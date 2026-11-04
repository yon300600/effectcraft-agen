// Second-engine check: the same module, the same frame, in V8 (Node) instead of wasmtime.
//
//   node tests/check_v8.mjs build/je_cream_cc.wasm <image.json> <params.json>
//
// Prints one line: "<sha256 of the output bytes> <first 6 output values>". The image and the
// parameter vector come from tests/check_pixels.py, which compares this hash with wasmtime's.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const [wasmPath, imagePath, paramsPath] = process.argv.slice(2);
const image = JSON.parse(readFileSync(imagePath, "utf8")); // {w, h, pixels: [], params: []}
const { w, h } = image;
const pixels = new Float32Array(image.pixels);
const params = image.params;

const { instance } = await WebAssembly.instantiate(readFileSync(wasmPath), {});
const ex = instance.exports;

const api = ex.ec_api_version();
if (api !== 1) throw new Error(`api ${api}`);
const manLen = ex.ec_manifest_len();
const man = new TextDecoder().decode(
  new Uint8Array(ex.memory.buffer, ex.ec_manifest_ptr(), manLen));
const manifest = JSON.parse(man);

const total = params.length * 8 + w * h * 16;
const base = ex.ec_alloc(total);
if (!base) throw new Error("ec_alloc returned 0");

const f64 = new Float64Array(ex.memory.buffer, base, params.length);
f64.set(params);
const pixelBytes = new Uint8Array(ex.memory.buffer, base + params.length * 8, w * h * 16);
new Uint8Array(pixels.buffer).forEach((v, i) => (pixelBytes[i] = v));

const rc = ex.ec_render(base + params.length * 8, w, h, base, params.length, 0.0, 1.0);
if (rc !== 0) throw new Error(`ec_render returned ${rc}`);

const out = new Uint8Array(ex.memory.buffer, base + params.length * 8, w * h * 16).slice();
const hash = createHash("sha256").update(Buffer.from(out)).digest("hex");
const first = new Float32Array(out.buffer, 0, 6);
console.log(`${hash} ${Array.from(first).map((v) => v.toPrecision(9)).join(",")} ${manifest.id}`);
