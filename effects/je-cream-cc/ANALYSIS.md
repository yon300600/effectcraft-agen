# "JE Cream CC" — complete analysis of the supplied reconstruction JSON

> Source: `JE Cream CC.effectcraft.json` (`effectcraft.ffx.v2`, 15,224,429 bytes of JSON describing
> a 194,922-byte `JE Cream CC.ffx` written by After Effects 94.3). The JSON was produced by the
> user's own tooling and supplied for this task. It was read in full; the binary payloads inside it
> were identified (size, SHA-256, first bytes) and **not** interpreted — see the boundary below.
>
> Regenerate the tables with `tools/analyze.py "/path/JE Cream CC.effectcraft.json"`.

## 1. What the package contains

The preset is **not** a single effect: it is a chain of five effects applied to one layer, in this
order.

| # | match name | display name | vendor / suite | parameters | reconstructed here |
|---|---|---|---|---|---|
| 1 | `S_Sharpen` | S_Sharpen | Boris FX — Sapphire | 28 | **yes**, independently |
| 2 | `BCC Unsharp Mask` | BCC Unsharp Mask | Boris FX — Continuum | 38 | **yes**, independently |
| 3 | `Looks` | Looks | Maxon/Red Giant — Magic Bullet | 6 | **no** — opaque payload |
| 4 | `S_Glow` | S_Glow | Boris FX — Sapphire | 38 | **yes**, independently |
| 5 | `S_Glow` | S_Glow 2 | Boris FX — Sapphire | 54 | **yes**, independently |

Compositing options for all five: opacity 100 %, no mask, no "Force CPU/GPU" override, so the
chain is a straight sequence of pixel operations on the layer.

## 2. Animation and timebase

* **0 keyframes** anywhere in the file (`accounting.keyframes: 0`, and every
  `properties[].hasKeyframes` is false).
* **0 expressions** (`accounting.expressions: 0`).
* Every property carries its own timebase annotation: *"Keyframe seconds are tick ÷ 30720"*
  (`animationTimebase: 30720` for the serialized streams; the file-level stream is `tdb4`
  30720 as well). Nothing in this preset depends on a global timebase.
* Therefore **there is no animation to reconstruct**. The reconstruction exposes every parameter
  as an ordinary animatable EffectCraft property (`prop.set`, `prop.addKey`, eases, expressions),
  and the in-app check keys one of them to prove that path works — but the preset itself is a
  static look, and claiming otherwise would be invention.

## 3. Boundary: what was *not* read

Per `EFFECTCRAFT_RECONSTRUCTION_RULES.md` §B0 (and `AGENTS.md` §2):

* No Adobe application, no plug-in binary and no `.ffx` binary was opened, disassembled,
  decompiled, decrypted, emulated or pattern-matched.
* The JSON's opaque payloads — 13 `pluginData` records, incl. the 68,321-byte Magic Bullet look
  (`4d424c32` = "MBL2") — were identified by size, SHA-256 and first bytes only. Their contents
  were not studied and were not used to derive any algorithm. The table in §8 lists them.
* Everything the reconstruction does is derived from (a) the parameter names, values and ranges
  the JSON decodes and (b) publicly documented image-processing technique. The proprietary
  implementations are neither known nor reproduced.

## 4. Parameters that actually matter in this preset

Values below are the preset author's saved settings (defaults from the descriptors in brackets).

**S_Sharpen** — Quality *Best* (Best/Fast), Sharpen Amp **0.7** [1], Edge Threshold **0.14**
[0.15], Small Detail Size **5** px [2.4], Sharpen Width **26.88** px [26.88] (hidden in the UI),
Sharpen Luma **1.19** [1], Sharpen Chroma **1.24** [1], Sharpen Red **1.18**, Green **1.15**,
Blue **1.21** [1], Opacity *Normal*, Mask Use *Luma*, Blur Mask 12, Invert Mask off. Detail-level
scales are left at their descriptor defaults: Tiny 3, Small 1.5, Medium 1, Large 2.

**BCC Unsharp Mask** — Radius **12** [1], Amount **6** [50] (%), Threshold **0** [0], Output
Channels *RGBA*, Reduce Flicker *Off*, Mix with Original **0** [0].

**Looks** — Strength **76** %; the look itself is the 68,321-byte `MBL2` payload (§8).

**S_Glow (1)** — Brightness **0.32** [2], Color white, Threshold **2.64** [0.5] (its advertised
range is 0…1, so the stored value means "no pixel is bright enough": this stage contributes
nothing), Glow Width **96** px [96], Width X/Y 1, Width Red 1, Green **1.2**, Blue **1.4**,
Subpixel on, Combine *Screen* [Screen], Edge Mode *Reflect*, Affect Alpha **1**, Glow From Alpha 0,
Glow Under Source 0, Light Background 0, Source Opacity 1, Bg Brightness 1, Atmosphere off.

**S_Glow (2)** — Brightness **0.44**, Threshold **0.77** (this is the glow that fires), Glow Width
**90** px, Width Red 1, Green **1.2**, Blue **1.4**, Combine *Screen*, Affect Alpha **1**,
Atmosphere off (Amp 0).

## 5. What the reconstruction implements

| preset parameter | module parameter | treatment |
|---|---|---|
| S_Sharpen Sharpen Amp / Edge Threshold / Small Detail Size / Sharpen Width | `sharpen_amp`, `edge_threshold`, `small_detail`, `sharpen_width` | own 4-band Laplacian sharpening, edge-masked |
| S_Sharpen Luma / Chroma / Red / Green / Blue | `sharpen_luma`, `sharpen_chroma`, `sharpen_r/g/b` | luma/chroma split + per-channel gains |
| S_Sharpen Quality | `quality` (Best/Fast) | 3-pass box blur vs 1-pass |
| BCC Radius / Amount / Threshold / Mix / Reduce Flicker | `unsharp_radius`, `unsharp_amount`, `unsharp_threshold`, `unsharp_mix`, `flicker` | textbook unsharp mask |
| S_Glow ×2 Brightness / Threshold / Glow Width / per-channel widths / Color / Combine / Affect Alpha | `glow{1,2}_*` | thresholded bloom, per-channel blur radii, 5 combine modes |
| Look / strength | `looks_strength` | **inactive** — documented, not faked |
| Matte/Mocha/Mask/Background/Atmosphere/Presets/Help buttons | — | not applicable (unused in this preset) or unsupported (mattes need a host matte layer) |

Added for usability, not present in the preset: `mix` (0–100 %). Everything else is the preset's.

## 6. Assumptions, stated so they can be argued with

1. **Radii are layer pixels**, multiplied by the host's `scale` for previews (After Effects
   semantics). The preset was authored at 1920 px, so at 1080p the glow is 90–96 px wide.
2. **S_Glow "Threshold" is a luminance threshold in 0…1.** The stored 2.64 is outside the
   advertised range (After Effects lets a value be typed past the slider's maximum); read
   literally, no pixel clears it and glow 1 does nothing. The module keeps the value and therefore
   reproduces that behaviour. It is exposed, so lowering it brings the stage to life.
3. **Sharpen detail bands** are the differences between successive blurs at radii derived from
   `small_detail` (finest, ×0.25), `small_detail`, their geometric mean, and `sharpen_width`
   (widest), weighted 3 / 1.5 / 1 / 2 — the descriptor defaults of Scale Tiny/Small/Medium/Large
   Details. Sapphire's own band construction is unknown; this is a documented equivalent.
4. **Edge mask**: the Sobel slope of luma, normalised so a full black→white step equals 1, ramped
   over 0.25 starting at Edge Threshold.
5. **Blur** is a 3-pass box blur (an approximation of a Gaussian with the same support).
6. **Glow** bright-passes `max(0, luma − threshold)` at the pixel's own colour, blurs each channel
   at its own radius, multiplies by Brightness, and combines with the source using the selected
   operator on display-referred (sRGB) values — the space the engine hands plug-ins.
7. **Looks** cannot be reproduced: the grade lives in a proprietary payload that this project does
   not interpret. The module is a pass-through there.

## 7. Accuracy labels (this file, and the README)

| Stage | Label | Basis |
|---|---|---|
| S_Sharpen (bands, mask, gains, luma/chroma) | **approximate** | own algorithm from the stored settings; no reference render, proprietary bands unknown |
| BCC Unsharp Mask | **close** | textbook maths with the preset's radius/amount/threshold; multiply-vs-linear details unknown |
| Looks | **unsupported** | opaque proprietary payload |
| S_Glow 2 | **approximate** | own bloom matched to the stored widths/threshold/brightness/combine |
| S_Glow 1 | **exact, trivially** | its stored threshold admits no pixel, so it is a no-op by its own parameters |
| Parameter set, defaults, ranges, animatability | **exact** | taken from the JSON's own decoded values |
| Keyframes / expressions | **not applicable** | the preset contains none |

No reference renders were supplied with the package, so no comparison against the original plug-ins
was possible; the verification that *was* possible (bit-exact agreement with an independent second
implementation, ABI conformance, and real in-app renders) is in `TEST-RESULTS.md`.

## 8. Full inventory, as decoded by the package

file: `JE Cream CC.ffx` — 194922 bytes on disk, 194922 bytes of FaFX

* container: `RIFX` / `FaFX`, big-endian, valid: True
* declared size 191082, actual end 191090
* written by After Effects 94.3
* 5 effects, 225 editable parameters (214 decoded, 11 partial), 194 descriptors, 0 keyframes, 0 expressions, 41 unknown chunks, 2772 binary records

| # | match name | display name | vendor | suite | parameters |
|---|---|---|---|---|---|
| 1 | `S_Sharpen` | S_Sharpen | Boris FX (inferred) | Sapphire | 28 |
| 2 | `BCC Unsharp Mask` | BCC Unsharp Mask  | Boris FX (inferred) | Continuum / BCC | 38 |
| 3 | `Looks` | Looks | Maxon / Red Giant (inferred) | Magic Bullet Looks | 6 |
| 4 | `S_Glow` | S_Glow | Boris FX (inferred) | Sapphire | 38 |
| 5 | `S_Glow` | S_Glow 2 | Boris FX (inferred) | Sapphire | 54 |

#### 1. `S_Sharpen` (S_Sharpen)

| parameter | control | type | value | min..max | slider | units | options | notes |
|---|---|---|---|---|---|---|---|---|
| Load Preset | button | button | 0 | null..null | null..null | — | — | — |
| Save Preset | button | button | 0 | null..null | null..null | — | — | — |
| Matte from Layer | custom / no data | layer-reference | 0 | null..null | null..null | — | — | — |
| Matte from Path | path / mask | mask-reference | -1 | null..null | null..null | — | — | — |
| Quality | dropdown | scalar | 1 | 1..2 | null..null | — | ["Best", "Fast"] | — |
| mocha | arbitrary data | arbitrary data | null | null..null | null..null | — | — | hidden, partial |
| Edit Mocha | button | button | 0 | null..null | null..null | — | — | — |
| Mocha | group start | scalar | 0 | null..null | null..null | — | — | — |
| Sharpen Amp | fixed slider | scalar | 0.6999999999999998 | 0..10 | 0..10 | — | — | — |
| Edge Threshold | fixed slider | scalar | 0.14 | 0..1 | 0..1 | — | — | — |
| Small Detail Size | fixed slider | scalar | 5 | 0..48 | 0..48 | — | — | — |
| Detail Levels | group start | scalar | 0 | null..null | null..null | — | — | — |
| Sharpen Width | fixed slider | scalar | 26.879989624023438 | 0..960 | 0..960 | — | — | hidden |
| Sharpen Luma | fixed slider | scalar | 1.1899999999999986 | 0..5 | 0..5 | — | — | — |
| Sharpen Chroma | fixed slider | scalar | 1.2400000000000002 | 0..5 | 0..5 | — | — | — |
| Sharpen Red | fixed slider | scalar | 1.1800000000000002 | 0..5 | 0..5 | — | — | — |
| Sharpen Green | fixed slider | scalar | 1.1500000000000001 | 0..5 | 0..5 | — | — | — |
| Sharpen Blue | fixed slider | scalar | 1.2100000000000002 | 0..5 | 0..5 | — | — | — |
| Opacity | dropdown | scalar | 2 | 1..3 | null..null | — | ["All Opaque", "Normal", "As Premult"] | — |
| Mask Use | dropdown | scalar | 1 | 1..2 | null..null | — | ["Luma", "Alpha"] | — |
| Blur Mask | fixed slider | scalar | 12 | 0..960 | 0..960 | — | — | — |
| Invert Mask | checkbox | scalar | false | 0..1 | null..null | — | — | — |
| Show Small Detail Size | checkbox | scalar | true | 0..1 | null..null | — | — | — |
| Help | button | button | 0 | null..null | null..null | — | — | — |
| Compositing Options | layer reference | property-group | null | null..null | null..null | — | — | not-applicable |
| S_Sharpen-0000 | — | layer-reference | 359 | null..null | null..null | — | — | hidden |
| S_Sharpen-0251 | group end | scalar | 0 | null..null | null..null | — | — | — |
| S_Sharpen-0253 | group end | scalar | 0 | null..null | null..null | — | — | — |

#### 2. `BCC Unsharp Mask` (BCC Unsharp Mask )

| parameter | control | type | value | min..max | slider | units | options | notes |
|---|---|---|---|---|---|---|---|---|
| Effect Presets & Docs | layer reference | scalar | 0 | null..null | null..null | — | — | — |
| Compare | group start | scalar | 0 | null..null | null..null | — | — | — |
| Radius | fixed slider | scalar | 12 | 0..100 | 0..100 | — | — | — |
| Amount | fixed slider | scalar | 6 | 0..200 | 0..200 | — | — | — |
| Threshold | fixed slider | scalar | 0 | 0..100 | 0..100 | — | — | — |
| Output Channels | dropdown | scalar | 1 | 1..9 | null..null | — | ["RGBA", "RGB", "Alpha", "Red", "Green"… | — |
| Reduce Flicker | dropdown | scalar | 1 | 1..4 | null..null | — | ["Off", "1-2-1", "2-3-2", "1-1-1"] | — |
| Mix with Original | fixed slider | scalar | 0 | -300..300 | -300..300 | — | — | — |
| PixelChooser / Mocha | group start | scalar | 0 | null..null | null..null | — | — | — |
| Legacy PixelChooser | dropdown | scalar | 1 | 1..5 | null..null | — | ["Off", "On", "View Chosen Pixels", "Ma… | — |
| PC Intensity | fixed slider | scalar | 100 | -300..300 | -300..300 | — | — | — |
| Controls | dropdown | scalar | 3 | 1..3 | null..null | — | ["Amount", "Threshold", "Amount & Thres… | hidden |
| Mask | path / mask | mask-reference | -1 | null..null | null..null | — | — | — |
| Shape | dropdown | scalar | 1 | 1..10 | null..null | — | ["All", "Inside Rectangle", "Outside Re… | — |
| Point 1 | point 2D | 2D spatial | [0.5, 0.5] | null..null | null..null | layer-normalized | — | hidden |
| Point 2 | point 2D | 2D spatial | [0.9500000000000001, 0.950000… | null..null | null..null | layer-normalized | — | hidden |
| From | fixed slider | scalar | -50 | -100..100 | -100..100 | — | — | — |
| To | fixed slider | scalar | 30 | -100..100 | -100..100 | — | — | — |
| Scale | fixed slider | scalar | 100 | 0..1000 | 0..1000 | — | — | — |
| Stretch/Direction | fixed slider | scalar | 0 | -200..200 | -200..200 | — | — | — |
| Region Blend | fixed slider | scalar | 10 | 0..200 | 0..200 | — | — | — |
| Reverse Range | checkbox | scalar | false | 0..1 | null..null | — | — | — |
| Channel | dropdown | scalar | 1 | 1..16 | null..null | — | ["None", "Luma", "Red", "Green ", "Blue… | — |
| Matte Layer | custom / no data | layer-reference | 0 | null..null | null..null | — | — | — |
| Type | dropdown | scalar | 1 | 1..3 | null..null | — | ["Levels", "Threshold", "Range"] | — |
| Black/Threshold/From | fixed slider | scalar | 0 | -100..400 | -100..400 | — | — | — |
| White/To | fixed slider | scalar | 255 | -100..400 | -100..400 | — | — | — |
| Matte Softness | fixed slider | scalar | 20 | 0..255 | 0..255 | — | — | — |
| Color | color | color | [0, 0, 0, 1] | null..null | null..null | — | — | partial |
| Blur Matte | fixed slider | scalar | 0 | 0..50 | 0..50 | — | — | — |
| Choke Matte | fixed slider | scalar | 0 | -20..20 | -20..20 | — | — | — |
| Invert Matte | checkbox | scalar | false | 0..1 | null..null | — | — | — |
| Compositing Options | layer reference | property-group | null | null..null | null..null | — | — | not-applicable |
| BCC3Unsharp Mask-0000 | — | layer-reference | 359 | null..null | null..null | — | — | hidden |
| BCC3Unsharp Mask-10158086 | group end | scalar | 0 | null..null | null..null | — | — | — |
| BCC3Unsharp Mask-11010066 | group end | scalar | 0 | null..null | null..null | — | — | — |
| BCC3Unsharp Mask-11010094 | group end | scalar | 0 | null..null | null..null | — | — | — |
| BCC3Unsharp Mask-11010051 | group end | scalar | 0 | null..null | null..null | — | — | — |

#### 3. `Looks` (Looks)

| parameter | control | type | value | min..max | slider | units | options | notes |
|---|---|---|---|---|---|---|---|---|
| MB LookSuite3-0015 | layer reference | scalar | 0 | null..null | null..null | — | — | — |
| Look | arbitrary data | arbitrary data | null | null..null | null..null | — | — | partial |
| MB LookSuite3-0014 | button | button | 0 | null..null | null..null | — | — | hidden |
| Strength | float slider | scalar | 76 | 0..100 | 0..100 | percent | — | — |
| Compositing Options | layer reference | property-group | null | null..null | null..null | — | — | not-applicable |
| MB LookSuite3-0000 | — | layer-reference | 359 | null..null | null..null | — | — | hidden |

#### 4. `S_Glow` (S_Glow)

| parameter | control | type | value | min..max | slider | units | options | notes |
|---|---|---|---|---|---|---|---|---|
| Load Preset | button | button | 0 | null..null | null..null | — | — | — |
| Save Preset | button | button | 0 | null..null | null..null | — | — | — |
| Background | custom / no data | layer-reference | 0 | null..null | null..null | — | — | — |
| Matte from Layer | custom / no data | layer-reference | 0 | null..null | null..null | — | — | — |
| Matte from Path | path / mask | mask-reference | -1 | null..null | null..null | — | — | — |
| mocha | arbitrary data | arbitrary data | null | null..null | null..null | — | — | hidden, partial |
| Edit Mocha | button | button | 0 | null..null | null..null | — | — | — |
| Mocha | group start | scalar | 0 | null..null | null..null | — | — | — |
| Brightness | fixed slider | scalar | 0.3200000000000001 | 0..5 | 0..5 | — | — | — |
| Color | color | color | [1, 1, 1, 1] | null..null | null..null | — | — | partial |
| Threshold | fixed slider | scalar | 2.6400000000000006 | 0..1 | 0..1 | — | — | — |
| Threshold Add Color | color | color | [0, 0, 0, 1] | null..null | null..null | — | — | partial |
| Glow Width | fixed slider | scalar | 96 | 0..960 | 0..960 | — | — | — |
| Width X | fixed slider | scalar | 1 | 0..5 | 0..5 | — | — | — |
| Width Y | fixed slider | scalar | 1 | 0..5 | 0..5 | — | — | — |
| Width Red | fixed slider | scalar | 1 | 0..5 | 0..5 | — | — | — |
| Width Green | fixed slider | scalar | 1.1999969482421875 | 0..5 | 0..5 | — | — | — |
| Width Blue | fixed slider | scalar | 1.399993896484375 | 0..5 | 0..5 | — | — | — |
| Subpixel | checkbox | scalar | true | 0..1 | null..null | — | — | — |
| Show | dropdown | scalar | 1 | 1..2 | null..null | — | ["Result", "Threshold"] | — |
| Combine | dropdown | scalar | 3 | 1..5 | null..null | — | ["Mult", "Add", "Screen", "Difference",… | — |
| Edge Mode | dropdown | scalar | 2 | 1..2 | null..null | — | ["Transparent", "Reflect"] | — |
| Affect Alpha | fixed slider | scalar | 1 | 0..1 | 0..1 | — | — | — |
| Glow From Alpha | fixed slider | scalar | 0 | 0..1 | 0..1 | — | — | — |
| Glow Under Source | fixed slider | scalar | 0 | 0..1 | 0..1 | — | — | — |
| Light Background | fixed slider | scalar | 0 | 0..1 | 0..1 | — | — | — |
| Source Opacity | fixed slider | scalar | 1 | 0..1 | 0..1 | — | — | — |
| Bg Brightness | fixed slider | scalar | 1 | 0..1 | 0..1 | — | — | — |
| Invert Matte | checkbox | scalar | false | 0..1 | null..null | — | — | — |
| Expand Borders | checkbox | scalar | false | 0..1 | null..null | — | — | — |
| Atmosphere | group start | scalar | 0 | null..null | null..null | — | — | — |
| Opacity | dropdown | scalar | 2 | 1..3 | null..null | — | ["All Opaque", "Normal", "As Premult"] | — |
| Show Glow Width | checkbox | scalar | true | 0..1 | null..null | — | — | — |
| Help | button | button | 0 | null..null | null..null | — | — | — |
| Compositing Options | layer reference | property-group | null | null..null | null..null | — | — | not-applicable |
| S_Glow-0000 | — | layer-reference | 359 | null..null | null..null | — | — | hidden |
| S_Glow-0251 | group end | scalar | 0 | null..null | null..null | — | — | — |
| S_Glow-0253 | group end | scalar | 0 | null..null | null..null | — | — | — |

#### 5. `S_Glow` (S_Glow 2)

| parameter | control | type | value | min..max | slider | units | options | notes |
|---|---|---|---|---|---|---|---|---|
| S_Glow-0000 | — | layer-reference | 359 | null..null | null..null | — | — | hidden |
| Load Preset | — | scalar | 0 | null..null | null..null | — | — | — |
| Save Preset | — | scalar | 0 | null..null | null..null | — | — | — |
| Background | — | layer-reference | 0 | null..null | null..null | — | — | — |
| Matte from Layer | — | layer-reference | 0 | null..null | null..null | — | — | — |
| Matte from Path | — | mask-reference | -1 | null..null | null..null | — | — | — |
| mocha | — | no-value | null | null..null | null..null | — | — | hidden, undecoded |
| Edit Mocha | — | scalar | 0 | null..null | null..null | — | — | — |
| Mocha | — | scalar | 0 | null..null | null..null | — | — | — |
| Blur Mocha | — | scalar | 0 | 0..96 | null..null | — | — | — |
| Mocha Opacity | — | scalar | 1 | 0..1 | null..null | — | — | — |
| Invert Mocha | — | scalar | 0 | null..null | null..null | — | — | — |
| Resize Mocha | — | scalar | 1 | 0..2 | null..null | — | — | — |
| Resize Rel X | — | scalar | 1 | 0..2 | null..null | — | — | — |
| Resize Rel Y | — | scalar | 1 | 0..2 | null..null | — | — | — |
| Shift Mocha X | — | scalar | 0 | -3840..3840 | null..null | — | — | — |
| Shift Mocha Y | — | scalar | 0 | -3840..3840 | null..null | — | — | — |
| Bypass Mocha | — | scalar | 0 | null..null | null..null | — | — | — |
| Show Mocha Only | — | scalar | 0 | null..null | null..null | — | — | — |
| Combine Masks | — | scalar | 1 | null..null | null..null | — | — | — |
| S_Glow-0251 | — | scalar | 0 | null..null | null..null | — | — | — |
| Brightness | — | scalar | 0.44000000000000006 | 0..5 | null..null | — | — | — |
| Color | — | color | [1, 1, 1, 1] | null..null | null..null | — | — | partial |
| Threshold | — | scalar | 0.7700000000000002 | 0..1 | null..null | — | — | — |
| Threshold Add Color | — | color | [0, 0, 0, 1] | null..null | null..null | — | — | partial |
| Glow Width | — | scalar | 90 | 0..960 | null..null | — | — | — |
| Width X | — | scalar | 1 | 0..5 | null..null | — | — | — |
| Width Y | — | scalar | 1 | 0..5 | null..null | — | — | — |
| Width Red | — | scalar | 1 | 0..5 | null..null | — | — | — |
| Width Green | — | scalar | 1.1999969482421875 | 0..5 | null..null | — | — | — |
| Width Blue | — | scalar | 1.399993896484375 | 0..5 | null..null | — | — | — |
| Subpixel | — | scalar | 1 | null..null | null..null | — | — | — |
| Show | — | scalar | 1 | null..null | null..null | — | — | — |
| Combine | — | scalar | 3 | null..null | null..null | — | — | — |
| Edge Mode | — | scalar | 2 | null..null | null..null | — | — | — |
| Affect Alpha | — | scalar | 1 | 0..1 | null..null | — | — | — |
| Glow From Alpha | — | scalar | 0 | 0..1 | null..null | — | — | — |
| Glow Under Source | — | scalar | 0 | 0..1 | null..null | — | — | — |
| Light Background | — | scalar | 0 | 0..1 | null..null | — | — | — |
| Source Opacity | — | scalar | 1 | 0..1 | null..null | — | — | — |
| Bg Brightness | — | scalar | 1 | 0..1 | null..null | — | — | — |
| Invert Matte | — | scalar | 0 | null..null | null..null | — | — | — |
| Expand Borders | — | scalar | 0 | null..null | null..null | — | — | — |
| Atmosphere | — | scalar | 0 | null..null | null..null | — | — | — |
| Atmosphere Amp | — | scalar | 0 | 0..5 | null..null | — | — | — |
| Atmosphere Freq | — | scalar | 1 | 0.09999…..20 | null..null | — | — | — |
| Atmosphere Detail | — | scalar | 0.5999908447265625 | 0..1 | null..null | — | — | — |
| Atmosphere Seed | — | scalar | 0.12298583984375 | 0..5 | null..null | — | — | — |
| Atmosphere Speed | — | scalar | 1 | -5..5 | null..null | — | — | — |
| S_Glow-0253 | — | scalar | 0 | null..null | null..null | — | — | — |
| Opacity | — | scalar | 2 | null..null | null..null | — | — | — |
| Show Glow Width | — | scalar | 1 | null..null | null..null | — | — | — |
| Help | — | scalar | 0 | null..null | null..null | — | — | — |
| Compositing Options | — | property-group | null | null..null | null..null | — | — | not-applicable |

#### Opaque payloads (identified, never interpreted)

| id | effect | signature | bytes | SHA-256 | first bytes | status |
|---|---|---|---|---|---|---|
| plugin-1 | effect-1 | `aRbp` | 1 | `6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d` | `00` | undecoded |
| plugin-2 | effect-1 | `aRbp` | 1 | `6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d` | `00` | undecoded |
| plugin-3 | effect-1 | `sdat` | 16 | `c204e446676401e94333d12ddaa2b0086c0fe931cf2088f717ee22c46840c2ac` | `77777777` | partial |
| plugin-4 | effect-2 | `aRbp` | 16 | `3f36b294943f52550addd353ed5b558d34d85f8f482ef75ba4f1296faaeb6774` | `00000001` | partial |
| plugin-5 | effect-2 | `aRbp` | 16 | `3f36b294943f52550addd353ed5b558d34d85f8f482ef75ba4f1296faaeb6774` | `00000001` | partial |
| plugin-6 | effect-2 | `sdat` | 200 | `1318371ac542e45a818da2009c20b11dc35b810df69949d1917123fb203e1042` | `00000001` | undecoded |
| plugin-7 | effect-3 | `aRbp` | 4 | `abcfb3b6df79b33223d7ae7e2cdd7befdc60cc82d23147711aca19a8beb8f9ca` | `00007d9b` | partial |
| plugin-8 | effect-3 | `aRbp` | 68321 | `43d98e53a3d4a181a4b5c62785ca4073f3bac2036e49e3053141d2cc273ff256` | `4d424c32` | partial |
| plugin-9 | effect-4 | `aRbp` | 1 | `6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d` | `00` | undecoded |
| plugin-10 | effect-4 | `aRbp` | 1 | `6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d` | `00` | undecoded |
| plugin-11 | effect-4 | `sdat` | 16 | `c204e446676401e94333d12ddaa2b0086c0fe931cf2088f717ee22c46840c2ac` | `77777777` | partial |
| plugin-12 | effect-5 | `aRbp` | 1 | `6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d` | `00` | undecoded |
| plugin-13 | effect-5 | `sdat` | 16 | `c204e446676401e94333d12ddaa2b0086c0fe931cf2088f717ee22c46840c2ac` | `77777777` | partial |

