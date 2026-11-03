# EffectCraft — WebAssembly effect interface (plug-in API v1)

The contract a reconstructed effect must implement to run inside EffectCraft. It is the
project's existing, shipped interface (`docs/plugins.md`, `crates/plugin/src/lib.rs`,
`crates/plugin/src/wasm.rs`, `crates/effects/src/plugin.rs`); this document restates it for
implementers, adds the byte-level details the source enforces, and records how it is tested.

> Status of verification: the ABI below was executed in two real runtimes (wasmtime, and V8 via
> Node) in this environment, and the modules conform. EffectCraft's own wasmi host was **not**
> executed here (no Rust toolchain available); the real-host check is provided in
> `tools/wasm-effect-kit/host/` to run where cargo works.

---

## 1. Module requirements

| Requirement | Detail |
|---|---|
| Binary | A `.wasm` module (or `.wat` text; the host enables wasmi's `wat` feature) |
| Imports | **None at all.** A single import is refused: "plug-ins can't import anything" |
| Exports | `memory`, `ec_api_version`, `ec_manifest_ptr`, `ec_manifest_len`, `ec_alloc`, `ec_render` |
| API version | `ec_api_version()` must return `1` |
| Determinism | Same inputs → same output, on every machine and thread. No clocks, no randomness, no environment |
| Thread safety | The host may run several instances of the module at once (one per thread); treat state as per-instance |
| Failure | Never trap on valid input; return a non-zero code for invalid input |

Signature table (`crates/plugin/src/wasm.rs`):

| Export | Wasm signature | Meaning |
|---|---|---|
| `memory` | memory | linear memory shared with the host |
| `ec_api_version` | `() -> i32` | must be `1` |
| `ec_manifest_ptr` | `() -> i32` | address of the UTF-8 JSON manifest |
| `ec_manifest_len` | `() -> i32` | its length in bytes, `0..=1 MiB` |
| `ec_alloc` | `(bytes: i32) -> i32` | buffer of **at least** `bytes` bytes, **8-byte aligned**; may reuse the previous buffer |
| `ec_render` | `(pixels: i32, width: i32, height: i32, params: i32, nparams: i32, time: f64, scale: f64) -> i32` | process pixels **in place**; `0` = success |

## 2. The frame buffer

For every render the host does exactly this:

1. `total = nparams * 8 + width * height * 16`
2. `base = ec_alloc(total)` — one allocation for **parameters then pixels**
3. writes `nparams` little-endian `f64` parameter values at `base`
4. writes `width * height` pixels at `base + nparams * 8`, each **4 × little-endian `f32`**
5. calls `ec_render(base + nparams*8, width, height, base, nparams, time, scale)`
6. if the call returns `0`, reads the pixels back from `base + nparams*8`; otherwise the frame is
   left as it was and an error is reported

```
base ─────────────► params[0]   f64  (8 bytes, LE)
                    params[1]   f64
                    …
                    params[n-1] f64
pixels = base + 8n ► R f32  G f32  B f32  A f32   ← pixel (0,0)
                    R f32  G f32  B f32  A f32   ← pixel (1,0)
                    …
                    R f32  G f32  B f32  A f32   ← pixel (w-1, h-1)
```

* **Pixel format:** premultiplied **RGBA**, `f32`, 0–1; values above 1 are legitimate in 32 bpc
  projects (do not clamp unless the effect's own maths requires it).
* **Row order / stride:** row-major, **no padding, no stride field**. Row stride is exactly
  `width * 16` bytes. Index `(y * width + x) * 4` floats.
* **Alpha:** premultiplied. To work in straight colour, divide by alpha (`a > 0`), then
  re-multiply. Alpha `0` means "no coverage", not "black".
* **Size:** `width * height` pixels, exactly the buffer the host allocated; it may be the layer's
  **content bounds** (smaller than the layer) and may be **scaled** for preview.
* **`scale`:** buffer pixels per layer pixel (e.g. `0.25` at quarter resolution). Pixel distances
  expressed in layer pixels — blur radii, offsets, kernel sizes — must be multiplied by it.
* **`time`:** **layer time in seconds** (`f64`), already resolved from comp time, layer
  in-point and time stretch/remap.
* **Point parameters** arrive already converted to buffer pixels (the host applies
  `buf.to_px(…)`), so do not multiply them by `scale` again.

## 3. The manifest

A UTF-8 JSON document in the module's memory (`docs/plugins.md`, `PluginManifest` in
`crates/effects/src/plugin.rs`):

```json
{
  "api": 1,
  "id": "org.example.posterize",
  "name": "Posterize",
  "category": "Stylize",
  "version": "1.0.0",
  "author": "…",
  "description": "…",
  "params": [
    {"id": "levels", "name": "Levels", "type": "slider", "default": 4, "min": 2, "max": 64,
     "sliderMax": 16, "decimals": 0},
    {"id": "tint",   "name": "Tint",   "type": "color",  "default": [1.0, 0.55, 0.2, 1.0]},
    {"id": "mode",   "name": "Mode",   "type": "popup",  "options": ["A", "B"], "default": 0},
    {"id": "centre", "name": "Centre", "type": "point",  "default": [0.5, 0.5]},
    {"id": "on",     "name": "On",     "type": "checkbox", "default": true},
    {"id": "angle",  "name": "Angle",  "type": "angle",  "default": 0}
  ]
}
```

Rules the host enforces (`PluginManifest::validate`):

* `api` must be `1`; `id` is reverse-domain (`A-Za-z0-9`, `.`, `_`, `-`), **unique**, and `ec.`
  is reserved for built-ins; `name` and `category` are required (a new category appears after the
  built-ins in Effects & Presets).
* At most **256** parameters; ids are `A-Za-z0-9_`, unique.
* `slider`: finite `min ≤ default ≤ max`, and `sliderMin ≤ sliderMax`.
* `popup`: non-empty `options`, `default` index in range.
* Manifest at most **1 MiB**.
* Unknown parameter types are refused.

### Parameter flattening (order = declaration order)

| Type | Slots | Value |
|---|---|---|
| `slider` | 1 | the number |
| `angle` | 1 | degrees |
| `checkbox` | 1 | `0.0` / `1.0` |
| `popup` | 1 | 0-based option index as `f64` |
| `point` | 2 | x, y **in buffer pixels** |
| `color` | 4 | R, G, B, A in 0–1 |

Total `nparams` is the sum. The host sends the **evaluated** value for the current frame, so
keyframed, eased or expression-driven parameters arrive already animated: the module must not
interpolate over time itself.

## 4. Lifecycle

```
load            instantiate (no imports) → ec_api_version → manifest → validate → register as EffectSpec
render (n)      take instance from pool (or instantiate) → set fuel → ec_alloc →
                write params+pixels → ec_render → read pixels → return instance to pool (on success)
several threads each thread takes its own instance; the pool never shares one instance at a time
unload          nothing to do: dropping the WasmPlugin drops its instances and store (the app has no
                explicit unload; a plug-in lives for the process)
```

* **Parameters change without re-instantiation.** There is no "set parameter" call: every frame
  writes the current values into the buffer and calls `ec_render`. Editing a slider, adding a
  keyframe or scrubbing the timeline costs one normal render.
* **Memory grows, never shrinks.** `ec_alloc` may grow linear memory and reuse one buffer
  (the reference example and the kit fixture both reuse a single buffer). The host's store limit
  is **1 GiB**; allocation beyond it fails.
* **One instance per render at a time**, but several instances may exist (parallel rendering).
  A module must not assume a single global state across threads.
* **Cancellation / runaway protection:** the store is fuel-metered. The budget is
  `50,000,000 + 20,000 × pixels` instructions per frame; running out stops the render with an
  error instead of hanging the application. The kit proves this with a deliberately infinite
  module (`fixture/ec_spin.c`).
* **Failure handling:** a non-zero return code or a trap logs a warning and **restores the
  original pixels**; the frame still renders with the effect skipped.

## 5. Error codes

EffectCraft treats any non-zero return as "this effect failed"; the number itself is only used in
the log message ("ec_render returned error N"). The kit fixture defines and documents a set that
a reconstructed effect should reuse for consistency:

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | too few parameters (`nparams` < the manifest's flattened length) |
| `2` | bad frame (`width` or `height` ≤ 0) |
| `3` | null `pixels` or `params` pointer |
| `4` | the frame does not fit the buffer `ec_alloc` handed out |
| `5` | the module could not grow its memory |

Never abort the module (`unreachable`) on invalid input: return a code and leave the pixels as
they were.

## 6. Host integration (already implemented — do not duplicate)

| Piece | Path |
|---|---|
| Runtime (wasmi), pooling, fuel, limits | `crates/plugin/src/wasm.rs` |
| `load_wasm(bytes, source)` → registered `EffectSpec` | `crates/plugin/src/lib.rs` |
| Manifest types, validation, parameter flattening, `EffectSpec` glue | `crates/effects/src/plugin.rs` |
| Engine hook installed by the host | `crates/host/src/lib.rs` (`plugin_loader`) |
| Commands `effect.plugins.load` / `.list` | `crates/engine/src/cmd/effect.rs` |
| Desktop menu "Effect ▸ Load Effect Plug-in…" | `crates/engine/src/menus.rs` |
| Start-up loading of `<settings>/Plug-ins/*.wasm` | `apps/effectcraft/src/main.rs` |
| Example plug-in (Rust) | `examples/plugins/posterize-bands` |
| Example plug-ins in `.wat` used by tests | `crates/plugin/src/tests.rs` |
| End-to-end host tests (register + render) | `crates/host/tests/it/plugins.rs` |

Because registration produces an ordinary `EffectSpec`, a plug-in effect automatically gets:
Effects & Presets listing and search, Effect menu entry, `effect.apply` by id or name,
`Effect Controls` panel with real editable parameters, keyframes/eases/expressions on those
parameters, undo, save/reopen in `.ecproj`, render queue and export, and agent/MCP access.

**Not available:** the web build (`apps/effectcraft-web`) does not ship the wasmi runtime, and
plug-ins have no GPU path (`gpu: false`). Reconstructed effects are desktop/CLI features.

## 7. Conformance tests

`tools/wasm-effect-kit/` contains a complete, executed conformance suite:

| File | Runtime | Checks |
|---|---|---|
| `fixture/check_host.py` | wasmtime (Python) | 48 checks: binary validity, no imports, exports, API version, manifest equality + schema, defaults, every parameter type, blur/gain/tint maths against an independent reference, `scale`, `time`, alpha, error codes, buffer-size refusal, 200 repeated renders, memory plateau, 1920×1080 frame, fuel stop, reload |
| `fixture/check_host.mjs` | Node / V8 | 14 checks: the same contract on a second engine |
| `host/` | EffectCraft's real wasmi host | registration through `effectcraft_plugin::load_wasm`, identity/gain/blur through `EffectPlugin::render`, error path leaves pixels unchanged (`cargo run --release`) — **executed on a GitHub runner**, see `EFFECTCRAFT_WASM_VERIFICATION.md` |
| `app_check.sh` | the shipped `effectcraft-cli` (real engine, loader and renderer) | `effect.plugins.load`, `effect.plugins.list`, `effect.apply`, `prop.set`, `props`, `renderQueue.render` on the fixture |

Two results worth keeping in mind when implementing a new effect:

* **Bit-exactness is reachable.** The fixture uses `f64` accumulation in a fixed order with
  `-ffp-contract=off`; an independent Python and JavaScript re-implementation of the same maths
  matches it exactly, not approximately. Do the same: define the maths precisely enough that a
  second implementation can be compared bit-for-bit.
* **Engine independence holds.** The same binary produced identical results in wasmtime and V8,
  which is the property EffectCraft needs in order to promise "same pixels on every machine".

## 8. Before a module loads in the application (checklist)

A module that passes §7 is not yet "loaded in EffectCraft". The application side has its own
requirements, all of them already implemented in the repository:

1. **A native build with the `wasm` feature** (`crates/plugin/Cargo.toml`, enabled by
   `crates/host`). Without it the loader says plug-ins are unavailable in this build.
2. **A session with a plug-in loader** — `crates/host/src/lib.rs::session()` sets
   `Session::plugin_loader` when `effectcraft_plugin::wasm_available()`.
3. **A load call in that session**: Effect ▸ Load Effect Plug-in…, `effect.plugins.load
   {path|folder}`, or (desktop only) a file in `<settings>/Plug-ins/` at start-up. The CLI does
   not scan that folder.
4. **A manifest the validator accepts** (§3) and an id not already taken.
5. **The module loaded again in every process** that opens a project using the effect: `.ecproj`
   stores the effect id, not the module.
6. **Native platforms only** — the browser build has no wasmi runtime, and plug-ins are CPU-only.

`EFFECTCRAFT_WASM_VERIFICATION.md` tracks which of these have actually been executed.
