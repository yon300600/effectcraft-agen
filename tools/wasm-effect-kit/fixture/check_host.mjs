#!/usr/bin/env node
// ABI conformance harness, second runtime: Node's own WebAssembly engine (V8).
//
// Same contract as check_host.py (which uses wasmtime), implemented independently: it proves
// the fixture module is not tied to one engine, and that a browser-side V8 runs it too. It
// does not repeat every check — see check_host.py for the full list.
//
// Usage: node check_host.mjs [--wasm ec_gain_blur.wasm] [--manifest plugin.json]

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};
const wasmPath = arg("--wasm", path.join(here, "ec_gain_blur.wasm"));
const manifestPath = arg("--manifest", path.join(here, "plugin.json"));

let passed = 0;
const failures = [];
function check(name, ok, detail = "") {
  if (ok) {
    passed++;
  } else {
    failures.push(`${name}: ${detail}`);
    console.log(`  FAIL ${name}: ${detail}`);
  }
}

const f32 = (v) => Math.fround(v);

/** The fixture's math, written from its description (same f64 order as the C). */
function reference(pixels, width, height, values, time = 0, scale = 1) {
  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
  const iround = (v) => Math.trunc(v < 0 ? v - 0.5 : v + 0.5);
  const enable = values.enable ?? true;
  const mode = iround(values.mode ?? 0);
  let img = pixels.map((p) => p.slice());
  if (!enable || mode === 2) return pixels.map((p) => p.map(f32));
  if (mode === 1) {
    return img.map(([r, g, b, a0]) => {
      const a = clamp(a0, 0, 1);
      const na = 1 - a;
      const k = a > 0 ? na / a : 0;
      return [f32(r * k), f32(g * k), f32(b * k), f32(na)];
    });
  }
  const radius = Math.min(iround(clamp(values.radius ?? 1, 0, 64) * clamp(scale, 0, 8)), 64);
  if (radius > 0) {
    const tmp = new Array(width * height * 4).fill(0);
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const acc = [0, 0, 0, 0];
        let n = 0;
        for (let k = -radius; k <= radius; k++) {
          const sx = Math.min(Math.max(x + k, 0), width - 1);
          const p = img[y * width + sx];
          for (let c = 0; c < 4; c++) acc[c] += p[c];
          n += 1;
        }
        for (let c = 0; c < 4; c++) tmp[(y * width + x) * 4 + c] = acc[c] / n;
      }
    }
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const acc = [0, 0, 0, 0];
        let n = 0;
        for (let k = -radius; k <= radius; k++) {
          const sy = Math.min(Math.max(y + k, 0), height - 1);
          const o = (sy * width + x) * 4;
          for (let c = 0; c < 4; c++) acc[c] += tmp[o + c];
          n += 1;
        }
        for (let c = 0; c < 4; c++) img[y * width + x][c] = acc[c] / n;
      }
    }
  }
  let gain = clamp(values.gain ?? 1, 0, 4);
  gain *= 1 + 0.25 * clamp(time, 0, 4);
  const mix = clamp(values.mix ?? 0, 0, 100) / 100;
  const tint = (values.tint ?? [1.0, 0.5, 0.2, 1.0]).slice(0, 3).map((v) => clamp(v, 0, 4));
  const [ox, oy] = values.origin ?? [width * 0.5, height * 0.5];
  const half = 0.5 * Math.max(width, height) || 1;
  const out = [];
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const [r, g, b, a0] = img[y * width + x];
      let c0 = r * gain;
      let c1 = g * gain;
      let c2 = b * gain;
      if (mix > 0) {
        const dx = (x + 0.5 - ox) / half;
        const dy = (y + 0.5 - oy) / half;
        const d = Math.sqrt(dx * dx + dy * dy);
        const m = mix * Math.max(1 - d, 0);
        c0 = c0 * (1 - m) + tint[0] * a0 * m;
        c1 = c1 * (1 - m) + tint[1] * a0 * m;
        c2 = c2 * (1 - m) + tint[2] * a0 * m;
      }
      out.push([f32(Math.max(c0, 0)), f32(Math.max(c1, 0)), f32(Math.max(c2, 0)), f32(clamp(a0, 0, 1))]);
    }
  }
  return out;
}

function gradient(w, h) {
  const px = [];
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      px.push([f32(((x * 2) % 8) / 8), f32(((y * 2) % 8) / 8), f32(((x + y) % 4) / 4), f32(Math.min(1, (x + 1) / w))]);
    }
  }
  return px;
}

class Host {
  constructor(bytes) {
    const module = new WebAssembly.Module(bytes);
    this.imports = WebAssembly.Module.imports(module);
    this.instance = new WebAssembly.Instance(module, {});
    this.e = this.instance.exports;
    const view = () => new DataView(this.e.memory.buffer);
    this.memBytes = () => {
      const ptr = this.e.ec_manifest_ptr();
      const len = this.e.ec_manifest_len();
      const u8 = new Uint8Array(this.e.memory.buffer, ptr, len);
      return new TextDecoder().decode(u8);
    };
    this.view = view;
  }

  flatten(values = {}, pointScale = [1, 0, 0]) {
    const out = [];
    for (const p of this.manifest.params) {
      const v = values[p.id] ?? p.default;
      switch (p.type) {
        case "point":
          out.push(v[0] * pointScale[0] + pointScale[1], v[1] * pointScale[0] + pointScale[2]);
          break;
        case "color":
          out.push(...v.map(Number));
          break;
        case "checkbox":
          out.push(v ? 1 : 0);
          break;
        case "popup":
          out.push(Number(v));
          break;
        default:
          out.push(Number(v));
      }
    }
    return out;
  }

  render(pixels, width, height, params, time = 0, scale = 1) {
    const n = pixels.length;
    const paramsBytes = params.length * 8;
    const total = paramsBytes + n * 16;
    const base = this.e.ec_alloc(total);
    if (!base) throw new Error("ec_alloc returned 0");
    const dv = this.view();
    params.forEach((v, i) => dv.setFloat64(base + i * 8, v, true));
    let at = base + paramsBytes;
    for (const px of pixels) {
      for (let c = 0; c < 4; c++) {
        dv.setFloat32(at, px[c], true);
        at += 4;
      }
    }
    const code = this.e.ec_render(base + paramsBytes, width, height, base, params.length, time, scale);
    const out = pixels.map((p) => p.slice());
    if (code === 0) {
      const dv2 = this.view();
      let o = base + paramsBytes;
      for (let i = 0; i < n; i++) {
        const px = [];
        for (let c = 0; c < 4; c++) {
          px.push(dv2.getFloat32(o, true));
          o += 4;
        }
        out[i] = px;
      }
    }
    return [code, out];
  }
}

const bytes = fs.readFileSync(wasmPath);
const declared = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const host = new Host(bytes);
host.manifest = JSON.parse(host.memBytes());

console.log(`wasm:    ${wasmPath} (${bytes.length} bytes)`);
console.log(`runtime: node ${process.version} (V8 WebAssembly)`);

check("module has no imports", host.imports.length === 0, JSON.stringify(host.imports));
check("module exports the v1 entry points",
  ["memory", "ec_api_version", "ec_manifest_ptr", "ec_manifest_len", "ec_alloc", "ec_render"].every((n) => n in host.e),
  Object.keys(host.e).join(","));
check("ec_api_version() == 1", host.e.ec_api_version() === 1);
check("manifest in the module equals plugin.json", JSON.stringify(host.manifest) === JSON.stringify(declared));

const src = gradient(5, 4);
const base = { origin: [2.5, 2.0], radius: 0, gain: 1, mix: 0 };
let [code, out] = host.render(src, 5, 4, host.flatten(base));
check("identity parameters return the frame unchanged", code === 0 && JSON.stringify(out) === JSON.stringify(src), `code ${code}`);

[code, out] = host.render(src, 5, 4, host.flatten({ ...base, radius: 2, gain: 1.5, mix: 40 }));
const ref = reference(src, 5, 4, { ...base, radius: 2, gain: 1.5, mix: 40 });
check("blur + gain + tint match the reference exactly", code === 0 && JSON.stringify(out) === JSON.stringify(ref), "mismatch");
check("blur actually changed pixels", JSON.stringify(out) !== JSON.stringify(src));

[code, out] = host.render(src, 5, 4, host.flatten({ ...base, radius: 1, gain: 1 }), 0, 2);
const refScaled = reference(src, 5, 4, { ...base, radius: 1, gain: 1 }, 0, 2);
check("scale doubles the blur radius", JSON.stringify(out) === JSON.stringify(refScaled));

[code, out] = host.render(src, 5, 4, host.flatten({ ...base, gain: 1 }), 4);
check("time reaches the module (gain doubles at t = 4 s)",
  out.every((p, i) => p[0] === f32(2 * src[i][0])), "time had no effect");

[code] = host.render(src, 5, 4, host.flatten(base).slice(0, 3));
check("too few parameters is refused with code 1", code === 1, `code ${code}`);
[code] = host.render(src, 0, 0, host.flatten(base));
check("zero-sized frame is refused with code 2", code === 2, `code ${code}`);

host.render(gradient(8, 8), 8, 8, host.flatten(base));
const smallBase = host.e.ec_alloc(11 * 8 + 8 * 8 * 16);
check("ec_alloc is 8-byte aligned", smallBase % 8 === 0, String(smallBase));
const codeBig = host.e.ec_render(smallBase + 11 * 8, 64, 64, smallBase, 11, 0, 1);
check("a frame larger than the buffer is refused with code 4", codeBig === 4, `code ${codeBig}`);

const img = gradient(24, 24);
const first = host.render(img, 24, 24, host.flatten({ ...base, radius: 1 }))[1];
let stable = true;
for (let i = 0; i < 200; i++) {
  if (JSON.stringify(host.render(img, 24, 24, host.flatten({ ...base, radius: 1 }))[1]) !== JSON.stringify(first)) stable = false;
}
check("200 renders on one instance are bit-identical", stable);

console.log(`\n${"-".repeat(60)}\n${passed} checks passed, ${failures.length} failed`);
if (failures.length) {
  console.log("\nfailures:");
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
