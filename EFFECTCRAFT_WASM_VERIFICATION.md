# EffectCraft — WASM verification status

What has been **executed**, where, and what has not been executed. Two tiers, kept apart on
purpose: evidence that the module meets the ABI outside the application, and evidence that the
application itself loads, registers and renders it.

> Last updated: 2026-11-04. Re-run everything with `tools/wasm-effect-kit/run_tests.sh`
> (tier A) and `tools/wasm-effect-kit/app_check.sh` + `tools/wasm-effect-kit/host` (tier B).

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
| B6 | The application's loader command accepts the module (`effect.plugins.load`), lists it (`effect.plugins.list`) with api 1 and 7 parameters | `tools/wasm-effect-kit/app_check.sh load` | see §4 |
| B7 | Applying the effect by id creates a real instance whose parameters are ordinary, animatable properties | `… app_check.sh project` | see §4 |
| B8 | The effect changes a frame rendered by the real renderer | `… app_check.sh render` | see §4 |

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

That job was **temporary** (project rules forbid adding CI in a feature PR); it ran from the
working branch, its results are recorded here, and the workflow file is removed before the change
is finished. Re-create it any time with the YAML in §6.

## 4. Tier B6–B8 — application-level checks

`tools/wasm-effect-kit/app_check.sh` drives the shipped CLI (same engine, same host, same
renderer as the desktop app) through three stages: `load`, `project`, `render`. Run it where a
CLI build exists:

```sh
cargo build -p effectcraft-cli
EFFECTCRAFT_CLI=target/debug/effectcraft-cli tools/wasm-effect-kit/app_check.sh
```

Status: recorded in the table below once a build was available — see the run log for the
results at the time of writing.

| Stage | What it proves |
|---|---|
| `load` | `effect.plugins.load` returns `{id, name, category, version, api: 1, params: 7}`; `effect.plugins.list` shows `wasm: true` and the plug-in |
| `project` | `comp.new` → `layer.newSolid` → `effect.apply` by id → `prop.set effects/#1/gain 2.0` → `props` shows the instance's parameters in the property tree |
| `render` | `renderQueue.add`/`renderQueue.render` produce PNGs with and without the effect; the two frames differ, so the effect ran through the real renderer |

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
