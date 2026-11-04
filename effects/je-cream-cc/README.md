# JE Cream CC (reconstructed) — a real EffectCraft plug-in

A WebAssembly effect for EffectCraft that reproduces the **look described by the preset
"JE Cream CC"**: the chain S_Sharpen → BCC Unsharp Mask → Looks → S_Glow → S_Glow 2, rebuilt from
the preset's own parameter values with publicly documented maths.

It is a working effect, not a mock-up: the module compiled here processes real frames, runs in
EffectCraft's own wasmi host, is registered in Effects & Presets, exposes 39 parameters with the
preset's values as defaults, and its parameters take keyframes, eases, expressions, undo and
save/reopen like any built-in effect.

**What it is not:** a copy of the proprietary plug-ins. Their algorithms were never available and
were not reverse-engineered (`EFFECTCRAFT_RECONSTRUCTION_RULES.md` §B0). Sharpening, unsharp
masking and glow are our own implementations matched to the stored settings; Magic Bullet's
"Looks" grade lives in an opaque payload and is **not** reproduced. `ANALYSIS.md` states exactly
which stage is exact, close, approximate or unsupported.

## Contents

| Path | What |
|---|---|
| `build/je_cream_cc.wasm` | the compiled module (wasm32-freestanding, no imports, ~15 KiB) |
| `src/je_cream_cc.c` | complete source of the processing module |
| `src/manifest.json` | the plug-in manifest: 39 parameters, defaults = the preset's values |
| `src/gen_manifest.py` | generates `src/manifest_bytes.h` and `src/param_index.h` from the manifest |
| `build.sh` | builds the module (Zig's clang; any clang with a wasm32 target works) |
| `preset/je-cream-cc.preset.json` | native EffectCraft animation preset (Apply Animation Preset…) |
| `tests/check_abi.py` | 34 ABI checks in wasmtime (exports, manifest, buffer layout, error codes, alpha, determinism, 1080p) |
| `tests/reference.py`, `tests/check_pixels.py` | an independent second implementation and 14 pixel checks against the module |
| `tests/check_v8.mjs` | the same module in V8/Node — engine independence |
| `tests/app_check.sh` | end-to-end check through the real CLI: load, apply, preset, render, pixel parity |
| `ANALYSIS.md` | the complete analysis of the supplied JSON and the reconstruction decisions |
| `TEST-RESULTS.md` | what was actually executed, with the output |

## Use it

```sh
# 1. build the module (Zig >= 0.13, or set ZIG=/path/to/zig)
./build.sh

# 2. load it in EffectCraft
#    desktop:  Effect ▸ Load Effect Plug-in…        (or drop it in <settings>/Plug-ins/)
#    headless: effectcraft-cli exec effect.plugins.load --params '{"path":"…/je_cream_cc.wasm"}'
# 3. apply it
#    Effects & Presets ▸ Reconstruction ▸ "JE Cream CC (reconstructed)"
#    or: effectcraft-cli exec effect.apply --params '{"effect":"org.effectcraft.reconstruction.je-cream-cc"}'

# 4. or start from the preset (applies the effect with these exact values)
#    Animation ▸ Apply Animation Preset… ▸ preset/je-cream-cc.preset.json
```

The effect is CPU-only and native (desktop/CLI): the browser build ships no wasmi runtime, and
plug-ins have no GPU path. It must be loaded again in every process that renders a project
using it — `.ecproj` stores the effect id, not the module.

## Defaults = the preset

| Stage | Parameters (default) |
|---|---|
| Sharpen | on, amp 0.7, edge threshold 0.14, small detail 5 px, width 26.88 px, luma 1.19, chroma 1.24, R 1.18, G 1.15, B 1.21, quality Best |
| Unsharp | on, radius 12 px, amount 6 %, threshold 0, mix 0, flicker Off |
| Looks | strength 76 % — **inactive**, the payload is proprietary |
| Glow 1 | on, brightness 0.32, threshold 2.64 (no pixel clears it: the stage is a no-op by its own values), width 96 px, R 1 / G 1.2 / B 1.4, Screen, affect alpha 1 |
| Glow 2 | on, brightness 0.44, threshold 0.77, width 90 px, R 1 / G 1.2 / B 1.4, Screen, affect alpha 1 |
| Mix | 100 % |

## Rebuild and test

```sh
./build.sh                              # prints size + sha256
python3 tests/check_abi.py              # 34 checks (needs wasmtime)
python3 tests/check_pixels.py           # 14 checks vs the independent reference (needs numpy, wasmtime, node)
tests/app_check.sh                      # in-app (needs a built effectcraft-cli; see TEST-RESULTS.md)
```

## Performance

Measured in wasmtime on one core of this sandbox: **1.5 s for a 1920×1080 frame** with the preset
defaults (the whole five-stage chain, including four sharpening bands per channel and the glow).
EffectCraft renders previews at reduced resolution, where the cost falls with the pixel count;
`quality = Fast` cuts the blur passes from three to one. EffectCraft's wasmi interpreter is slower
than wasmtime's JIT — see `TEST-RESULTS.md` for the in-app number.

## Licence and provenance

Original work for this repository, under the project's own licence. Derived from the *settings* the
supplied preset stores (parameter names, values, ranges, animation metadata) and from public
technique descriptions. No proprietary code, binary, look-up table or preset format was read,
copied or shipped.
