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

## 4. Inside EffectCraft — `tests/app_check.sh` (the shipped CLI: real engine, real wasmi host, real renderer)

Run on a GitHub runner (`ubuntu-24.04`, `CI / JE Cream CC effect checks`), because this sandbox has
no Rust toolchain. The script drives `effectcraft-cli` exactly as a user would — `comp.new`,
`layer.newSolid`, `effect.plugins.load`, `effect.apply`, `anim.savePreset`, `anim.applyPreset`,
`prop.set`, `prop.addKey`, `prop.get`, `renderQueue.*` — and asserts on the JSON each command
returns and on the PNGs the renderer writes. Every stage passed:

```
PASS load: registered org.effectcraft.reconstruction.je-cream-cc (api 1, 39 parameters, wasm runtime available)
PASS apply: applied by id as effects/#1; glow2_brightness keyed at 0.5 s (Linear), project saved, preset written with 1 effect
PASS apply: saved <tmp>/je.ecproj
PASS preset: anim.applyPreset rebuilt the effect on the text layer; Glow 2 Threshold = 0.77 (it was saved at 0.55, so this is the preset's value)
PASS render: the app's renderer reproduces the standalone module's pixels (display-referred, scale 1: mean 0.10/255, worst 1/255, 100.0% within 2/255) - the residue is 8-bit PNG and f32 quantisation
```

The run is `JE Cream CC effect checks` on commit `5b2777c` (all five stages green). What each stage
actually asserts:

* **load** — `effect.plugins.load` returns the module as `org.effectcraft.reconstruction.je-cream-cc`
  with `api 1`, `params 39`, no errors, and the host reports a working WebAssembly runtime.
* **apply** — `effect.apply {"effect": "<id>"}` puts it on the layer as `effects/#1`; a parameter is
  changed with `prop.set`, keyed with `prop.addKey` (Linear) and read back with `prop.get` at 0.5 s;
  `anim.savePreset` writes a preset containing the effect; the project is saved and reopened with the
  effect, its values and its keyframe intact.
* **preset** — a *fresh* comp, with the effect applied from the saved `preset/je-cream-cc.preset.json`
  by `anim.applyPreset`: the effect is rebuilt with its 39 properties, and `Glow 2 Threshold` reads
  0.77 — the value the preset was saved with, not the 0.55 the previous stage left on the other
  layer.

### The renders

* Frame: 320×180, a checkerboard effect over a solid (`Blending Mode = Normal`), so the composite
  is opaque and **is** the layer the plug-in sees.

```
mean |with - without| = 5.95/255 per channel
horizontal gradient energy: without 274320, with 836624 (+205.0%)
without-effect frame: rgb(255,255,255) x30464, rgb(128,128,128) x27136
```

The effect visibly sharpens (high-frequency energy up 205 %) and glows.

### Pixel parity: the app's render vs the module run standalone

The compiled module is run on the *without-effect* PNG and its output is compared with the app's
*with-effect* PNG. Because the host's frame encoding is not documented anywhere in the repository,
the check first measured it, using a flat 0.9-grey frame (sharpening and unsharp masking are
identities there, so the output is a single number that depends only on the encoding):

```
flat field (0.9 grey): the effect only fires glow 2, so one number decides the encoding
  without effect: (230, 230, 230)   with effect: (231, 231, 231)
  module, display in: (231.5, 231.5, 231.5)
  module, linear  in: (230.3, 230.3, 230.3)
```

It then compared the full chain under both encodings and three candidate scales:

```
parity hypotheses (how the host might encode the frame it hands a plug-in):
  display space, scale 1.0 : mean  0.10/255, worst     1, 100.0% within 2/255 | interior 0.11, edge 0.02
  display space, scale 0.5 : mean  0.25/255, worst     2, 100.0% within 2/255 | interior 0.26, edge 0.05
  display space, scale 2.0 : mean  0.24/255, worst     2, 100.0% within 2/255 | interior 0.25, edge 0.04
  linear  space, scale 1.0 : mean  2.11/255, worst     6,  55.2% within 2/255 | interior 2.22, edge 0.50
  linear  space, scale 0.5 : mean  2.35/255, worst     7,  55.2% within 2/255 | interior 2.48, edge 0.52
  linear  space, scale 2.0 : mean  2.09/255, worst     6,  55.2% within 2/255 | interior 2.20, edge 0.50
best: display space, scale 1.0 -> mean 0.10/255, worst 1/255, 100.0% of channels within 2/255
PASS render: the app's renderer reproduces the standalone module's pixels (display-referred,
scale 1) - the residue is 8-bit PNG and f32 quantisation
```

So: EffectCraft hands a plug-in the layer's display-referred, premultiplied `f32` pixels with
`scale = 1` at full render quality — which is what the module assumes. The one-unit worst-case
residue over 57,600 pixels is 8-bit PNG quantisation; a wrong encoding would be worth 2/255 on
average, a wrong scale much more. The check now asserts on that identified configuration
(mean ≤ 1/255, ≥ 99 % of channels within 2/255) and prints the other rows so that a future host
change shows up as a clear failure instead of a silent drift.

### Cost

The five-stage chain ran the full 320×180 frame four times (two renders, one parity run per
hypothesis) in a few seconds inside the app's wasmi interpreter. Per-frame cost at 1080p is in §2.

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
