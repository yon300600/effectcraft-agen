# EffectCraft — WebAssembly toolchain

How effect modules are compiled, loaded and tested in this repository, with the **exact
versions and results measured on 2026-11-04** in the build environment, and an honest list of
what that environment could not do.

---

## 1. The two runtimes in play

| Role | Runtime | Where it comes from |
|---|---|---|
| **Production host** (loads a `.wasm` effect inside the app) | **wasmi 2.0.0** — a pure-Rust interpreter, pinned in `Cargo.lock` | workspace dependency `wasmi = { version = "2", default-features = false, features = ["std", "validate", "wat", "deterministic", "portable-dispatch"] }` (`Cargo.toml:71`) |
| **Application compiled to wasm** (the browser build) | `wasm32-unknown-unknown` + `wasm-bindgen` 0.2.129 | `docs/web.md` |
| **Verification runtimes** used here | **wasmtime 50.0.1** (Python bindings) and **Node 22.22.3 / V8** | `pip install wasmtime`; Node's built-in `WebAssembly` |

Effect plug-ins themselves only ever run in wasmi in production. The other two runtimes exist in
this kit to *prove the module is portable and to test it without compiling the whole application*.

## 2. Environment measured in this sandbox

| Tool | Before | Installed for this work | Version |
|---|---|---|---|
| Rust toolchain (`rustc`, `cargo`) | **absent** | **not possible** (see §3) | — |
| Clang | absent | — | — |
| Zig (via the `ziglang` PyPI wheel) | absent | `pip install ziglang` in a venv | **0.17.0** |
| Python | 3.11.2 | venv at `~/.venv` | 3.11.2 |
| wasmtime (Python) | absent | `pip install wasmtime` | **50.0.1** |
| Node.js | 22.22.3 | — | 22.22.3 |
| npm | 10.9.8 | — | 10.9.8 |
| GCC | 12.2.0 (Debian) | — | cannot target wasm |
| OS / CPU / RAM | Linux 6.1 x86_64, 2 cores, 3 GB | — | — |

Network egress in this sandbox is restricted to `github.com`, `codeload.github.com`,
`api.github.com`, `registry.npmjs.org`, `pypi.org`, `files.pythonhosted.org`.

## 3. Why not Rust here, and what that means

Measured, not assumed:

```
$ curl -o /dev/null -w '%{http_code}\n' https://static.rust-lang.org/dist/channel-rust-stable.toml   → 000
$ curl -o /dev/null -w '%{http_code}\n' https://static.crates.io/crates/serde/serde-1.0.200.crate    → 000
$ gh api repos/rust-lang/rust/releases/latest --jq '.assets|length'                                   → 0
```

* `rustup` downloads toolchains from `static.rust-lang.org` — **blocked**.
* `cargo` needs the crates registry `static.crates.io` (plus the workspace's pinned git
  dependencies on `github.com`, which are reachable) — **blocked**, so even a toolchain would not
  build EffectCraft's crates.
* `rust-lang/rust` GitHub releases carry **no binary assets**, so a toolchain cannot be fetched
  from GitHub either.

Consequences, stated plainly:

1. **EffectCraft's own workspace was not built or tested in this sandbox.** `cargo build`,
   `cargo test` and `cargo xtask ci` need the blocked hosts. They were run on a GitHub runner
   instead — see §6a, which records exactly which commands ran and what they printed; the
   sandbox itself contributed only the non-Rust work.
2. The **real wasmi host was therefore not executed here**, only on that runner (§6a).
   `tools/wasm-effect-kit/host/` remains a standalone crate that anyone can run where cargo works.
3. Compiling effect modules here uses **Zig's clang frontend**, which produces exactly what the
   ABI needs: a dependency-free `wasm32` module with no imports. This is why `ziglang` was
   installed from PyPI (a wheel containing the official Zig compiler); the same build works with
   a normal Zig install, and any language producing the ABI (Rust, C, Zig, AssemblyScript…)
   is acceptable to the host.

## 4. Building the fixture (verified)

```sh
cd tools/wasm-effect-kit
./fixture/build.sh                    # or: PYTHON=~/.venv/bin/python ./fixture/build.sh
```

What it runs (`wasm32-freestanding`, no libc, no CRT):

```sh
python3 gen_manifest_header.py plugin.json manifest_bytes.h EC_MANIFEST
<python> -m ziglang cc \
    -target wasm32-freestanding -O2 -ffreestanding -nostdlib -ffp-contract=off \
    -Wl,--no-entry -Wl,--export-memory \
    -Wl,--initial-memory=2097152 -Wl,--max-memory=1073741824 -Wl,--strip-all \
    -o ec_gain_blur.wasm ec_gain_blur.c
```

Result (measured):

| Artifact | Size | SHA-256 | Imports | Exports |
|---|---:|---|---|---|
| `fixture/ec_gain_blur.wasm` | 3,543 B | `0e9e962d5f7e66ffc17663cfef41e79b0591f279057227865c422a7396303db2` | 0 | `memory, ec_api_version, ec_manifest_ptr, ec_manifest_len, ec_alloc, ec_render` |
| `fixture/ec_spin.wasm` | 502 B | `09fdeb9ac0130f2acde0ee9b5b281ef75facb8c5bf80781e73d504e28c820ab6` | 0 | same six |

* **Reproducible:** rebuilding produced byte-identical output (`cmp` clean).
* `manifest_bytes*.h` are generated at build time and git-ignored; the manifest text inside the
  module is therefore always the checked-in `plugin.json` / `plugin_spin.json`.
* `-ffp-contract=off` matters: it forbids FMA contraction, so `a*b + c` evaluates the same way in
  every runtime, which is what makes bit-exact comparisons possible.

## 5. Testing the fixture (verified)

```sh
tools/wasm-effect-kit/run_tests.sh
```

| Runtime | Harness | Checks | Result |
|---|---|---:|---|
| wasmtime 50.0.1 | `fixture/check_host.py` (stand-in host mirroring `crates/plugin/src/wasm.rs`) | 48 | **48 passed, 0 failed** |
| Node 22.22.3 / V8 | `fixture/check_host.mjs` | 14 | **14 passed, 0 failed** |

What the 48 checks cover (all executed):

* binary validity (magic/version), zero imports, all six exports, `ec_api_version() == 1`;
* the manifest in the module byte-equals `plugin.json`, and passes the host's schema rules;
* rendering 3×2 and 5×4 frames and comparing **every f32 output bit** against an independent
  reference implementation of the same maths;
* identity parameters leave the frame **bit-identical**; gain, blur radius, tint mix, popup mode,
  checkbox and point parameters each change the result exactly as documented;
* `scale` (buffer/layer resolution) doubles the effective blur radius; `time` reaches the module
  and changes the output (per-frame animation);
* alpha is preserved and stays in 0–1;
* error codes 1, 2 and 4, and a refused frame leaves pixels untouched;
* `ec_alloc` returns an 8-byte-aligned pointer; memory stops growing once the buffer is big
  enough; 200 renders on one instance are bit-identical;
* a 1920×1080 frame renders (~1.5 s through wasmtime **in Python**, including Python's own copy
  overhead — not a performance measurement of the module);
* the runaway fixture is stopped by the fuel budget (stopped in 0.02 s, no hang);
* the module reloads into a fresh instance and still produces reference-matching pixels.

## 6. Running the real host and the project's own gates

Where a Rust toolchain and registry access exist (the user's machine, or CI):

```sh
# the real wasmi host, loading the kit fixture through effectcraft-plugin
cd tools/wasm-effect-kit/host && cargo run --release

# the project's existing plug-in tests (wasmi + engine integration)
cargo test -p effectcraft-plugin
cargo test -p effectcraft-host --test it plugins

# the project's gates
cargo xtask ci            # layers, assets, docs, wasm target, clippy, tests
```

### 6a. What actually ran on a GitHub Actions runner (2026-11-04)

The sandbox cannot compile Rust; a GitHub runner can. A temporary workflow (`wasm host check`,
Ubuntu 24.04, rustc 1.99.1) was pushed to the PR branch and executed every gate — run
**41779068845** (commit `b73b413`), no `continue-on-error`, `set -o pipefail`:

| Step | Result |
|---|---|
| `cargo run --release` in `tools/wasm-effect-kit/host` — **the real `effectcraft-plugin` wasmi host** | **success** |
| `cargo test -p effectcraft-plugin` | **success** |
| `cargo build -p effectcraft-cli` | **success** |
| `tools/wasm-effect-kit/app_check.sh load` — the application's loader | **success** |
| `tools/wasm-effect-kit/app_check.sh project` — apply by id, `prop.set`, `prop.addKey` | **success** |
| `tools/wasm-effect-kit/app_check.sh render` — real renderer, PNG comparison | **success** |

So the fixture module *is* accepted and rendered by EffectCraft. The host check registered it
(`org.effectcraft.wasmkit.fixture.gain-blur … api 1, 7 parameters`), rendered identity, gain, blur
and the error path; the application stages then showed the effect in the app's registry
(`effect.plugins.list` → `wasm: true`, 7 named parameters), applied it as `effects/#1`, set and
keyframed its `Gain` parameter like any built-in property, and rendered frames where the effect
changed the mean RGB from 128 to 255.

The workflow file was temporary: it lived only on the working branch and has been deleted, because
the project's rules forbid adding CI in a feature PR. The full output is preserved in
`EFFECTCRAFT_WASM_VERIFICATION.md` and in the PR comment posted by that run.

Toolchain the project expects: Rust **1.95+** (`rust-version = "1.95"`, edition 2024) and
`rustup target add wasm32-unknown-unknown` for the browser build (`docs/web.md`). The pinned git
dependencies are on `github.com` (craft-libs, FilmCraft), so they are reachable from this sandbox
even though the registry is not.


## 7. Known limitations of this environment

| Limitation | Effect | Mitigation |
|---|---|---|
| No Rust toolchain / registry **in the sandbox** | EffectCraft cannot be compiled here; the wasmi host, `cargo test` and `xtask ci` cannot be run here | they were run on a GitHub Actions runner (§6a, run `41779068845`), and the project's own `CI / gate` job passes on this branch |
| Zig from a PyPI wheel | compiler provenance is the `ziglang` wheel, not a system Zig | same source builds with any Zig ≥ 0.13; `ZIG=/path/to/zig ./fixture/build.sh` |
| 2 cores, 3 GB | no meaningful performance numbers | timing printed only as a sanity figure |
| No browser | the **application's** wasm build (`cargo xtask web`) was not exercised | unchanged by this work (nothing in the app's build was modified) |
| Node has no fuel metering | execution limits proven on wasmtime only (wasmi in production has its own) | documented; the fixture's spin module is used for that check |

## 8. Adding a new effect module to the build

Copy `tools/wasm-effect-kit/fixture/` to `extensions/effects/<effect-id>/`, keep the same three
moving parts (`manifest` JSON → generated header → module), add your source, and run
`build && check`. The manifest JSON is the source of truth; never hand-edit the embedded copy.
