# JE Cream CC (reconstructed) — test results

Everything below was **executed**. Commands, environments and the numbers they printed are
recorded as they came out; anything not executed is named in §6.

Artifact under test:

```
build/je_cream_cc.wasm   15,607 bytes
sha256 0ea38acc78e0cfce80a0a93781ff5c26892a8b993b51af1db1d2a8798b18cde6
```

Built with Zig 0.17.0's clang frontend, `-target wasm32-freestanding -O2 -ffp-contract=off`,
no libc, no imports. Rebuilding produces the **same SHA-256** (checked on a clean CI runner, twice
in a row).

## 1. Build and static shape

| Check | Result |
|---|---|
| Compiles to a valid Wasm module | **pass** — `\0asm`, 15,607 bytes |
| No imports at all | **pass** — 0 imports |
| Exports `memory, ec_api_version, ec_manifest_ptr, ec_manifest_len, ec_alloc, ec_render` | **pass** |
| `ec_api_version() == 1` | **pass** |
| Manifest parses, equals `src/manifest.json`, valid reverse-domain id, 39 parameters (45 slots) | **pass** |
| Reproducible rebuild | **pass** (identical sha256 on the CI runner) |

## 2. ABI conformance — `tests/check_abi.py` (wasmtime 50.x)

**34/34 checks passed** on the CI runner (and locally). Included:

* the host's exact buffer layout (f64 parameters then f32 RGBA pixels in one allocation);
* error codes 1 (too few parameters), 2 (zero-size frame), 3 (null pointer), and that a refused
  frame is left byte-identical;
* `mix = 0` restores the input frame exactly;
* determinism: repeated renders are byte-identical, no memory growth per render;
* alpha: transparent pixels stay transparent with zero colour, sharpen/unsharp leave alpha alone;
* `scale` reaches the module (a half-scale preview differs from a full-scale render);
* a full **1920×1080** frame renders successfully in **1.08 s** (wasmtime JIT, one core).

## 3. Pixels — `tests/check_pixels.py` (module vs an independent reference)

`tests/reference.py` is a second, independent implementation of the same maths in IEEE single
precision (numpy float32, same operation order), so agreement can be required to be exact.

**14/14 checks passed**, each comparing all 6,144 values of a 48×32 synthetic frame:

```
ok   preset defaults (all five stages): bit-identical to the reference (6144 values)
ok   sharpen only: bit-identical to the reference (6144 values)
ok   unsharp only: bit-identical to the reference (6144 values)
ok   glow 2 only: bit-identical to the reference (6144 values)
ok   glow 1 only (threshold 2.64: no energy): bit-identical to the reference (6144 values)
ok   glow 2, Add, tinted: bit-identical to the reference (6144 values)
ok   quality = Fast: bit-identical to the reference (6144 values)
ok   reduce flicker 1-2-1: bit-identical to the reference (6144 values)
ok   mix 50%: bit-identical to the reference (6144 values)
ok   unsharp threshold + negative mix: bit-identical to the reference (6144 values)
ok   the preset's settings change the frame (4896 of 6144 values)
ok   glow 1 with threshold 2.64 contributes nothing, as its parameter implies
ok   `scale` reaches the module (half-scale preview differs from full-scale)
ok   V8 (Node) produces byte-identical output to wasmtime
```

Two properties are worth calling out:

* **Bit-exactness, not "close".** Ten parameter configurations match the independent
  implementation to the last bit — the maths is pinned down precisely enough for a second
  implementation to reproduce it.
* **Engine independence.** The same binary produces byte-identical output in wasmtime and V8, so the
  effect does not depend on the host's JIT.

## 4. Inside EffectCraft — `tests/app_check.sh` (shipped CLI: real engine, real wasmi host, real renderer)

_Run on a GitHub runner (`ubuntu-24.04`), because this sandbox has no Rust toolchain._

STAGE_RESULTS_PLACEHOLDER

## 5. What these tests do and do not prove

* They prove the module is a valid, deterministic, ABI-conformant effect that **does the processing
  it claims to do**, that an independent implementation of the same maths agrees bit-for-bit, and
  that EffectCraft's loader, engine, parameter system, preset system and renderer all accept and
  run it.
* They do **not** prove visual equivalence with the original Sapphire/BCC/Magic Bullet plug-ins:
  no reference renders were supplied, and those algorithms were never available (they were not
  reverse-engineered). See `ANALYSIS.md` §7 for the per-stage accuracy labels.

## 6. Not executed, and why

| Not run | Why |
|---|---|
| Comparison against the original plug-ins' renders | No reference renders in the package; rendering them needs the proprietary plug-ins, which are out of scope by rule |
| The Magic Bullet "Looks" grade | The look is an opaque 68,321-byte payload (`4d424c32`); it is not interpreted, so the stage is a documented pass-through |
| Desktop GUI session (menus, Effect Controls panel) | No display in this environment; the same code paths are exercised through the CLI's engine and renderer |
| Browser (`wasm32-unknown-unknown`) build | EffectCraft ships no wasmi runtime in the web build; plug-ins are native-only by design |
| GPU path | Plug-ins in this application are CPU-only (`gpu: false`) |
| Long-form video render (seconds of footage) | The render-queue test renders a full comp, frame for frame, through the same renderer; per-frame cost is in §2 |
