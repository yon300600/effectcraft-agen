# EffectCraft — effect reconstruction rules (permanent)

These are the standing instructions for every future session that receives an
**`effect_reconstruction.json`** package and is asked to reconstruct the effect it describes as a
real EffectCraft effect. They apply to humans and agents alike, in this repository, on top of
`AGENTS.md` (rules that must never be broken), `CLAUDE.md` (working instructions) and
`CONTRIBUTING.md`. **When documents disagree, `AGENTS.md` wins; when reality disagrees with this
file, reality wins — then fix this file.**

> Read together with:
> `EFFECTCRAFT_ARCHITECTURE_AUDIT.md` (what the app does),
> `EFFECTCRAFT_WASM_INTERFACE.md` (the ABI a module must implement),
> `EFFECTCRAFT_WASM_TOOLCHAIN.md` (how to build and test it here),
> `tools/wasm-effect-kit/` (the working build + conformance harness).

---

## 0. Prime directives

1. **This is the real EffectCraft application.** Never create a replacement app, a parallel
   effect system, a second registry, a second animation system or a second preset format.
2. **Never claim what was not executed.** No "it works", "it is pixel-perfect" or "integrated"
   without the command output that proves it. State what could not be run and why.
3. **Never fabricate**: no placeholder algorithms, no returning the input unchanged, no
   UI-only imitation, no invented keyframes, no invented parameter values, no guessed fields.
4. **Never leave the repository broken.** Existing files are modified only with a clear technical
   reason; functionality is preserved.
5. **Clean room** (`AGENTS.md` §2): work from public documentation and observable *behaviour*.
   Never read, disassemble or copy Adobe code, plug-ins or `.ffx` presets; never copy
   GPL/LGPL/AGPL code; never use Adobe artwork.

---

## 0.1 Conflicts with `AGENTS.md` — resolved here

`AGENTS.md` outranks this file. Where an earlier revision of these rules could be read as
permitting something `AGENTS.md` forbids, the table below states the binding resolution; the
rest of this document has been rewritten to match it.

| Topic | `AGENTS.md` | Risk in an effect-reconstruction workflow | Resolution (binding) |
|---|---|---|---|
| Adobe `.ffx` presets | §2: "Never read or copy Adobe … `.ffx` presets or effect plug-ins; the public Expression Language Reference and Scripting Guide describe *behaviour* only"; `docs/file-format-parity.md` puts `.ffx` outside clean-room scope | A user-supplied `effect_reconstruction.json` often *originates* from such a preset, and "parse every field" could be read as "analyse the format's internals" | Only the **user's own file** is opened, and only as **data about settings**: parameter names, types, values, ranges, and animation metadata. The `.ffx` binary format is never studied, documented, reimplemented or shipped as a reader; the algorithm is never derived from it. |
| Adobe app bundles and plug-in binaries | §2: "Never read, disassemble or copy anything inside Adobe application bundles; file names and listings only" | Extracted packages contain base64 blobs that are compiled plug-in payloads | **Never disassembled, decompiled, emulated, decrypted, deobfuscated, pattern-matched or otherwise analysed.** Opaque chunks are hashed, sized, stored verbatim and reported (see §B0). |
| Assets | §1: every asset open-licensed, with an `.attribution` sidecar and an `ATTRIBUTION.md` row; no Adobe imagery, "inspired" redraws included | Reconstruction bundles may carry icons, LUTs, reference frames | Any non-code file added to the repo needs a sidecar and an index row; Adobe-derived imagery is refused; if the licence is unclear, the file does not go in. |
| Reference material | §1.5: After Effects reference screenshots and notes stay **local** (`plan/aftereffects/`, gitignored) and are never committed, bundled or shipped | Accuracy work wants reference renders | Reference renders and notes from a proprietary host stay **outside the repository** (a gitignored local folder), used only for local comparison. Never committed, attached to a PR, or included in a deliverable ZIP. |
| Build artifacts | Implicitly: no caches, no large generated files | Committing a compiled module | Small deliverable `.wasm` files are allowed (they are the product of the task); generated headers, `target/`, caches and `.pyc` are ignored. |
| CI | "Don't add or change CI in a feature or fix PR" | Needing a runner to compile Rust | Verification jobs are **temporary**, live on the working branch only, and are removed before the change is considered finished; anything permanent goes through the project's own process. |
| Commits | `CONTRIBUTING.md`: one task per commit, `cargo xtask ci` green | Multi-effect batches | One effect per commit; gates run where they can run, and the ones that could not are named in the report — never described as passing. |
| Honesty | `AGENTS.md` "Prove it", "Never crash" | Temptation to call ABI-level evidence "integration" | Verified-outside-the-app and verified-inside-the-app are reported separately (see `EFFECTCRAFT_WASM_VERIFICATION.md`). |

## A. Inspect the complete package

For every uploaded file (and every nested file it references):

1. **Parse the whole JSON.** Do not stop at the first level. Walk objects, arrays and nested
   parameter groups; record the document's top-level keys and their types.
2. **Inventory every effect and parameter**: match name, display name, parameter names, types,
   units, default values, ranges, popup options, group membership, order.
3. **Record identity and provenance**: `id`, match names, plug-in/effect identifiers, version
   fields, host application and version, author/vendor, creation metadata, locale strings.
4. **Identify encoded blobs — nothing more.** Where a field is obviously Base64 (`A`, `data`,
   `chunk`, `bytes`, `payload`, long `[A-Za-z0-9+/=]` strings), decode it **only far enough to
   classify it**: length, SHA-256, and the first bytes' magic. Then stop. Decoding to *classify*
   is allowed; analysing the contents is not (§B0).
   * If it is JSON or another text document describing settings → treat it as data (§B).
   * If it is a compiled module, plug-in payload, resource fork, encrypted or obfuscated data →
     it is **opaque**: record `{field, bytes, sha256, magic, guessed-container}` and preserve it
     verbatim. Do not disassemble, decompile, emulate, decrypt, deobfuscate or pattern-match it.
5. **Preserve unknown binary chunks verbatim**, outside version control where the licence or
   provenance is unknown (`extensions/effects/<id>/import/` with a `.gitignore`, or the raw Base64
   in the analysis document if the bytes must travel with it). Never silently drop data; never
   "clean up" a package; never commit a proprietary binary.
6. **Extract all animation data**: keyframe times, values, interpolation types, in/out eases,
   bezier handles, influences, speeds, holds, roving flags, and the timebase they are expressed
   in (fps, comp duration, sample rate).
7. **Preserve original value types** (int vs float, string vs enum, array vs scalar).
8. **Record what could not be interpreted** in an explicit list, with the raw bytes/fields kept
   alongside. "Unknown and preserved" is an acceptable outcome; "unknown and discarded" is not.

Deliverable of this phase: `extensions/effects/<id>/ANALYSIS.md` — a complete inventory, in
tables, plus the list of uninterpreted fields and any decoded blobs with their format and SHA-256.

## B0. Hard prohibitions: proprietary binaries and `.ffx` data

These prohibitions are absolute. They implement `AGENTS.md` §2 and are not negotiable because a
reconstruction "needs" the information.

**Never reverse-engineer.** No disassembly, decompilation, decompression-inspection,
deobfuscation, decryption, emulation, symbolic execution, string-carving or
differential-probing of any proprietary binary — including compiled plug-ins (`.aex`, `.plugin`,
`.dylib`, `.so`, `.dll`, Mach-O/PE/ELF payloads), encrypted or packed resource sections, and any
binary embedded in a preset package. Tools that do this (objdump, otool, Ghidra, IDA,
strings-on-binaries, `wasm2wat` on a third party's module, and their equivalents) are not applied
to such files.

**Never treat preset data as an algorithm.** `.ffx`-derived and preset-derived data yields
*settings*: effect and parameter identifiers, values, ranges, interpolation and animation
metadata. It never yields the processing algorithm, and it must not be used to infer one
("parameter X is 0.37 at frame 12, therefore the kernel must be …" is not evidence). The algorithm
comes from public documentation, published literature and independent reasoning (§C).

**Never run or embed the proprietary plug-in.** No Adobe application, no Adobe plug-in, no
compatibility layer, no "reference renderer" service. The reconstructed effect has no runtime or
build dependency on proprietary software.

**Never ship what you did not originate.** Opaque chunks stay opaque: hashed, sized, preserved,
and reported as "not interpreted". They are not committed to the repository, not added to a PR,
not bundled into a deliverable ZIP, and not presented as decoded.

**What *is* allowed with a user package:** reading its JSON, recording parameter names, types,
values, ranges and animation metadata, decoding a text/JSON blob to classify it, hashing and
preserving opaque blobs, and reporting what could not be interpreted. That is the whole list.

## B. Understand what the package actually contains

Classify every field into exactly one of:

| Class | What it is | What it may be used for |
|---|---|---|
| Known effect parameters | values the host/plug-in would receive | parameter reconstruction (names, defaults, ranges) |
| Plug-in configuration | which effect, which version, host settings | identifying the *behaviour to reproduce* |
| Host application metadata | comp size, rate, duration, colour depth | defaults, test fixtures |
| Animation data | keyframes and eases | keyframe reconstruction (§F) |
| Private plug-in data | opaque fields a plug-in owns | preserved, not interpreted; never invented |
| Unknown binary chunks | Base64/embedded blobs | preserved; reported |
| Processing algorithm information | mathematical description of the operation | the only legitimate source for the implementation |

**The hard truth:** a preset describes **settings**, not the algorithm. An `.ffx`-style document
contains parameter values and identifiers; it does **not** contain the proprietary processing
code, and it must never be treated as if it did. In this project `.ffx` is explicitly outside
clean-room scope (`AGENTS.md` §2, `docs/file-format-parity.md`); an uploaded package is handled as
*the user's data about settings*, and the algorithm is implemented independently from public
knowledge.

If the package does not contain enough information to reproduce the behaviour, say exactly what
is missing and what the delivered implementation therefore approximates — before writing code.

## C. Independent algorithm development

1. Identify the **visual operation** (blur, sharpening, glow, colour transform, distortion,
   motion, noise, edge detection, compositing, spatial mapping…). Different effects need
   different maths; do not force one technique onto everything.
2. Choose the method from the operation and its parameters, using public image-processing
   literature and public documentation: separable filters, convolution, IIR/Gaussian
   approximations, histogram/curve operations, colour-space transforms, homographies,
   PDE/inpainting, particle systems, optical-flow-style motion, etc.
3. Make it **precise**: write the maths down (kernel, radius rule, boundary handling, colour
   space, premultiplication, rounding, clamp order), because the tests compare against a second
   implementation and against reference renders.
4. Respect EffectCraft's frame conventions: premultiplied RGBA `f32`, `scale` for preview
   resolution, `time` for anything time-varying, and the fact that parameters arrive already
   evaluated for the frame.
5. Forbidden: calling After Effects or any Adobe binary; depending on the original proprietary
   plug-in at runtime; shipping a generic filter and calling it the effect; returning the input.

## D. Real WebAssembly implementation

Implement the effect as a **real module** satisfying `EFFECTCRAFT_WASM_INTERFACE.md`:

* no imports; exports `memory`, `ec_api_version` (=1), `ec_manifest_ptr/len`, `ec_alloc`,
  `ec_render`; deterministic; no clocks, no randomness;
* processes the pixel buffer **in place**; honours `width`, `height` and `scale`;
* parameters read in manifest declaration order from the flattened `f64` block;
* returns `0` on success and a documented non-zero code on invalid input (see the interface doc's
  code table); never traps on user input;
* reuses one buffer (as `examples/plugins/posterize-bands` and the kit fixture do);
* survives the fuel budget (`50M + 20k × pixels` instructions per frame).

Build with the kit (`tools/wasm-effect-kit/fixture/build.sh` as the template) and keep both the
**source** and the **built `.wasm`** in the effect's directory.

## E. Native EffectCraft integration

Use what exists — do not add a loader:

* Loading: **Effect ▸ Load Effect Plug-in…**, `effect.plugins.load {path|folder}`, or copying the
  `.wasm` into `<settings>/Plug-ins`.
* Registration produces an ordinary `EffectSpec`, so the effect appears in Effects & Presets and
  the Effect menu, is applicable by id/name (`effect.apply`), shows **real editable parameters**
  in Effect Controls (sliders, numbers, popups, checkboxes, colours, points, angles), supports
  `effect.reorder`, `effect.toggle`, `effect.remove`, undo/redo, and is saved in `.ecproj`.
* Parameter sets can be shipped as EffectCraft presets. The project's preset format is its own
  JSON (`.ecpreset`, `crates/engine/presets/*.json`, `anim.applyPreset`), applied through
  `crates/engine/src/cmd/anim_presets.rs`. Do **not** invent a new preset format and do not
  emulate Adobe's `.ffx` binary format.
* Verify the lifecycle in the app where possible: apply → edit parameters → keyframe → save →
  reopen → render queue → export.

## F. Animation reconstruction

When the package contains animation:

1. Convert times to the project's exact integer `Tick` (254,016,000,000 per second) using the
   documented timebase; never round to milliseconds.
2. Map value types onto `Value` (`Scalar`, `Vec2`, `Vec3`, `Color`, `Bool`, `Enum`, …).
3. Map interpolation: linear → `Interp::Linear`; hold/constant → `Interp::Hold`; bezier →
   `Interp::Bezier` with `Ease { speed, influence }` per dimension and per side, converting
   speeds to units/second and influences to a fraction of the segment.
4. Preserve incoming and outgoing sides, spatial tangents for spatial parameters, roving flags
   and continuous/auto-bezier flags where the source expresses them.
5. **Never flatten an animated property to a single static value.**
6. If a source concept has no EffectCraft equivalent, implement the honest nearest thing and list
   the difference. Do not silently drop keys.

Presets that add animation go into the project's preset JSON (`set` / `keys` blocks), so they
play back like any other preset.

## G. Accuracy and reference comparison

1. When reference renders are supplied, compare them numerically and visually: per-channel
   absolute error, maximum error, percentage of pixels within tolerance, and difference images.
   State the tolerance definition and the sample set. **Reference renders from a proprietary host
   stay local** (`plan/aftereffects/` or another gitignored folder, per `AGENTS.md` §1.5): they
   are never committed, attached to a PR, or included in a deliverable ZIP. Only *our* renders,
   generated from our own fixtures or openly licensed media, may enter the repository.
2. Classify the result honestly: **exact** (bit-identical or within a stated epsilon),
   **close** (visually indistinguishable, measured error bounded), **approximate** (behaviour
   matches, pixels differ, differences described), **unsupported** (cannot be reproduced from the
   available information; say so).
3. Iterate on the maths until the classification is as good as the available evidence allows, and
   record what was tried.
4. Never write "pixel-identical" without a measured comparison that shows it.

## H. Deliverables

Into the repository, per effect — `extensions/effects/<effect-id>/`:

```
README.md              what it is, exact behaviour, parameters, limitations
ANALYSIS.md            §A/§B inventory (with preserved unknown data)
manifest.json          the parameter schema (source of truth)
src/…                  module source (C, Zig, Rust…), with the maths documented
build.sh               reproducible build → <id>.wasm
<id>.wasm              the built module
tests/                 reference implementation + conformance checks (like the kit's)
presets/               optional .ecpreset files reconstructed from the package
```

Plus, when packaged for delivery: a ZIP containing the compiled `.wasm`, complete source,
manifest, parameter definitions, reconstructed animation data, the native EffectCraft preset,
tests, build instructions, README, test results and known limitations.

The ZIP never contains: proprietary binaries or plug-ins, opaque chunks extracted from a
package, Adobe-derived images/fonts/LUTs, or reference renders made in a proprietary host.

**Deliver results, not explanations.** A reconstruction is finished only when the module runs,
the app loads it, and the tests pass — or when the report says precisely which step failed.

---

## Testing gates (all must be attempted; record what ran)

Report results in two **separate** columns, never merged: **verified outside the application**
(module compiled, ABI conformance in a runtime, maths vs an independent reference) and **verified
inside the application** (the real loader accepted it, the real renderer produced pixels). The kit
that produces the first column and the script that produces the second are described in
`EFFECTCRAFT_WASM_VERIFICATION.md`; a green first column is not evidence for the second.

| Gate | How | Evidence required |
|---|---|---|
| Compilation | `build.sh` | command output, `.wasm` size + SHA-256 |
| Valid module / ABI | kit harness (`check_host.py`, `check_host.mjs`) | pass/fail counts |
| Maths correctness | reference implementation compared **bit-exactly** or with stated tolerance | max error, mismatch count |
| Parameters | defaults, each parameter changes the output as documented, min/max respected | per-parameter checks |
| Sizes | several dimensions incl. odd sizes and a large frame (e.g. 1920×1080) | checks + timing |
| Alpha / premultiplication | alpha preserved, stays 0–1, transparent pixels unchanged | checks |
| Errors | short parameter list, zero-size frame, undersized buffer, runaway loop | codes + "frame unchanged" |
| Reuse / stability | ≥200 renders on one instance, identical output, memory plateau | checks |
| Animation | static, multiple keys, linear + bezier, timebase conversion, per-frame evaluation | script + values |
| Real host | `tools/wasm-effect-kit/host` (`cargo run --release`) | output |
| App integration | load, apply, edit, keyframe, save/reopen, render one frame, export | described steps + results |
| Project gates | `cargo xtask ci` where cargo exists | output |

**A gate that was not run is reported as "not run", never as "passed".**

## Repository conventions

* Effects live in `extensions/effects/<effect-id>/`; documentation of the workflow lives here and
  in the four `EFFECTCRAFT_*.md` files. Do not put generated build output in `crates/`.
* Assets: anything that is not code (icons, images, LUTs, audio, models) needs a `.attribution`
  sidecar and an `ATTRIBUTION.md` row (`AGENTS.md` §1). Do not add Adobe-derived material of any
  kind, including "inspired" redraws.
* Build artifacts: commit the small `.wasm` deliverables the task asks for; ignore generated
  headers, `target/`, and anything large (see each directory's `.gitignore`).
* Code style: `cargo fmt`, `clippy` clean with the project lints; no `unwrap()/panic!/unsafe` in
  non-test code; tests may unwrap.
* One task per commit; a commit message that says what changed and why.

## Git workflow

* Work in the user's fork, on a dedicated branch — the delivered workflow asks for
  `effectcraft/reconstruction-foundation` for the foundation work and
  `effectcraft/effect-<short-id>` for each effect.
* **Exception, this session's harness:** an Arena session's branch is fixed
  (`arena/c29c0251-effectcraft-agen` in this checkout). Create the change there, push that branch,
  and open the pull request from it; do not switch or rename it. Where the repository is used
  outside Arena, use the `effectcraft/…` names above.
* Never commit secrets, tokens, credentials, model weights, caches or large generated artifacts.
* Before finishing: `git diff --check`, review the full diff, run the gates that this environment
  can run, and state which could not.
* Open a pull request; **never merge it automatically**.

## Definition of done (per effect)

- [ ] Package fully parsed; every field classified; unknown data preserved and listed
- [ ] Algorithm independently derived and documented (no Adobe code, no placeholder)
- [ ] Real `.wasm` built from committed source, reproducible build script
- [ ] Conformance checks pass (compilation, ABI, maths, parameters, sizes, alpha, errors, reuse)
- [ ] Animation reconstructed when present — keys, times, interpolation, eases; nothing flattened
- [ ] Effect loads in EffectCraft and renders correctly; parameters are editable and keyframable
- [ ] Accuracy classified with measured evidence against any supplied references
- [ ] README, ANALYSIS, manifest, tests, known limitations written
- [ ] Gates that could not be run are named, with the reason
- [ ] PR opened (not merged), diff reviewed, `git diff --check` clean
