#!/usr/bin/env python3
"""Render stills through the compiled module, so the reconstruction's look can be inspected.

    tests/render_stills.py                          # docs/source-portrait.png -> docs/*.png
    tests/render_stills.py --set sharpen_amp=1.4    # try a different setting
    tests/render_stills.py --input photo.png --out /tmp/stills

Needs `wasmtime` and `Pillow`. The module is fed exactly what EffectCraft feeds it: display-referred
premultiplied f32 RGBA with `scale = 1`, parameters in manifest order (see TEST-RESULTS.md §4).
"""
import argparse
import json
import os
import struct
import sys
import time

import wasmtime
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WASM = os.path.join(HERE, "build", "je_cream_cc.wasm")
MANIFEST = os.path.join(HERE, "src", "manifest.json")


def default_params(manifest, overrides):
    flat, seen = [], set()
    for p in manifest["params"]:
        v = p["default"]
        key = p["id"]
        if key in overrides:
            raw = overrides[key]
            if p["type"] == "checkbox":
                v = raw.lower() in ("1", "true", "on", "yes")
            elif p["type"] in ("color", "point"):
                v = [float(x) for x in raw.split(",")]
            elif p["type"] == "slider":
                v = float(raw)
            else:
                v = int(raw)
            seen.add(key)
        if p["type"] == "checkbox":
            flat.append(1.0 if v else 0.0)
        elif p["type"] in ("color", "point"):
            flat += [float(x) for x in v]
        else:
            flat.append(float(v))
    unknown = set(overrides) - seen
    if unknown:
        sys.exit(f"unknown parameter(s): {', '.join(sorted(unknown))}")
    return flat


def render(img, params, scale=1.0):
    """img: RGBA image, premultiplied floats are built here. Returns float RGBA floats."""
    w, h = img.size
    px = list(img.convert("RGBA").getdata())
    flat = []
    for r, g, b, a8 in px:
        a = a8 / 255.0
        flat += [r / 255.0 * a, g / 255.0 * a, b / 255.0 * a, a]

    eng = wasmtime.Engine()
    store = wasmtime.Store(eng)
    inst = wasmtime.Instance(store, wasmtime.Module.from_file(eng, WASM), [])
    ex = inst.exports(store)
    total = len(params) * 8 + w * h * 16
    base = ex["ec_alloc"](store, total)
    if not base:
        sys.exit("ec_alloc returned null")
    buf = bytearray(struct.pack(f"<{len(params)}d", *params))
    buf += struct.pack(f"<{len(flat)}f", *flat)
    ex["memory"].write(store, bytes(buf), base)
    t0 = time.perf_counter()
    rc = ex["ec_render"](store, base + len(params) * 8, w, h, base, len(params), 0.0, scale)
    dt = time.perf_counter() - t0
    if rc != 0:
        sys.exit(f"ec_render returned {rc}")
    raw = bytes(ex["memory"].read(store, base + len(params) * 8, base + len(params) * 8 + w * h * 16))
    out = struct.unpack(f"<{w * h * 4}f", raw)
    return out, dt


def to_image(out, size):
    w, h = size
    im = Image.new("RGBA", size)
    data = []
    for i in range(w * h):
        a = out[i * 4 + 3]
        if a <= 0.0:
            data.append((0, 0, 0, 0))
            continue
        rgb = [min(max(out[i * 4 + c] / a, 0.0), 1.0) for c in range(3)]
        data.append(tuple([int(round(v * 255.0)) for v in rgb] + [int(round(min(max(a, 0.0), 1.0) * 255.0))]))
    im.putdata(data)
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=os.path.join(HERE, "docs", "source-portrait.jpg"))
    ap.add_argument("--out", default=os.path.join(HERE, "docs"))
    ap.add_argument("--width", type=int, default=1280, help="downscale the input to this width (0 = keep)")
    ap.add_argument("--crop", default="0.10,0.20,0.35,0.55", help="x0,y0,x1,y1 of the detail crop, 0..1")
    ap.add_argument("--zoom", type=int, default=2)
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--format", choices=("jpg", "png"), default="jpg")
    ap.add_argument("--quality", type=int, default=92)
    args = ap.parse_args()

    overrides = dict(s.split("=", 1) for s in args.set)
    params = default_params(json.load(open(MANIFEST)), overrides)

    src = Image.open(args.input)
    if args.width and src.width > args.width:
        src = src.resize((args.width, round(src.height * args.width / src.width)), Image.LANCZOS)
    src = src.convert("RGBA")
    os.makedirs(args.out, exist_ok=True)

    out, dt = render(src, params)
    after = to_image(out, src.size)

    ext = ".jpg" if args.format == "jpg" else ".png"
    before_p = os.path.join(args.out, "before" + ext)
    after_p = os.path.join(args.out, "after" + ext)

    def save(im, path):
        if path.endswith(".jpg"):
            im.convert("RGB").save(path, quality=args.quality, subsampling=0)
        else:
            im.save(path)

    save(src, before_p)
    save(after, after_p)

    px_b = list(src.getdata())
    px_a = list(after.getdata())
    diffs = [abs(px_a[i][c] - px_b[i][c]) for i in range(len(px_a)) for c in range(3)]
    print(f"{src.width}x{src.height}: {dt * 1000:.0f} ms in wasmtime "
          f"({dt * 1e6 / (src.width * src.height):.1f} us/pixel)")
    print(f"mean |after - before| = {sum(diffs) / len(diffs):.2f}/255, "
          f"max {max(diffs)}/255, changed {100.0 * sum(1 for d in diffs if d) / len(diffs):.1f}% of channels")

    x0, y0, x1, y1 = (float(v) for v in args.crop.split(","))
    box = (int(x0 * src.width), int(y0 * src.height), int(x1 * src.width), int(y1 * src.height))
    z = args.zoom
    for name, im in (("detail-before" + ext, src), ("detail-after" + ext, after)):
        c = im.crop(box)
        save(c.resize((c.width * z, c.height * z), Image.NEAREST), os.path.join(args.out, name))
    print(f"detail crop {box} at {z}x -> detail-before{ext} / detail-after{ext}")
    if overrides:
        print("settings overridden: " + ", ".join(f"{k}={v}" for k, v in overrides.items()))


if __name__ == "__main__":
    main()
