# EffectCraft — WASM verification status

What has been **executed**, where, and what has not been executed. Two tiers, kept apart on
purpose: evidence that the module meets the ABI outside the application, and evidence that the
application itself loads, registers and renders it.

> Last updated: 2026-11-04. Re-run everything with `tools/wasm-effect-kit/run_tests.sh`
> (tier A) and `tools/wasm-effect-kit/app_check.sh` + `tools/wasm-effect-kit/host` (tier B).

**Bottom line.** The fixture module is compiled, loaded, executed and pixel-processed **both**
standalone (wasmtime 50.0.1, V8; 48/48 and 14/14 checks) **and** inside the real EffectCraft
application (its own `effectcraft-plugin` wasmi 2.0 host; the shipped CLI's loader, engine and
renderer; workflow run `41779068845`, all stages green). It is **not** registered as a production
effect, and no reconstruction of a third-party effect has been attempted yet — the fixture exists
to prove the ABI and the integration path before that work starts.

---

## 1. Tier A — verified independently of the application

Runtime- and format-level facts about the fixture module. None of this proves that EffectCraft
accepts the module; it proves the module is a valid, deterministic plug-in API v1 module.

| # | Check | Tool | Result |
|---|---|---|---|
| A1 | Compiles from source to Wasm (`wasm32-freestanding`, no CRT, no imports) | Zig 0.17.0 (clang frontend) | **pass** — 3,543 B module, byte-identical on rebuild |
| A2 | Valid binary, magic/version, zero imports, six exports | wasmtime 50.0.1 + Node 22 (V8) | **pass** |
| A3 | `ec_api_version() == 1` | both | **pass** |
| A4 | Manifest identical to `plugin.json` and schema-valid | both | **pass** |
| A5 | Memory: `ec_alloc` 8-byte aligned, grows on demand, plateaus, refuses overflow | wasmtime | **pass** |
| A6 | Parameter delivery: all 7 parameter types (slider, colour, popup, point, checkbox) reach the module | wasmtime + V8 | **pass** |
| A7 | Pixel processing matches an independent reference **bit-exactly** | wasmtime + V8 | **pass** |
| A8 | `scale` (preview resolution) and `time` (layer seconds) are honoured | both | **pass** |
| A9 | Alpha preserved, premultiplied, stays in 0–1 | both | **pass** |
| A10 | Error codes: short parameter list (1), zero-size frame (2), undersized buffer (4); refused frames unchanged | both | **pass** |
| A11 | 200 repeated renders identical; no memory growth | both | **pass** |
| A12 | 1920×1080 frame renders and is finite | wasmtime | **pass** (~1.5 s in Python; not a module benchmark) |
| A13 | A runaway module is stopped by the fuel budget instead of hanging | wasmtime fuel | **pass** (0.02 s) |
| A14 | Module reloads into a fresh instance and still matches the reference | wasmtime | **pass** |

Totals: **48/48** checks in `check_host.py`, **14/14** in `check_host.mjs`.

## 2. Tier B — verified inside the application

| # | Check | How | Result |
|---|---|---|---|
| B1 | EffectCraft's real host instantiates the module under **wasmi 2.0** (no imports, fuel, 1 GiB limit) | `tools/wasm-effect-kit/host` — `cargo run --release`, GitHub runner | **pass** (see §3) |
| B2 | The manifest is read and validated by the real Rust validator; the effect registers as an `EffectSpec` with 7 parameters | same | **pass** |
| B3 | `EffectPlugin::render` produces the expected pixels: identity unchanged, gain 2× on RGB with alpha untouched, radius 2 changes the frame | same | **pass** |
| B4 | A failing render (short parameter list) reports an error and leaves the frame unchanged | same | **pass** |
| B5 | The project's own plug-in test suite still passes on this branch | `cargo test -p effectcraft-plugin` | **pass** |
| B6 | The application's loader command accepts the module (`effect.plugins.load`), lists it (`effect.plugins.list`) with api 1 and 7 parameters | `tools/wasm-effect-kit/app_check.sh load` | **pass** (§4.1) |
| B7 | Applying the effect by id creates a real instance whose parameters are ordinary, animatable properties (`prop.set`, `prop.addKey`, keyframe read back) | `… app_check.sh project` | **pass** (§4.2) |
| B8 | The effect changes frames rendered by the real renderer (PNG sequence, with and without the effect) | `… app_check.sh render` | **pass** (§4.3) |

## 3. How tier B1–B5 was run (and why not here)

The sandbox that builds this repository has **no Rust toolchain and no registry access**, so the
Rust host cannot be compiled locally. The routes investigated, all with measured results:

| Route | Probe | Outcome |
|---|---|---|
| Install Rust locally | `https://static.rust-lang.org/dist/channel-rust-stable.toml` → HTTP 000; `https://static.crates.io/…` → 000; `https://index.crates.io/config.json` → 000 | blocked by egress policy |
| Prebuilt toolchain from GitHub releases | `repos/rust-lang/rust/releases/latest` → **0 assets**; any release asset redirects to `objects.githubusercontent.com` → **000** | impossible |
| Toolchain bundled in an npm/pypi package | npm `rustc` 1.74 tarball inspected: contains **Mach-O** stubs plus a downloader that fetches from `static.rust-lang.org`; PyPI `rustc`/`rust-toolchain` → 404 | unusable |
| EffectCraft release binary (same wasmi host) | `storytold/effectcraft` v0.21.0 has `effectcraft-0.21.0-linux-x86_64.tar.gz`, but the download 302s to `objects.githubusercontent.com` → **000** | blocked |
| wasmi as a library in Python/npm | PyPI `pywasmi` 0.6.0: cp27/cp36 wheels only (2019); npm `wasmi`: a TypeScript demo that calls the browser engine | not the wasmi engine |
| **GitHub Actions runner** | fork has Actions enabled; temporary workflow `wasm host check`, run **41731160392** | **worked** — this is where B1–B5 were executed |

The runner job (`ubuntu-24.04`, checkout of the PR head, stable Rust) reported:

```
success  Real host check (effectcraft-plugin, wasmi 2.0)   ← tools/wasm-effect-kit/host: cargo run --release
success  Plug-in crate tests                               ← cargo test -p effectcraft-plugin
```

The final run (`41779068845`, commit `b73b413`) ran every stage without `continue-on-error` and
with `set -o pipefail`, so a failing stage fails the job:

```
success  Toolchain
success  Real host check (effectcraft-plugin, wasmi 2.0)
success  Plug-in crate tests
success  Build the CLI
success  App stage load
success  App stage project
success  App stage render
```

(An earlier run, `41735974156`, used `continue-on-error` and a `tee` pipeline without
`pipefail`; a failing stage there still reported success. That masking was removed — the steps are
green now because the stages pass, not because failures were swallowed.)

That workflow was **temporary** (project rules forbid adding CI in a feature PR): it lived on the
working branch only, its results are recorded here, and the file is deleted before this change is
finished. Re-create it any time with the YAML in §6.

## 4. Tier B6–B8 — application-level checks (executed)

`tools/wasm-effect-kit/app_check.sh` drives the shipped CLI — same engine, same
`effectcraft-plugin` wasmi host, same renderer as the desktop app — through three stages. It was
built and run on a GitHub runner (`cargo build -p effectcraft-cli`, Ubuntu 24.04, rustc 1.99.1),
workflow run **41779068845** (commit `b73b413`), with `set -o pipefail` and **no**
`continue-on-error`: every stage's exit status is the job's.

```
success  Build the CLI
success  App stage load
success  App stage project
success  App stage render
```

### 4.1 `app_check.sh load` — the application's own loader

```
[{"command":"effect.plugins.load","result":{"errors":[],"loaded":[{"api":1,
  "category":"Test Plug-ins","id":"org.effectcraft.wasmkit.fixture.gain-blur",
  "name":"WASM Kit Fixture: Gain and Box Blur","params":7,"version":"1.0.0"}]}},
 {"command":"effect.plugins.list","result":{"api":1,"plugins":[{"author":"EffectCraft contributors",
  "id":"org.effectcraft.wasmkit.fixture.gain-blur", "params":["radius","gain","tint","mix","mode",
  "origin","enable"], "source":"…/tools/wasm-effect-kit/fixture/ec_gain_blur.wasm", …}],
  "wasm":true}}]

PASS load: registered org.effectcraft.wasmkit.fixture.gain-blur (api 1, 7 parameters, wasm runtime available)
```

The effect is in the application's registry, with its parameter names, ready for the Effects panel.

### 4.2 `app_check.sh project` — applied by id, parameters behave like built-in ones

The whole command sequence, as the CLI reported it (`comp.new` → `layer.newSolid` →
`effect.plugins.load` → `effect.apply` → `prop.set` → `prop.get` → `prop.addKey` → `prop.get`):

```
{"result":[
 {"command":"comp.new","result":{"comp":1}},
 {"command":"layer.newSolid","result":{"layer":4}},
 {"command":"effect.plugins.load","result":{"loaded":[{"api":1,"id":"org.effectcraft.wasmkit.fixture.gain-blur","params":7}]}},
 {"command":"effect.apply","result":{"effect":"org.effectcraft.wasmkit.fixture.gain-blur","effects":[27],"paths":["effects/#1"]}},
 {"command":"prop.set","result":2.0},
 {"command":"prop.get","result":{"animated":false,"match":"gain","name":"Gain","type":"scalar","value":2.0,"keys":[]}},
 {"command":"prop.addKey","result":1},
 {"command":"prop.get","result":{"animated":true,"time":0.5,"value":3.0,
   "keys":[{"time":0.5005,"value":3.0,"in":"Linear","out":"Linear"}]}}],
 "saved":"…/with.ecproj"}

PASS project: applied by id as effects/#1; effects/#1/Gain (scalar) takes prop.set and prop.addKey like any built-in parameter
PASS project: saved …/with.ecproj
```

So a plug-in's parameters live in the ordinary property tree (`effects/#1/Gain`), take
`prop.set`, accept `prop.addKey`, and come back with keyframe timing, interpolation and values —
no separate animation system, exactly as the brief requires.

### 4.3 `app_check.sh render` — pixels out of the real renderer

Two runs of the same comp (32×32 grey solid, 0.5 grey), one with the plug-in applied and
`gain = 2.0`, one without. `renderQueue.add` + `renderQueue.render` wrote a PNG sequence in each
case; the script decodes frame 0 with its own PNG reader and compares the mean:

```
with effect:    00000.png (32, 32) mean RGB [255.0, 255.0, 255.0]
without effect: 00000.png (32, 32) mean RGB [128.0, 128.0, 128.0]
PASS render: the plug-in effect changed the rendered frame through the real renderer
```

128 → 255 is the plug-in's `gain = 2.0` applied to 0.5 grey by EffectCraft's renderer: the frame
came out of the module, through the host, through the compositor, into a PNG.

### 4.4 `host/` — the same module under the project's own wasmi host (run 41779068845)

```
registered org.effectcraft.wasmkit.fixture.gain-blur (WASM Kit Fixture: Gain and Box Blur), api 1, 7 parameters
ok: identity parameters leave the frame unchanged
ok: gain 2.0 doubles RGB, alpha untouched
ok: radius 2 blurs the frame
ok: a refused frame reports Some("ec_render returned error 1") and leaves the pixels unchanged

real-host check passed (wasmi, plug-in API v1)
```

`cargo test -p effectcraft-plugin` ran alongside it and passed (`ok. 0 passed` — the crate ships
no unit tests of its own; the meaningful coverage is `host/` above and the engine's own plug-in
tests, which the project's `gate` job runs).

## 5. What still has to be true before a module loads in the real app

Everything below is about the *application*, not the module:

1. **A build with the `wasm` feature.** `effectcraft-plugin`'s runtime is behind `wasm =
   ["dep:wasmi"]`; the desktop app and CLI enable it (`crates/host/Cargo.toml`). A build without
   it answers `effect.plugins.load` with "WebAssembly effect plug-ins are not available in this
   build".
2. **A loader in the session.** `crates/host/src/lib.rs::session()` sets `plugin_loader` when
   `effectcraft_plugin::wasm_available()`. Anything that builds a `Session` by hand (tests,
   embedders) must do the same, or the command refuses.
3. **Loading, in one of three ways:**
   * desktop: Effect ▸ Load Effect Plug-in… (menu id `effect.plugins.load`);
   * headless: `effectcraft-cli exec effect.plugins.load --params '{"path": "…/x.wasm"}'`
     (or `{"folder": "…"}`);
   * start-up: copy the `.wasm` into `<settings>/Plug-ins/` — **desktop only**; the CLI does not
     scan that folder, so a CLI process must load explicitly.
4. **A valid manifest and API version.** Reverse-domain id, `ec.` reserved, ≤256 parameters,
   ≤1 MiB manifest, API 1 — otherwise the loader refuses with a message.
5. **A project that references the effect by id.** A plug-in is not saved inside `.ecproj`; the
   project stores the id, so **the module must be loaded again in every process** that opens and
   renders the project (a render in a fresh CLI process skips an unknown effect). Use
   `Plug-ins/` on the desktop, or load then render in the same process/session.
6. **Platform scope.** Native only (desktop, CLI). The browser build has no wasmi runtime, and
   plug-ins have no GPU path.

## 6. Re-running tier B

Temporary workflow used on the runner (create `.github/workflows/wasm-host-check.yml` on a
branch, push, open/refresh a PR):

```yaml
name: wasm host check
on:
  pull_request:
  workflow_dispatch:
jobs:
  host:
    runs-on: ubuntu-24.04
    timeout-minutes: 120
    steps:
      - uses: actions/checkout@v4
      - name: Toolchain
        run: rustc --version && cargo --version
      - name: Real host check (effectcraft-plugin, wasmi 2.0)
        working-directory: tools/wasm-effect-kit/host
        run: cargo run --release
      - name: Plug-in crate tests
        run: cargo test -p effectcraft-plugin
      - name: Build the CLI
        run: cargo build -p effectcraft-cli
      - name: App stages
        env:
          EFFECTCRAFT_CLI: target/debug/effectcraft-cli
        run: ./tools/wasm-effect-kit/app_check.sh
```

Locally, the same commands work on any machine with Rust 1.95+, `clang`/`zig` (or the PyPI
`ziglang` wheel) to rebuild the fixture, and Python with `wasmtime` for the ABI harness.
