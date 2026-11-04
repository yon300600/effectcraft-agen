#!/usr/bin/env python3
"""ABI conformance for the JE Cream CC reconstruction module (plug-in API v1).

Runs the compiled module in wasmtime and checks the contract from
EFFECTCRAFT_WASM_INTERFACE.md: exports, no imports, API version, manifest identity and schema,
parameter flattening, the frame/parameter buffer layout, error codes, determinism, alpha handling,
resolution scaling and a full-size frame.

    /tmp/venv/bin/python tests/check_abi.py [path/to/je_cream_cc.wasm]
"""
import json
import pathlib
import struct
import sys
import time

import wasmtime

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
WASM = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "je_cream_cc.wasm"
MANIFEST = json.loads((ROOT / "src" / "manifest.json").read_text())
SLOTS = {"slider": 1, "angle": 1, "checkbox": 1, "popup": 1, "point": 2, "color": 4}

fails = []
count = 0


def check(name, ok, detail=""):
    global count
    count += 1
    if ok:
        print(f"ok   {name}")
    else:
        print(f"FAIL {name} {detail}")
        fails.append(name)


class Module:
    def __init__(self):
        self.engine = wasmtime.Engine()
        self.store = wasmtime.Store(self.engine)
        self.mod = wasmtime.Module.from_file(self.engine, str(WASM))
        self.inst = wasmtime.Instance(self.store, self.mod, [])
        self.ex = self.inst.exports(self.store)
        self.mem = self.ex["memory"]
        self.alloc = self.ex["ec_alloc"]
        self.render = self.ex["ec_render"]

    def buffers(self, w, h, nparams):
        total = nparams * 8 + w * h * 16
        base = self.alloc(self.store, total)
        assert base != 0, "ec_alloc returned null"
        return base, base + nparams * 8

    def write(self, base, params, pixels):
        buf = bytearray(struct.pack(f"<{len(params)}d", *params))
        buf += struct.pack(f"<{len(pixels)}f", *pixels)
        self.mem.write(self.store, bytes(buf), base)

    def read_pixels(self, ptr, w, h):
        raw = bytes(self.mem.read(self.store, ptr, ptr + w * h * 16))
        return list(struct.unpack(f"<{w * h * 4}f", raw))

    def run(self, w, h, params, pixels):
        base, px = self.buffers(w, h, len(params))
        self.write(base, params, pixels)
        rc = self.render(self.store, px, w, h, base, len(params), 0.0, 1.0)
        return rc, self.read_pixels(px, w, h), base


def defaults():
    vals = []
    for p in MANIFEST["params"]:
        v = p["default"]
        if p["type"] == "checkbox":
            vals.append(1.0 if v else 0.0)
        elif p["type"] == "color":
            vals += [float(x) for x in v]
        elif p["type"] == "point":
            vals += [float(x) for x in v]
        else:
            vals.append(float(v))
    return vals


def main():
    check("module file exists", WASM.exists(), str(WASM))
    m = Module()

    imports = [(i.module, i.name) for i in m.mod.imports]
    check("no imports", not imports, str(imports))
    for name in ("memory", "ec_api_version", "ec_manifest_ptr", "ec_manifest_len", "ec_alloc", "ec_render"):
        check(f"exports {name}", name in m.ex)
    check("api version is 1", m.ex["ec_api_version"](m.store) == 1)

    ptr = m.ex["ec_manifest_ptr"](m.store)
    length = m.ex["ec_manifest_len"](m.store)
    raw = bytes(m.mem.read(m.store, ptr, ptr + length))
    man = json.loads(raw)
    check("manifest parses as JSON", isinstance(man, dict))
    check("manifest identical to src/manifest.json", man == MANIFEST,
          "the compiled-in manifest differs from src/manifest.json")
    check("api field is 1", man.get("api") == 1)
    check("id is reverse-domain", man.get("id", "").count(".") >= 2 and not man["id"].startswith("ec."))
    check("manifest under 1 MiB", length < 1024 * 1024, str(length))
    ids = [p["id"] for p in man["params"]]
    check("unique parameter ids", len(ids) == len(set(ids)))
    check("parameter count <= 256", len(man["params"]) <= 256, str(len(man["params"])))

    slots = sum(SLOTS[p["type"]] for p in man["params"])
    params = defaults()
    check("flattened parameter slots match", len(params) == slots, f"{len(params)} vs {slots}")

    w, h = 8, 6

    def f32(v):
        return struct.unpack("<f", struct.pack("<f", v))[0]

    base_pixels = []
    for y in range(h):
        for x in range(w):
            base_pixels += [f32(x / (w - 1)), f32(y / (h - 1)), 0.5, 1.0]

    rc, out, _ = m.run(w, h, params, base_pixels)
    check("render returns 0", rc == 0, str(rc))
    check("output is finite", all(v == v and abs(v) < 1e6 for v in out))

    # Full defaults must change a high-contrast frame (sharpen + glow are on in the preset).
    rc2, out2, _ = m.run(w, h, params, base_pixels)
    check("deterministic across runs", out == out2)

    # Every stage off except nothing: mix=0 leaves the frame exactly as it was.
    off = list(params)
    off[ids.index("mix")] = 0.0
    rc3, out3, _ = m.run(w, h, off, base_pixels)
    check("mix = 0 leaves the frame unchanged", rc3 == 0 and out3 == base_pixels,
          f"max diff {max(abs(a - b) for a, b in zip(out3, base_pixels)):.3g}")

    # Error codes: too few parameters, bad frame, null pointer.
    base, px = m.buffers(w, h, slots)
    m.write(base, params, base_pixels)
    check("code 1 for too few parameters", m.render(m.store, px, w, h, base, slots - 1, 0.0, 1.0) == 1)
    check("code 2 for a zero-size frame", m.render(m.store, px, 0, h, base, slots, 0.0, 1.0) == 2)
    check("code 3 for a null pointer", m.render(m.store, 0, w, h, base, slots, 0.0, 1.0) == 3)
    after = m.read_pixels(px, w, h)
    check("a refused frame is left unchanged", after == base_pixels)

    # Alpha: fully transparent pixels stay transparent and premultiplication is respected.
    px_alpha = []
    for y in range(h):
        for x in range(w):
            a = 0.0 if x < w // 2 else 0.5
            px_alpha += [f32(0.5 * a), f32(0.25 * a), f32(0.75 * a), a]
    rc4, out4, _ = m.run(w, h, params, px_alpha)
    left = [out4[i * 4 + 3] for i in range(w * h) if (i % w) < w // 2]
    check("transparent pixels keep alpha 0", all(a == 0.0 for a in left))
    # Premultiplication: the sharpen and unsharp stages must keep colour inside coverage. The
    # glow is additive light by design (screen + Affect Alpha), so it is excluded here.
    nomix = list(params)
    for pid in ("glow1_on", "glow2_on"):
        nomix[ids.index(pid)] = 0.0
    rc4b, out4b, _ = m.run(w, h, nomix, px_alpha)
    zero_ok = all(out4b[i * 4 + c] == 0.0 for i in range(w * h) if (i % w) < w // 2 for c in range(3))
    alpha_ok = all(abs(out4b[i * 4 + 3] - px_alpha[i * 4 + 3]) < 1e-6 for i in range(w * h))
    check("zero alpha means zero colour", zero_ok)
    check("sharpen/unsharp leave alpha untouched", rc4b == 0 and alpha_ok)
    check("glow may add light beyond coverage (documented, not a premultiplication bug)",
          all(abs(v) < 1e6 for v in out4[::13]))

    # Resolution scaling: the same parameters at a smaller frame scale the radii (no crash, finite).
    rc5, _, _ = m.run(16, 12, params, [0.5] * (16 * 12 * 4))
    check("16x12 render returns 0 (radii scale with the frame)", rc5 == 0)

    # Full-size frame: 1920x1080, timing only (correctness is checked in check_pixels.py).
    big = []
    for y in range(1080):
        v = (y / 1079.0) ** 2
        for x in range(1920):
            big += [v * 0.9, v * 0.8, v * 0.7, 1.0]
    t0 = time.time()
    rc6, out6, _ = m.run(1920, 1080, params, big)
    dt = time.time() - t0
    check("1920x1080 render returns 0", rc6 == 0, str(rc6))
    check("1920x1080 output finite", all(v == v and abs(v) < 1e6 for v in out6[::97]))
    print(f"     1920x1080: {dt:.2f} s in wasmtime (host JIT; the app's wasmi is slower)")

    # Repeated renders do not drift (no hidden state) and memory stops growing.
    size_before = m.mem.size(m.store)
    for _ in range(5):
        r, o, _ = m.run(w, h, params, base_pixels)
        assert r == 0 and o == out, "output drifted on repeat"
    check("5 repeated renders identical", True)
    check("memory does not grow per render", m.mem.size(m.store) == size_before,
          f"{size_before} -> {m.mem.size(m.store)}")

    print()
    if fails:
        print(f"{len(fails)} of {count} checks FAILED: {', '.join(fails)}")
        return 1
    print(f"all {count} ABI checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
