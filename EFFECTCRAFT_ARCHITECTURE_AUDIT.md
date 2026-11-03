# EffectCraft — architecture audit

> **Scope.** What the *existing* EffectCraft source actually does, read from the code in this
> repository, as the basis for adding independently reconstructed effects. Every claim below
> names the file it comes from. Where something could not be verified by running it, it says so.
>
> **Repository:** `github.com/yon300600/effectcraft-agen` — a fork of
> `github.com/storytold/effectcraft`.
> **Commit audited:** `c4f386a22fce7a5d4eb0ca9eafdd1781f70962e8` (tree
> `35d2f3eedba3ddb8115668d426e66c1d69b1eaec`, identical to upstream at that commit).
> **Size:** 1,451 tracked files, 1,108 Rust files, 481,389 lines of Rust, 33 library crates,
> 3 apps, 5,201 `#[test]` attributes.
> **Date of audit:** 2026-11-04.

---

## 1. Languages, build system, dependencies

| Thing | What it is | Where |
|---|---|---|
| Language | Rust 2024 edition, `rust-version = 1.95`, `unsafe_code` forbidden | `Cargo.toml`, `clippy.toml` |
| Build system | Cargo workspace, `resolver = "3"`, members `crates/*`, `apps/*`, `xtask` | `Cargo.toml` |
| Task runner | `cargo xtask` (`layers`, `wasm`, `assets`, `ci`, `web`, `corpus`, `bench`) | `xtask/src/main.rs` |
| Dependencies | crates.io plus **pinned git** dependencies: `craft-*` (craft-libs) and FilmCraft codecs | `Cargo.toml` lines 14–19 |
| UI framework | `egui`/`eframe` (frontend only, L5) | `crates/ui-egui` |
| Raster | `tiny-skia`-compatible own compositor on `effectcraft-raster` | `crates/raster` |
| Scripting | `boa` JavaScript engine (expressions L3, scripting L4) | `crates/expr`, `crates/script` |
| WASM runtime | `wasmi` (pure-Rust interpreter), behind the `wasm` feature | `crates/plugin`, `Cargo.toml` |
| GPU | `wgpu` compute/rendering | `crates/gpu` |
| Web build | `wasm32-unknown-unknown` + `wasm-bindgen` 0.2.129 (the **application** compiled to wasm) | `docs/web.md`, `apps/effectcraft-web` |

Two different meanings of "WebAssembly" exist in this project and must not be confused:

1. **The whole application compiled to wasm32** (`apps/effectcraft-web`, `cargo xtask wasm`) —
   the browser build.
2. **Effect plug-ins as WebAssembly modules** (`crates/plugin`, plug-in API v1) — a sandboxed
   `.wasm` file the *desktop/CLI* host loads with wasmi. **This is the integration point for
   reconstructed effects**, and it is what this audit and the kit focus on.

## 2. Application architecture and entry points

```
apps/effectcraft/src/main.rs        desktop app (eframe/winit window, native menu, launch guard)
apps/effectcraft-cli/src/main.rs    headless CLI: render, exec, get/set, script, bench, MCP
apps/effectcraft-web/src/lib.rs     browser app (wasm32), Web Worker engine instances
```

All three drive the same engine (`crates/engine`, `crates/host`) through the same **command
registry**. `crates/host/src/lib.rs` wires a complete `Session` (media pool, expression host,
script host, plug-in loader, exporter). The frontend never owns project state.

Layering (enforced by `cargo xtask layers`, `docs/architecture.md`):

| Layer | Crates |
|---|---|
| L0 | `time`, `geom`, `color`, `vp9enc`, `opusenc`, `hevcenc`, `av1enc` |
| L1 | `raster`, `keyframe`, `segment`, `psd`, `path` |
| L2 | `project`, `text`, `effects`, `svg`, `pdf`, `model`, `track` |
| L3 | `render`, `media`, `expr`, `export`, `gpu`, `sam2`, `interchange`, `lottie`, `plugin` |
| L4 | `engine`, `script`, `host` |
| L5 | `ui-egui`, `automation` (MCP) |
| L6 | the three apps |

Key rule for new code: **`effectcraft-plugin` (L3) may depend on `effectcraft-effects` (L2);
nothing below L5 may depend on egui/eframe/winit/rfd/cpal/muda.**

## 3. Image processing

### 3.1 Representation in memory

```rust
// crates/raster/src/lib.rs:24, :54
pub type Px = [f32; 4];
pub struct Image { pub width: u32, pub height: u32, pub data: Vec<Px> }
```

* **Format:** premultiplied **RGBA**, four `f32` channels, 0–1, with values above 1 allowed in
  32 bpc projects (`docs/architecture.md` §3; `crates/effects/src/plugin.rs` module docs).
* **Order:** **RGBA** (not BGRA), row-major.
* **Stride:** there is **no stride field**. `Image.data` is tightly packed:
  index = `y * width + x` (`Image::idx`, `crates/raster/src/lib.rs:71`). Row stride is always
  `width * 16` bytes. Any padding a plug-in sees comes from the *content bounds* of the layer
  buffer, not from a stride.
* **Colour space:** footage is decoded to sRGB/Rec.709-encoded premultiplied f32
  (`crates/media/src/lib.rs` module docs); the compositor's colour pipeline converts to linear
  internally when the project asks for it (`crates/render/src/color.rs`, `Pipe`).

The effects layer wraps an image with its placement:

```rust
// crates/effects/src/lib.rs:263
pub struct Buf { pub img: Image, pub offset: [f64; 2], pub scale: f64 }
```

`offset`/`scale` map **layer pixels → buffer pixels** (`Buf::to_px`). A blur radius expressed in
layer pixels must be multiplied by `scale`; a point parameter arrives already mapped to buffer
pixels (for plug-ins, `flatten` does that mapping — `crates/effects/src/plugin.rs`).

### 3.2 How processing happens

* **CPU reference path** — `crates/render` (L3). `Renderer::comp_frame(comp_id, t) -> Image`
  (`crates/render/src/pipeline.rs:391`) renders a composition bottom-to-top over visible layers:
  **source → masks → effects → transform (2D affine or 3D projective with motion blur
  sub-samples) → track matte → blend**. Adjustment layers run their effect stack on everything
  below them.
* **GPU path** — `crates/gpu` implements the same effects as wgpu compute shaders; the renderer
  switches per effect (`Accelerator`, `FxStep`, `FxTarget` — `crates/render/src/accel.rs`) and
  runs a contiguous run of GPU-capable effects in one submission. Results are checked against
  the CPU renderer in `crates/gpu/src/tests.rs`.
* **Parallelism** — `rayon`. Layers and effect stacks are parallelised; exports render frames in
  parallel batches (`crates/export/src/lib.rs` module docs).

### 3.3 Large images, caching, and how results reach the UI

* **Layer cache** — `crates/render/src/cache.rs` (`LayerCache`, `Arc<Buf>` entries, byte-budgeted,
  optional disk store). Static and transform-only layers render once and are reused
  (`Renderer::layer_is_static`).
* **Footage cache** — `crates/media/src/pool.rs`: LRU of decoded frames, `DEFAULT_BUDGET = 1 GiB`,
  evicted by bytes; the browser build keeps 512 MB layer cache / 256 MB footage cache
  (`docs/web.md`).
* **UI delivery** — panels hold `Arc<Comp>` snapshots and the viewer draws the `Image` the engine
  produced (`crates/engine/src/session/render.rs`, `crates/ui-egui/src/panels/viewer*`). Preview
  frames may be at reduced resolution, which is why effects receive `scale`.

**Where a new image-processing effect belongs:** as an `EffectSpec` in the effect registry
(`crates/effects`), for built-ins; or as a **plug-in** (`crates/plugin`, wasm) which is
registered into the same registry. See §5.

## 4. Video processing

* **Probe/decode** — `crates/media` (`probe`, `probe_bytes`) describes a file as
  `effectcraft_project::Footage` (size, rate, duration, streams, codec, alpha). Decoding is
  on demand through `MediaPool`, which owns one decoder per source and keeps it positioned for
  sequential playback: **a movie is never loaded into memory as a whole.**
* **Hand-off to the renderer** — the `FootageSource` trait
  (`crates/render/src/footage.rs:24`): `frame(item, footage, t)` and
  `frame_at_size(..., width, height)` return `Arc<Image>` for a source time `t: Tick`; `audio`,
  `aux` (depth/IDs/Cryptomatte), `model`, `set_cache_budget`, `purge` complete it.
* **Timing** — all time is an integer `Tick` of 254,016,000,000 per second (`crates/time`), the
  LCM of broadcast frame rates and audio rates; `layer_time = (comp_time - start_time) / stretch`
  with Time Remap override. Frame rate conversions are exact.
* **Effects on video frames** — identical to stills: each decoded frame becomes an `Image`, gets
  a `Buf`, and runs the layer's effect stack. There is no separate video effect path, which is
  why one plug-in implementation covers stills and video.
* **Output** — `crates/export` renders the queue: frames in parallel batches through the same
  `Renderer`, then the output module (crop/resize/fields/colour depth) and an encoder
  (H.264/HEVC/AV1 MP4, ProRes, WebM VP9+Opus, PNG/JPEG/TIFF/EXR/TGA sequences, GIF, WAV/AIFF),
  with cancel-able progress callbacks.
* **Real time?** Playback renders at the viewer's resolution with caching and an adaptive
  quality controller (`crates/render/src/auto.rs`); it is "as fast as the frame budget allows",
  not a hard real-time guarantee.

## 5. Effects system

### 5.1 Registry

```rust
// crates/effects/src/lib.rs:586
pub struct EffectSpec {
    pub id: &'static str,        // "ec.blur.gaussian"
    pub name: &'static str,
    pub category: &'static str,
    pub params: Vec<ParamSpec>,
    pub render: RenderFn,        // fn(&EffectCtx, Buf) -> Buf
    pub gpu: bool,               // implemented on the GPU path too
    pub float: bool,             // 32 bpc capable
}
```

* `registry()` (`crates/effects/src/lib.rs:628`) concatenates the `specs()` of ~49 modules,
  sorts by category then name, and marks GPU effects from `GPU_EFFECTS`. **308 effects,
  2,987 parameters** (generated `docs/effects.md`).
* `find(id)`, `lookup(name_or_id)` (id, display name, aliases, old names), `categories()`,
  `all()` (built-ins **plus registered plug-ins**), `name_matches()` for search.
* `instantiate(spec, ids, instance_name, layer_size)` (`:763`) builds the instance's **property
  group**: `GroupKind::Effect { effect }` with one `Property` per `ParamSpec`, nested groups for
  `group/param` ids, a hidden `…Source` companion for layer parameters, `hold_only` for
  checkbox/popup/layer parameters, `spatial` for points.

### 5.2 Input, output, chaining

* An effect is a pure function `fn(&EffectCtx, Buf) -> Buf` over the layer's buffer, **in place
  and possibly padded/scaled**.
* `EffectCtx` (`crates/effects/src/lib.rs:550`) carries `params: &Params`, `time` (layer
  seconds), `layer_size`, a stable per-instance `seed`, `adjustment`, and `EffectEnv` (masks,
  other layers through `EffectHost`, comp time, frame rate, working space, shutter).
* The stack is the layer's `effects` property group; `Renderer::run_effect_stack`
  (`crates/render/src/pipeline.rs:554`) walks the groups **in order**, skips disabled groups,
  skips audio-only effects for the video path, sends runs of GPU-capable effects to the
  accelerator, and falls back to the CPU render function otherwise. Adjustment layers run their
  stack against the composited image below.
* Chaining is therefore positional order in that group list, exactly as in Effect Controls.

### 5.3 Enable, disable, reorder, remove, errors

Commands (`crates/engine/src/cmd/effect.rs` registry): `effect.apply`, `effect.applyLast`,
`effect.remove`, `effect.removeAll`, `effect.reorder`, `effect.toggle`, `effect.duplicate`,
`effect.copy`/`effect.paste`, `effect.reset`, `effect.list`, `effect.plugins.load`,
`effect.plugins.list`. Each is an undoable engine edit.

Error handling: a plug-in that returns an error code, traps, or exhausts fuel **leaves the frame
unchanged** and logs a warning once (`run_slot`, `crates/effects/src/plugin.rs`); a panicking
built-in is caught by the app's panic boundary (`AGENTS.md`, "Never crash").

### 5.4 Two ways to add an effect (already implemented — do not duplicate)

1. **Built-in**: a `spec(...)` in `crates/effects/src/*.rs` added to that module's `specs()`.
2. **Plug-in API v1** (`docs/plugins.md`, `crates/effects/src/plugin.rs`, `crates/plugin`):
   * Rust: implement `EffectPlugin` and call `register_plugin`.
   * **WebAssembly**: a module with no imports exporting `ec_api_version`, `ec_manifest_ptr`,
     `ec_manifest_len`, `ec_alloc`, `ec_render`, loaded by
     `effectcraft_plugin::load_wasm` → `register_plugin` → an ordinary `EffectSpec`.
   * Loading paths: **Effect ▸ Load Effect Plug-in…**, `effect.plugins.load {path|folder}`,
     `effect.plugins.list`, or every `.wasm` in `<settings>/Plug-ins` at start-up
     (`apps/effectcraft/src/main.rs`).
   * Limits: 64 plug-ins per process, 256 parameters each, 1 MiB manifest, 1 GiB memory,
     fuel budget per frame; **desktop and CLI only** (`wasm` feature, no web build);
     plug-ins are CPU-only (`gpu: false`).

## 6. Parameters

* `ParamUi` (`crates/project/src/props.rs:13`): `Number`, `Slider{min,max,slider_min,slider_max,
  decimals}`, `Percent`, `Angle`, `Pixels`, `Point`, `Point3`, `Color`, `Checkbox`,
  `Popup{options}`, `Layer`, `Mask`, `Path`, `Text`, `File{filters}`, `Hidden` and related.
* `Value` (`crates/keyframe/src/value.rs:285`): `Scalar`, `Vec2`, `Vec3`, `Color`, `Bool`,
  `Enum(u32)`, `Path`, `Text`, `Layer`, `Gradient`, `Str` — every animated value in the project.
* A `Property` (`crates/project/src/props.rs:58`) holds `uid`, `match_id` (e.g. `blurriness`),
  `name`, static `value`, `keys: Vec<Keyframe>`, optional expression, `ui`, `spatial`,
  `hold_only`, dimension flags.
* Defaults and ranges come from the `ParamSpec` (or the plug-in manifest); the UI builds the
  widget from `ParamUi` and enforces the range (`slider_min..slider_max` for the slider, the
  wider `min..max` for typed values); the engine command `prop.set` clamps and validates.
* **Presets**: animation presets are JSON (`crates/engine/presets/*.json`, `.ecpreset`), applied
  by `anim.applyPreset`/`anim.applyBuiltinPreset`, and they add effect instances with static
  values and/or keyframes (`crates/engine/src/cmd/anim_presets.rs`). After Effects `.ffx` is
  **not** read (clean-room rule, `AGENTS.md` §2).

## 7. Animation and keyframes

`crates/keyframe` (L1) implements After Effects keyframe semantics:

| Feature | Where / how |
|---|---|
| Time | integer `Tick`, 254,016,000,000/s (`crates/time`) |
| Interpolation | `Interp::{Linear, Bezier, Hold}` per side (`crates/keyframe/src/lib.rs:26`) |
| Temporal ease | `Ease { speed, influence }` per dimension, per side; `EASE` const; `easy_ease()` |
| Spatial motion paths | `spatial_in`/`spatial_out` tangents, `spatial_auto`, arc-length evaluation, `spatial_tangents`, `spatial_handles` |
| Auto / continuous Bezier | `auto_bezier`, `continuous` flags, tangents derived from neighbours |
| Roving | `retime_roving()`, skipped by eases |
| Hold | per-side `Interp::Hold`, `hold_only` properties |
| Evaluation | `evaluate(keys, t, spatial)`, `segment_value`, `velocity`, `speed` |
| Time reversal | `time_reverse()` |
| Expression overrides | `Property.expr`, evaluated by `crates/expr` (boa) before keyframe evaluation |

Editing commands: `anim.addKeyframe`, `keys.copy/paste/nudge/…`, `key.*` dialogs, graph editor
(`crates/ui-egui/src/panels/graph.rs`), Keyframe Velocity dialog (`panels/key_dialogs.rs`),
Ease Presets extension. Playback is the viewer's clock (`crates/ui-egui/src/clock.rs`) feeding
`Tick` times to the renderer.

**Consequence for reconstruction:** a reconstructed effect's parameters are plain properties, so
keyframes, eases, expressions, the graph editor, presets and save/reopen work with **no new
machinery**. An effect must therefore be implemented as frame-independent processing driven by
`params` + `time`, never as an animation itself.

## 8. Commands and automation

Every action is a `CommandSpec { id, label, menu, shortcut, params, enabled, run }`
(`crates/engine/src/cmd.rs`, 379 `cmd!` + 57 `query!` registrations). The desktop UI, the CLI
(`effectcraft-cli exec`), the JSON control channel and the MCP server all dispatch by id, so an
effect added to the registry is immediately drivable by agents.

## 9. What this means for reconstructed effects (summary)

1. The integration point **already exists**: plug-in API v1 (`crates/plugin` + `crates/effects/
   src/plugin.rs`), loaded at runtime, no rebuild of the app required.
2. Pixels in: premultiplied RGBA f32, tight rows, possibly scaled/padded; pixels out: same
   buffer, in place.
3. Parameters in: flattened f64s, already evaluated for the current frame (keyframes,
   expressions, eases), so animation is the host's job.
4. Errors: never panic, return a non-zero code or let the sandbox stop you; the frame is
   restored.
5. No new preset format, registry or loader is needed: use `Effect ▸ Load Effect Plug-in…`,
   the `Plug-ins` folder, or `.ecpreset` presets for parameter sets.

## 10. Known limits of this audit

* The Rust workspace **was not compiled** in the audit environment (no Rust toolchain; egress to
  `static.rust-lang.org` and `static.crates.io` blocked). See
  `EFFECTCRAFT_WASM_TOOLCHAIN.md`.
* EffectCraft's own wasmi host could therefore not be executed here; ABI conformance was proven
  with two other real runtimes and a provided real-host crate (`tools/wasm-effect-kit/`).
* Performance numbers in `docs/architecture.md` are the project's own measurements, not
  re-measured here.
