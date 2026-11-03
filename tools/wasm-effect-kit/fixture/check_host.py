#!/usr/bin/env python3
"""ABI conformance harness for EffectCraft WebAssembly effect plug-ins (plug-in API v1).

This is a *stand-in host*. It reproduces, step by step, what EffectCraft's real host does in
`crates/plugin/src/wasm.rs` when it renders a frame with a plug-in:

  1. instantiate the module with no imports, under a fuel budget and a memory limit;
  2. read `ec_api_version` (must be 1), then the manifest from `ec_manifest_ptr` /
     `ec_manifest_len` and validate it the way `PluginManifest::validate` does;
  3. `ec_alloc(total)` once for a buffer holding the flattened parameters (`nparams`
     little-endian f64) followed by the pixels (`width * height * 4` little-endian f32,
     premultiplied RGBA, row-major);
  4. write the buffer, call
     `ec_render(pixel_ptr, width, height, params_ptr, nparams, time, scale)`;
  5. read the pixels back; a non-zero return code or a trap leaves the frame unchanged.

It exists because EffectCraft's own host cannot be compiled in every environment (it needs a
Rust toolchain and the crates.io registry). Results from this harness are ABI-level evidence,
not proof that the Rust host ran; `tools/wasm-effect-kit/host/` is the real-host check to run
where cargo is available.

Usage:
    python3 check_host.py [--wasm ec_gain_blur.wasm] [--manifest plugin.json]
                          [--spin ec_spin.wasm] [--verbose]

Exit status is 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys
import time as _time

try:
    import wasmtime
except ImportError:  # pragma: no cover - environment guidance
    print("check_host.py: the 'wasmtime' Python package is required (pip install wasmtime).", file=sys.stderr)
    print("It is a real WebAssembly runtime (the same engine the wasmtime CLI uses).", file=sys.stderr)
    sys.exit(2)

PLUGIN_API_VERSION = 1
MAX_PARAMS = 256
MAX_MANIFEST = 1 << 20
# The budget in crates/plugin/src/wasm.rs: a base plus a per-pixel allowance.
FUEL_BASE = 50_000_000
FUEL_PER_PIXEL = 20_000
MAX_MEMORY = 1 << 30

ID_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
PARAM_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------
class Report:
    def __init__(self, verbose: bool) -> None:
        self.passed = 0
        self.failed = 0
        self.failures: list[str] = []
        self.verbose = verbose

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        if ok:
            self.passed += 1
            if self.verbose:
                print(f"  ok   {name}")
        else:
            self.failed += 1
            self.failures.append(f"{name}: {detail}")
            print(f"  FAIL {name}: {detail}")
        return ok

    def section(self, title: str) -> None:
        print(f"\n== {title} ==")


# --------------------------------------------------------------------------------------
# The stand-in host
# --------------------------------------------------------------------------------------
def f32(v: float) -> float:
    """Round an f64 to f32 exactly as wasm's f32.demote_f64 does (round-half-to-even)."""
    return struct.unpack("<f", struct.pack("<f", v))[0]


class HostError(Exception):
    pass


class Host:
    """What crates/plugin/src/wasm.rs does, in Python."""

    def __init__(self, wasm_path: str, consume_fuel: bool = True) -> None:
        self.raw = open(wasm_path, "rb").read()
        config = wasmtime.Config()
        if consume_fuel:
            config.consume_fuel = True
        self.engine = wasmtime.Engine(config)
        self.module = wasmtime.Module(self.engine, self.raw)
        if len(list(self.module.imports)) != 0:
            raise HostError("plug-ins can't import anything (the module has imports)")
        self.store = wasmtime.Store(self.engine)
        if consume_fuel:
            self.store.set_fuel(FUEL_BASE)
        self.instance = wasmtime.Instance(self.store, self.module, [])
        self.exports = self.instance.exports(self.store)
        missing = [n for n in ("memory", "ec_api_version", "ec_manifest_ptr", "ec_manifest_len", "ec_alloc", "ec_render") if n not in self.exports]
        if missing:
            raise HostError(f"the module exports no {', '.join(missing)}")
        self.memory = self.exports["memory"]
        self.manifest_text = self._read_manifest()
        self.manifest = json.loads(self.manifest_text)

    # -- loading ------------------------------------------------------------------
    def _read_manifest(self) -> str:
        version = self.exports["ec_api_version"](self.store)
        if version != PLUGIN_API_VERSION:
            raise HostError(f"the module implements plug-in API {version}, expected {PLUGIN_API_VERSION}")
        ptr = self.exports["ec_manifest_ptr"](self.store)
        length = self.exports["ec_manifest_len"](self.store)
        if not (0 <= length <= MAX_MANIFEST):
            raise HostError(f"bad manifest length {length}")
        return bytes(self.memory.read(self.store, ptr, ptr + length)).decode("utf-8", "replace")

    def validate_manifest(self) -> None:
        """Mirror of PluginManifest::validate in crates/effects/src/plugin.rs."""
        m = self.manifest
        if m.get("api") != PLUGIN_API_VERSION:
            raise HostError(f"manifest api is {m.get('api')}, expected {PLUGIN_API_VERSION}")
        if not m.get("id") or not ID_RE.match(m["id"]) or m["id"].startswith("ec."):
            raise HostError(f"bad id {m.get('id')!r}")
        if not m.get("name") or not m.get("category"):
            raise HostError("manifest needs a name and a category")
        params = m.get("params", [])
        if len(params) > MAX_PARAMS:
            raise HostError(f"{len(params)} parameters (at most {MAX_PARAMS})")
        seen = set()
        for p in params:
            pid = p.get("id", "")
            if not PARAM_ID_RE.match(pid) or pid in seen:
                raise HostError(f"bad or duplicate parameter id {pid!r}")
            seen.add(pid)
            kind = p.get("type")
            if kind == "slider":
                lo, hi = p.get("min", 0.0), p.get("max", 100.0)
                d = p.get("default", 0.0)
                smin, smax = p.get("sliderMin", lo), p.get("sliderMax", hi)
                if not all(math.isfinite(v) for v in (d, lo, hi, smin, smax)) or lo > hi or smin > smax or not (lo <= d <= hi):
                    raise HostError(f"slider {pid!r}: min <= default <= max (and sliderMin <= sliderMax)")
            elif kind == "popup":
                opts = p.get("options", [])
                if not opts or not (0 <= p.get("default", 0) < len(opts)):
                    raise HostError(f"popup {pid!r} needs options and a default index in range")
            elif kind not in ("angle", "checkbox", "point", "color"):
                raise HostError(f"parameter {pid!r}: unknown type {kind!r}")

    # -- parameters ---------------------------------------------------------------
    def flat_len(self) -> int:
        widths = {"point": 2, "color": 4}
        return sum(widths.get(p["type"], 1) for p in self.manifest["params"])

    def flatten(self, values: dict | None = None, point_scale: tuple[float, float, float] = (1.0, 0.0, 0.0)) -> list[float]:
        """Flatten parameters exactly like effects::plugin::flatten.

        `values` overrides declared values by parameter id (defaults otherwise). Point values
        are layer pixels; `point_scale` = (buffer scale, offset x, offset y) maps them to
        buffer pixels, as `Buf::to_px` does.
        """
        values = values or {}
        out: list[float] = []
        for p in self.manifest["params"]:
            kind = p["type"]
            v = values.get(p["id"], p.get("default"))
            if kind == "point":
                qx, qy = (v if isinstance(v, (list, tuple)) else (0.0, 0.0))
                out.extend([qx * point_scale[0] + point_scale[1], qy * point_scale[0] + point_scale[2]])
            elif kind == "color":
                out.extend([float(c) for c in (v if isinstance(v, (list, tuple)) else (1.0, 1.0, 1.0, 1.0))])
            elif kind == "checkbox":
                out.append(1.0 if v else 0.0)
            elif kind == "popup":
                out.append(float(v))
            else:
                out.append(float(v))
        return out

    # -- one frame ----------------------------------------------------------------
    def render(
        self,
        pixels: list[tuple[float, float, float, float]],
        width: int,
        height: int,
        params: list[float],
        time: float = 0.0,
        scale: float = 1.0,
        fuel_per_pixel: bool = True,
        alloc: bool = True,
    ) -> tuple[int, list[tuple[float, float, float, float]]]:
        """Render one frame. Returns (return code, pixels). A trap raises HostError.

        `alloc=False` keeps the buffer a previous `ec_alloc` handed out (used to prove the
        module refuses a frame that does not fit instead of overrunning memory).
        """
        n = len(pixels)
        params_bytes = len(params) * 8
        total = params_bytes + n * 16
        if total > 0x7FFFFFFF:
            raise HostError("frame too large for a 32-bit plug-in")
        if fuel_per_pixel:
            self.store.set_fuel(FUEL_BASE + FUEL_PER_PIXEL * n)
        else:
            self.store.set_fuel(FUEL_BASE)
        if alloc:
            base = self.exports["ec_alloc"](self.store, total)
            if base == 0:
                raise HostError("ec_alloc returned 0")
            self.last_base = base
            self.last_total = total
        else:
            base = self.last_base
        if total > getattr(self, "last_total", 0):
            # The host never writes past the buffer it asked for; this is exactly the
            # "frame does not fit" case, so only the parameters are written.
            self.memory.write(self.store, struct.pack("<%dd" % len(params), *params), base)
            try:
                return self.exports["ec_render"](self.store, base + params_bytes, width, height, base, len(params), time, scale), list(pixels)
            except wasmtime.Trap as e:
                raise HostError(f"ec_render trapped: {e}") from e
        buf = bytearray()
        buf += struct.pack("<%dd" % len(params), *params)
        for px in pixels:
            buf += struct.pack("<4f", *px)
        self.memory.write(self.store, bytes(buf), base)
        px_ptr = base + params_bytes
        try:
            code = self.exports["ec_render"](self.store, px_ptr, width, height, base, len(params), time, scale)
        except wasmtime.Trap as e:  # fuel exhaustion, unreachable, out of bounds…
            raise HostError(f"ec_render trapped: {e}") from e
        out = list(pixels)
        if code == 0:
            data = bytes(self.memory.read(self.store, px_ptr, px_ptr + n * 16))
            for i in range(n):
                out[i] = struct.unpack_from("<4f", data, i * 16)
        return code, out

    def alloc(self, total: int) -> int:
        return self.exports["ec_alloc"](self.store, total)

    def fuel_left(self) -> int | None:
        try:
            return self.store.get_fuel()
        except Exception:
            return None


# --------------------------------------------------------------------------------------
# Independent reference implementation of the fixture's math
# --------------------------------------------------------------------------------------
def reference(
    pixels: list[tuple[float, float, float, float]],
    width: int,
    height: int,
    values: dict,
    time: float = 0.0,
    scale: float = 1.0,
) -> list[tuple[float, float, float, float]]:
    """The fixture algorithm, written from its description, in the same f64 order as the C.

    radius, gain, tint (4), mix, mode, origin (2), enable — see fixture/plugin.json.
    """

    def clamp(v, lo, hi):
        return lo if v < lo else hi if v > hi else v

    def iround(v):
        return int(v - 0.5 if v < 0 else v + 0.5)

    enable = values.get("enable", True)
    mode = iround(float(values.get("mode", 0)))
    img = [[float(c) for c in px] for px in pixels]
    if not enable or mode == 2:
        return [tuple(f32(c) for c in px) for px in img]
    if mode == 1:
        out = []
        for px in img:
            a = clamp(px[3], 0.0, 1.0)
            na = 1.0 - a
            k = (na / a) if a > 0.0 else 0.0
            out.append((f32(px[0] * k), f32(px[1] * k), f32(px[2] * k), f32(na)))
        return out

    radius = iround(clamp(float(values.get("radius", 1.0)), 0.0, 64.0) * clamp(scale, 0.0, 8.0))  # manifest default: 1
    radius = min(radius, 64)
    if radius > 0:
        # Horizontal pass.
        tmp = [0.0] * (width * height * 4)
        for y in range(height):
            for x in range(width):
                acc = [0.0, 0.0, 0.0, 0.0]
                n = 0.0
                for k in range(-radius, radius + 1):
                    sx = min(max(x + k, 0), width - 1)
                    p = img[y * width + sx]
                    for c in range(4):
                        acc[c] += p[c]
                    n += 1.0
                for c in range(4):
                    tmp[(y * width + x) * 4 + c] = acc[c] / n
        # Vertical pass.
        for y in range(height):
            for x in range(width):
                acc = [0.0, 0.0, 0.0, 0.0]
                n = 0.0
                for k in range(-radius, radius + 1):
                    sy = min(max(y + k, 0), height - 1)
                    p = tmp[(sy * width + x) * 4 : sy * width * 4 + x * 4 + 4]
                    for c in range(4):
                        acc[c] += p[c]
                    n += 1.0
                for c in range(4):
                    img[y * width + x][c] = acc[c] / n

    gain = clamp(float(values.get("gain", 1.0)), 0.0, 4.0)
    gain *= 1.0 + 0.25 * clamp(time, 0.0, 4.0)
    mix = clamp(float(values.get("mix", 0.0)), 0.0, 100.0) / 100.0
    default_tint = values.get("tint", (1.0, 0.5, 0.2, 1.0))
    tint = [clamp(float(default_tint[0]), 0.0, 4.0), clamp(float(default_tint[1]), 0.0, 4.0), clamp(float(default_tint[2]), 0.0, 4.0)]
    origin = values.get("origin", (width * 0.5, height * 0.5))
    ox, oy = float(origin[0]), float(origin[1])
    half = 0.5 * float(max(width, height)) or 1.0

    out = []
    for y in range(height):
        for x in range(width):
            px = img[y * width + x]
            a = px[3]
            c0, c1, c2 = px[0] * gain, px[1] * gain, px[2] * gain
            if mix > 0.0:
                dx = (x + 0.5 - ox) / half
                dy = (y + 0.5 - oy) / half
                d = math.sqrt(dx * dx + dy * dy)
                falloff = max(1.0 - d, 0.0)
                m = mix * falloff
                c0 = c0 * (1.0 - m) + tint[0] * a * m
                c1 = c1 * (1.0 - m) + tint[1] * a * m
                c2 = c2 * (1.0 - m) + tint[2] * a * m
            out.append((f32(max(c0, 0.0)), f32(max(c1, 0.0)), f32(max(c2, 0.0)), f32(clamp(a, 0.0, 1.0))))
    return out


# --------------------------------------------------------------------------------------
# Test images
# --------------------------------------------------------------------------------------
def gradient(w: int, h: int) -> list[tuple[float, float, float, float]]:
    """A small test image.

    Components are quantized to f32: the host writes pixels as f32, so a comparison against
    the reference is only meaningful on values that survive that conversion unchanged.
    """
    px = []
    for y in range(h):
        for x in range(w):
            px.append(
                tuple(
                    f32(v)
                    for v in (
                        ((x * 2) % 8) / 8.0,
                        ((y * 2) % 8) / 8.0,
                        ((x + y) % 4) / 4.0,
                        min(1.0, (x + 1) / float(w)),
                    )
                )
            )
    return px


def max_diff(a, b) -> float:
    d = 0.0
    for pa, pb in zip(a, b):
        for ca, cb in zip(pa, pb):
            if ca != cb:
                d = max(d, abs(ca - cb))
    return d


def main(argv=None) -> int:
    here = __file__.rsplit("/", 1)[0]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wasm", default=f"{here}/ec_gain_blur.wasm")
    ap.add_argument("--manifest", default=f"{here}/plugin.json")
    ap.add_argument("--spin", default=f"{here}/ec_spin.wasm")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    r = Report(args.verbose)
    digest = hashlib.sha256(open(args.wasm, "rb").read()).hexdigest()
    print(f"wasm:     {args.wasm} ({len(open(args.wasm,'rb').read())} bytes, sha256 {digest})")
    print(f"manifest: {args.manifest}")
    print(f"runtime:  wasmtime-py {getattr(wasmtime, '__version__', '')}".rstrip())

    # -- 1. compilation output and module shape ------------------------------------
    r.section("module")
    raw = open(args.wasm, "rb").read()
    r.check("valid wasm binary (magic + version)", raw[:4] == b"\x00asm" and raw[4:8] == b"\x01\x00\x00\x00", raw[:8].hex())
    host = Host(args.wasm)
    r.check("module has no imports", len(list(host.module.imports)) == 0, str(list(host.module.imports)))
    r.check("ec_api_version() == 1", host.exports["ec_api_version"](host.store) == 1)
    r.check("memory is exported", host.exports["memory"] is not None)
    for name in ("ec_manifest_ptr", "ec_manifest_len", "ec_alloc", "ec_render"):
        r.check(f"export {name}", name in host.exports)

    # -- 2. manifest ---------------------------------------------------------------
    r.section("manifest")
    declared = json.load(open(args.manifest))
    r.check("module manifest equals plugin.json (canonical JSON)", json.loads(host.manifest_text) == declared,
            f"module={host.manifest_text[:120]}")
    try:
        host.validate_manifest()
        r.check("manifest passes the host's validation rules", True)
    except HostError as e:
        r.check("manifest passes the host's validation rules", False, str(e))
    r.check("manifest id is reverse-domain, not reserved 'ec.'", host.manifest["id"].startswith("org.effectcraft."))
    r.check("flattened parameter count is 11", host.flat_len() == 11, str(host.flat_len()))

    # -- 3. defaults, parameters, pixels -------------------------------------------
    r.section("pixels (3x2 and 5x4 test frames)")
    for (w, h) in ((3, 2), (5, 4)):
        src = gradient(w, h)
        flat = host.flatten({"origin": (w * 0.5, h * 0.5)})
        code, out = host.render(src, w, h, flat)
        ref = reference(src, w, h, {"origin": (w * 0.5, h * 0.5)})
        r.check(f"{w}x{h}: render returns 0", code == 0, f"code {code}")
        r.check(f"{w}x{h}: pixels match the reference exactly", out == ref, f"max diff {max_diff(out, ref)}")
        r.check(f"{w}x{h}: output keeps the input size", len(out) == w * h)

    r.section("parameters change the result (and only as documented)")
    src = gradient(5, 4)
    base = {"origin": (2.5, 2.0)}
    code, plain = host.render(src, 5, 4, host.flatten(base))
    r.check("defaults render", code == 0)

    # Pass-through: gain 1, radius 0, mix 0, time 0 → bit-identical to the input.
    passthru = dict(base, radius=0, gain=1.0, mix=0.0)
    code, same = host.render(src, 5, 4, host.flatten(passthru))
    r.check("identity parameters leave the frame bit-identical", same == src, f"max diff {max_diff(same, src)}")

    # Gain.
    code, gained = host.render(src, 5, 4, host.flatten(dict(passthru, gain=2.0)))
    r.check("gain 2.0 doubles RGB (alpha untouched)",
            all(o[0] == f32(2.0 * s[0]) and o[3] == f32(s[3]) for o, s in zip(gained, src)),
            "rgb not doubled or alpha changed")

    # Blur actually blurs: radius 2 must differ from radius 0, and match the reference.
    code, blurred = host.render(src, 5, 4, host.flatten(dict(passthru, radius=2)))
    ref_blur = reference(src, 5, 4, dict(passthru, radius=2))
    r.check("radius 2 changes the frame", blurred != same, "blur had no effect")
    r.check("radius 2 matches the reference exactly", blurred == ref_blur, f"max diff {max_diff(blurred, ref_blur)}")

    # Scale: radius 1 at scale 2 == radius 2 at scale 1 (blur radii follow buffer resolution).
    code, scaled = host.render(src, 5, 4, host.flatten(dict(passthru, radius=1)), scale=2.0)
    r.check("scale doubles the effective radius", scaled == blurred, f"max diff {max_diff(scaled, blurred)}")

    # Popup modes.
    code, pass2 = host.render(src, 5, 4, host.flatten(dict(passthru, mode=2)))
    r.check("popup mode 2 (pass through) leaves pixels unchanged", pass2 == src)
    code, inverted = host.render(src, 5, 4, host.flatten(dict(passthru, mode=1)))
    r.check("popup mode 1 inverts alpha", inverted == reference(src, 5, 4, dict(passthru, mode=1)),
            f"max diff {max_diff(inverted, reference(src, 5, 4, dict(passthru, mode=1)))}")

    # Checkbox.
    code, disabled = host.render(src, 5, 4, host.flatten(dict(passthru, enable=False, gain=3.0)))
    r.check("checkbox off disables the effect", disabled == src)

    # Colour and point parameters reach the module.
    tinted = dict(passthru, mix=100.0, tint=[0.0, 1.0, 0.0, 1.0])
    code, tint_out = host.render(src, 5, 4, host.flatten(tinted))
    r.check("colour parameter changes the mix", tint_out == reference(src, 5, 4, tinted), "tint mismatch")
    moved = dict(tinted, origin=(0.0, 0.0))
    code, moved_out = host.render(src, 5, 4, host.flatten(moved))
    r.check("point parameter moves the tint falloff", moved_out != tint_out and moved_out == reference(src, 5, 4, moved))

    # Time reaches the module (per-frame parameter evaluation in an animated effect).
    code, t0 = host.render(src, 5, 4, host.flatten(dict(passthru, gain=1.0)), time=0.0)
    code, t4 = host.render(src, 5, 4, host.flatten(dict(passthru, gain=1.0)), time=4.0)
    r.check("time=4 s doubles the gain (animation reaches the module)",
            all(o[0] == f32(2.0 * s[0]) for o, s in zip(t4, src)), "time had no effect")
    r.check("time=0 leaves the gain alone", t0 == src)

    # Alpha handling.
    alpha_src = [(0.25, 0.25, 0.25, 1.0), (0.0, 0.0, 0.0, 0.0), (0.5, 0.5, 0.5, 0.5), (0.0, 0.0, 0.0, 1.0)]  # exact in f32
    code, alpha_out = host.render(alpha_src, 2, 2, host.flatten({"origin": (1.0, 1.0), "radius": 0, "mix": 0, "gain": 1.0}))
    r.check("alpha channel preserved for identity parameters", [p[3] for p in alpha_out] == [p[3] for p in alpha_src])
    code, alpha_blur = host.render(alpha_src, 2, 2, host.flatten({"origin": (1.0, 1.0), "radius": 1, "mix": 0, "gain": 1.0}))
    r.check("alpha stays inside 0..1 after blurring", all(0.0 <= p[3] <= 1.0 for p in alpha_blur),
            str([p[3] for p in alpha_blur]))

    # -- 4. error codes -------------------------------------------------------------
    r.section("error handling")
    buf = host.alloc(11 * 8 + 2 * 2 * 16)
    r.check("ec_alloc returns an 8-byte-aligned pointer", buf % 8 == 0, str(buf))
    code, _ = host.render(src, 0, 0, host.flatten(passthru))
    r.check("zero-sized frame is refused with code 2", code == 2, f"code {code}")
    code, unchanged = host.render(src, 5, 4, host.flatten(passthru)[:5])
    r.check("too few parameters is refused with code 1", code == 1, f"code {code}")
    r.check("a refused frame leaves the pixels unchanged", unchanged == src)
    # Ask for more pixels than ec_alloc provided for: the module must refuse, not overrun.
    host.render(src, 5, 4, host.flatten(passthru))  # ec_alloc for a 5x4 frame
    big = gradient(64, 64)
    code, untouched = host.render(big, 64, 64, host.flatten(passthru), alloc=False)
    r.check("a frame larger than the allocated buffer is refused with code 4", code == 4, f"code {code}")
    r.check("the refused frame is left unchanged", untouched == big)

    # -- 5. reuse, determinism, resource behaviour ----------------------------------
    r.section("repeated processing")
    host.alloc(11 * 8 + 20 * 20 * 16)
    small = gradient(20, 20)
    first = host.render(small, 20, 20, host.flatten(dict(passthru, radius=1)))[1]
    ok = all(host.render(small, 20, 20, host.flatten(dict(passthru, radius=1)))[1] == first for _ in range(200))
    r.check("200 renders on one instance are bit-identical", ok, "output drifted")
    r.check("the instance is still usable after 200 renders", host.render(small, 20, 20, host.flatten(passthru))[0] == 0)
    mem_pages = host.exports["memory"].size(host.store)
    for _ in range(20):
        host.render(small, 20, 20, host.flatten(passthru))
    r.check("memory stops growing once the buffer is big enough", host.exports["memory"].size(host.store) == mem_pages,
            f"{host.exports['memory'].size(host.store)} vs {mem_pages} pages")

    # -- 6. large frames ------------------------------------------------------------
    r.section("large frames")
    w, h = 1920, 1080
    big_frame = [(((x % 16) / 16.0), ((y % 16) / 16.0), ((x + y) % 8) / 8.0, 1.0) for y in range(h) for x in range(w)]  # exact in f32
    t0 = _time.time()
    code, out = host.render(big_frame, w, h, host.flatten({"origin": (w * 0.5, h * 0.5), "radius": 2, "gain": 1.0, "mix": 25.0}))
    elapsed = _time.time() - t0
    r.check(f"{w}x{h} frame renders (code 0)", code == 0, f"code {code}")
    r.check(f"{w}x{h} frame keeps its size and alpha", len(out) == w * h and all(0.0 <= p[3] <= 1.0 for p in out[:1000]))
    r.check(f"{w}x{h} frame output is finite", all(math.isfinite(c) for p in out[:5000] for c in p))
    print(f"       ({elapsed:.2f} s for one {w}x{h} frame through wasmtime, radius 2, in Python)")

    # -- 7. execution limits --------------------------------------------------------
    r.section("execution limits")
    spin = Host(args.spin)
    r.check("the runaway fixture loads", spin.exports["ec_render"] is not None)
    spin.store.set_fuel(FUEL_BASE)
    started = _time.time()
    try:
        spin.render([(0.0, 0.0, 0.0, 1.0)], 1, 1, [], fuel_per_pixel=False)
        r.check("a runaway module is stopped by the fuel budget", False, "it returned")
    except HostError as e:
        r.check("a runaway module is stopped by the fuel budget", "fuel" in str(e).lower(), str(e))
    print(f"       (stopped after {_time.time() - started:.2f} s)")

    # -- 8. reload ---------------------------------------------------------------
    r.section("module lifecycle")
    del host
    again = Host(args.wasm)
    code, out2 = again.render(gradient(5, 4), 5, 4, again.flatten({"origin": (2.5, 2.0)}))
    r.check("the module reloads into a fresh instance and renders", code == 0 and out2 == reference(gradient(5, 4), 5, 4, {"origin": (2.5, 2.0)}))

    print(f"\n{'-'*60}\n{r.passed} checks passed, {r.failed} failed")
    if r.failed:
        print("\nfailures:")
        for f in r.failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
