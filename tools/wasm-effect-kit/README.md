# WASM effect kit

Everything needed to build, check and integrate **WebAssembly effect plug-ins** for EffectCraft
(plug-in API v1, documented in [`docs/plugins.md`](../../docs/plugins.md) and specified for
implementers in [`EFFECTCRAFT_WASM_INTERFACE.md`](../../EFFECTCRAFT_WASM_INTERFACE.md)).

The kit is a foundation, not an effect: `fixture/` is an ABI conformance test that proves the
whole path works — compile → `.wasm` → load → allocate → write parameters and pixels → run →
read pixels back → error codes → execution limits. Future reconstructed effects are built with
the same plumbing (see [`EFFECTCRAFT_RECONSTRUCTION_RULES.md`](../../EFFECTCRAFT_RECONSTRUCTION_RULES.md)).

## What is here

| Path | What it is |
|---|---|
| `fixture/ec_gain_blur.c` | The fixture module in C: a deterministic separable box blur + gain + tint + alpha mode. **Test fixture only.** |
| `fixture/plugin.json` | Its manifest — the single source of truth, embedded into the module at build time. |
| `fixture/ec_spin.c` | A runaway module, used to prove the runtime's fuel limit stops a plug-in instead of hanging the host. |
| `fixture/build.sh` | Compiles both to `.wasm` (`wasm32-freestanding`, no imports, no libc). |
| `fixture/check_host.py` | Stand-in host + 48 checks, in wasmtime (Python). Mirrors `crates/plugin/src/wasm.rs`. |
| `fixture/check_host.mjs` | The same contract in Node's V8, to prove the module is engine-independent. |
| `host/` | The **real-host** check: loads the fixture through `effectcraft-plugin` (wasmi). Needs cargo. |
| `run_tests.sh` | Builds, then runs both runtimes' harnesses. |

## Run it

```sh
tools/wasm-effect-kit/run_tests.sh
```

Requirements: Zig (or `pip install ziglang`), and either `pip install wasmtime` or a system
Python with it; Node is optional (the V8 check is skipped without it). No network access is
needed once those are installed. Exact versions used, and what could not be run in the build
sandbox, are recorded in [`EFFECTCRAFT_WASM_TOOLCHAIN.md`](../../EFFECTCRAFT_WASM_TOOLCHAIN.md).

The real-host check (needs a Rust toolchain, and the workspace's dependencies):

```sh
cd tools/wasm-effect-kit/host && cargo run --release
```

## Use it for a new effect

1. Copy `fixture/` to `extensions/effects/<your-effect>/`.
2. Write your manifest (`plugin.json`) — id, category, typed parameters with defaults and ranges.
3. Implement `ec_render` in your language of choice (C, Zig, Rust, AssemblyScript…), following
   the ABI in `EFFECTCRAFT_WASM_INTERFACE.md`. No imports.
4. Build to `.wasm`, run `check_host.py`-style checks against your own reference implementation,
   then load it in the app: Effect ▸ Load Effect Plug-in…, or
   `effectcraft-cli exec effect.plugins.load '{"path": "…/your.wasm"}'`.
5. Parameters, keyframes, expressions, Effect Controls, Effect & Presets listing, save/reopen and
   the render queue then work exactly as they do for a built-in effect: a plug-in's parameters
   are ordinary properties in the layer's property tree.
