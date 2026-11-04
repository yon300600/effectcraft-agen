#!/usr/bin/env python3
"""Pixel comparison: the compiled module against the independent Python reference.

The reference (tests/reference.py) is a second implementation of the same maths in IEEE single
precision, so agreement is bit-exact or it is a bug. Each case isolates a stage so a mismatch
points at the stage that produced it.

    /tmp/venv/bin/python tests/check_pixels.py [path/to/je_cream_cc.wasm]
"""
import json
import pathlib
import struct
import sys

import numpy as np
import wasmtime

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reference  # noqa: E402

ROOT = HERE.parent
WASM = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "je_cream_cc.wasm"
MANIFEST = json.loads((ROOT / "src" / "manifest.json").read_text())
PARAMS = {p["id"]: p for p in MANIFEST["params"]}

W, H = 48, 32


def f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def test_image():
    """A deterministic frame with edges, a highlight (for the glow) and a colour gradient."""
    px = []
    for y in range(H):
        for x in range(W):
            fx, fy = x / (W - 1), y / (H - 1)
            r = 0.15 + 0.7 * fx
            g = 0.10 + 0.6 * fy
            b = 0.05 + 0.3 * (1.0 - fx)
            if (x // 6 + y // 5) % 2 == 0:  # checker: hard edges for the sharpen
                r, g, b = r * 0.55, g * 0.55, b * 0.55
            d2 = (x - 34) ** 2 + (y - 11) ** 2
            if d2 < 18:  # a bright spot: energy for the glow
                r, g, b = 0.95, 0.93, 0.85
            a = 1.0 if y < H - 6 else 0.6  # a softer alpha band at the bottom
            px += [f32(r * a), f32(g * a), f32(b * a), f32(a)]  # premultiplied
    return px


class Mod:
    def __init__(self):
        eng = wasmtime.Engine()
        self.store = wasmtime.Store(eng)
        mod = wasmtime.Module.from_file(eng, str(WASM))
        inst = wasmtime.Instance(self.store, mod, [])
        self.ex = inst.exports(self.store)
        self.mem = self.ex["memory"]

    def run(self, pix, params, w=W, h=H, scale=1.0):
        total = len(params) * 8 + w * h * 16
        base = self.ex["ec_alloc"](self.store, total)
        ptr = base + len(params) * 8
        buf = bytearray(struct.pack(f"<{len(params)}d", *params))
        buf += struct.pack(f"<{w * h * 4}f", *pix)
        self.mem.write(self.store, bytes(buf), base)
        rc = self.ex["ec_render"](self.store, ptr, w, h, base, len(params), 0.0, scale)
        if rc != 0:
            raise RuntimeError(f"ec_render returned {rc}")
        raw = bytes(self.mem.read(self.store, ptr, ptr + w * h * 16))
        return list(struct.unpack(f"<{w * h * 4}f", raw))


def with_params(**over):
    p = reference.defaults()
    for k, v in over.items():
        p[reference.slot_of(k)] = float(v)
    return p


def main():
    m = Mod()
    img = test_image()
    fails = 0
    checks = 0

    cases = {
        "preset defaults (all five stages)": {},
        "sharpen only": {"unsharp_on": 0, "glow1_on": 0, "glow2_on": 0},
        "unsharp only": {"sharpen_on": 0, "glow1_on": 0, "glow2_on": 0},
        "glow 2 only": {"sharpen_on": 0, "unsharp_on": 0, "glow1_on": 0},
        "glow 1 only (threshold 2.64: no energy)": {"sharpen_on": 0, "unsharp_on": 0, "glow2_on": 0},
        "glow 2, Add, tinted": {"sharpen_on": 0, "unsharp_on": 0, "glow1_on": 0, "glow2_combine": 1,
                                "glow2_color": 1.0},
        "quality = Fast": {"quality": 1},
        "reduce flicker 1-2-1": {"sharpen_on": 0, "glow1_on": 0, "glow2_on": 0, "flicker": 1},
        "mix 50%": {"mix": 50},
        "unsharp threshold + negative mix": {"sharpen_on": 0, "glow1_on": 0, "glow2_on": 0,
                                             "unsharp_threshold": 3, "unsharp_mix": -60},
    }

    for name, over in cases.items():
        params = with_params(**over)
        # a colour parameter needs all four slots written explicitly
        if "glow2_color" in over:
            base = reference.slot_of("glow2_color")
            params[base:base + 4] = [1.0, 0.55, 0.2, 1.0]
        got = m.run(img, params)
        want = reference.render(img, W, H, params)
        diff = [abs(a - b) for a, b in zip(got, want)]
        worst = max(diff)
        checks += 1
        if worst == 0.0:
            print(f"ok   {name}: bit-identical to the reference ({len(got)} values)")
        else:
            fails += 1
            bad = sum(1 for d in diff if d != 0.0)
            idx = diff.index(worst)
            print(f"FAIL {name}: {bad} of {len(diff)} values differ, worst {worst:.3g} "
                  f"at index {idx} (module {got[idx]!r}, reference {want[idx]!r})")

    # The effect must actually change the frame - a no-op module would pass "deterministic".
    got = m.run(img, with_params())
    changed = sum(1 for a, b in zip(got, img) if a != b)
    checks += 1
    if changed > len(img) // 10:
        print(f"ok   the preset's settings change the frame ({changed} of {len(got)} values)")
    else:
        fails += 1
        print(f"FAIL the effect is a no-op ({changed} values changed)")

    # Glow 1 at its stored threshold must be a no-op (energy = luma - 2.64 is never positive).
    g1 = m.run(img, with_params(sharpen_on=0, unsharp_on=0, glow2_on=0))
    ref_id = [f32(v) for v in img]
    checks += 1
    if all(abs(a - b) < 1e-6 for a, b in zip(g1, ref_id)):
        print("ok   glow 1 with threshold 2.64 contributes nothing, as its parameter implies")
    else:
        fails += 1
        print(f"FAIL glow 1 changed the frame at threshold 2.64 (worst {max(abs(a-b) for a, b in zip(g1, ref_id)):.3g})")

    # Preview scale must scale the radii: a half-scale render is not the full-scale one.
    a = m.run(img, with_params(), scale=0.5)
    b = m.run(img, with_params(), scale=1.0)
    checks += 1
    if a != b:
        print("ok   `scale` reaches the module (half-scale preview differs from full-scale)")
    else:
        fails += 1
        print("FAIL `scale` had no effect on a radius-dependent effect")

    # Engine independence: the same binary, the same frame, in V8 (Node) instead of wasmtime.
    import hashlib
    import json as _json
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    checks += 1
    if not node:
        fails += 1
        print("FAIL node is not installed: the second engine was not exercised")
    else:
        params = with_params()
        got = m.run(img, params)
        want_hash = hashlib.sha256(struct.pack(f"<{len(got)}f", *got)).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            frame = pathlib.Path(td) / "frame.json"
            frame.write_text(_json.dumps({"w": W, "h": H, "pixels": img, "params": params}))
            r = subprocess.run([node, str(HERE / "check_v8.mjs"), str(WASM), str(frame)],
                               capture_output=True, text=True)
        if r.returncode != 0:
            print(f"FAIL V8 run failed: {r.stderr.strip()[:200]}")
        else:
            v8_hash = r.stdout.split()[0]
            if v8_hash == want_hash:
                print("ok   V8 (Node) produces byte-identical output to wasmtime")
            else:
                fails += 1
                print(f"FAIL V8 differs from wasmtime: {v8_hash[:16]} vs {want_hash[:16]}")

    print()
    if fails:
        print(f"{fails} of {checks} pixel checks FAILED")
        return 1
    print(f"all {checks} pixel checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
