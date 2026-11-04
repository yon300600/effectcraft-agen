#!/bin/sh
# Build the deliverable ZIP: module, source, integration files, preset, tests, documents.
#
#   tools/package.sh        -> dist/je-cream-cc-<version>.zip
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(python3 -c "import json,sys;print(json.load(open('$HERE/src/manifest.json'))['version'])")
NAME="je-cream-cc-$VERSION"
OUT="$HERE/dist"
mkdir -p "$OUT"

[ -f "$HERE/build/je_cream_cc.wasm" ] || (cd "$HERE" && ./build.sh)

STAGE=$(mktemp -d)
mkdir -p "$STAGE/$NAME"
cp -R "$HERE/src" "$HERE/tests" "$HERE/tools" "$HERE/build" "$HERE/build.sh" "$HERE/run_tests.sh" \
      "$HERE/README.md" "$HERE/ANALYSIS.md" "$STAGE/$NAME/"
[ -f "$HERE/TEST-RESULTS.md" ] && cp "$HERE/TEST-RESULTS.md" "$STAGE/$NAME/"
[ -d "$HERE/preset" ] && cp -R "$HERE/preset" "$STAGE/$NAME/" || true
[ -d "$HERE/docs" ] && cp -R "$HERE/docs" "$STAGE/$NAME/" || true
rm -rf "$STAGE/$NAME/tests/__pycache__" "$STAGE/$NAME/src/__pycache__" "$STAGE/$NAME/build/.tmp"

cat > "$STAGE/$NAME/FILES.txt" <<EOF
JE Cream CC (reconstructed) $VERSION - deliverable contents

build/je_cream_cc.wasm          compiled WebAssembly module (plug-in API v1, no imports)
src/je_cream_cc.c               complete source of the processing module
src/manifest.json               plug-in manifest (39 parameters, preset values as defaults)
src/manifest_bytes.h            generated: the manifest the module exports
src/param_index.h               generated: parameter slot indices
src/gen_manifest.py             regenerates the two headers from the manifest
build.sh                        builds the module (Zig/clang, wasm32-freestanding)
run_tests.sh                    build + ABI checks + pixel checks (+ --app for the in-app check)
tests/check_abi.py              34 ABI/format/determinism/limits checks (wasmtime)
tests/reference.py              independent Python implementation of the same maths
tests/check_pixels.py           14 pixel checks: module vs reference, plus V8 parity
tests/check_v8.mjs              the module in V8 (engine independence)
tests/app_check.sh              in-application check through the EffectCraft CLI
tests/render_stills.py          renders the before/after stills through the module
docs/                           before/after stills (JPEG), their source frame, and the
                                .attribution sidecars the repository's assets gate requires
preset/je-cream-cc.preset.json  native EffectCraft animation preset (Apply Animation Preset...)
ANALYSIS.md                     analysis of the supplied JSON and the reconstruction decisions
TEST-RESULTS.md                 what was executed and what it printed
README.md                       overview, usage, accuracy labels, limitations
EOF

( cd "$STAGE" && zip -qr "$OUT/$NAME.zip" "$NAME" )
rm -rf "$STAGE"
ls -l "$OUT/$NAME.zip"
python3 - "$OUT/$NAME.zip" <<'PY'
import hashlib, pathlib, sys, zipfile
p = pathlib.Path(sys.argv[1])
z = zipfile.ZipFile(p)
names = z.namelist()
print(f"{len(names)} entries, {p.stat().st_size} bytes, sha256 {hashlib.sha256(p.read_bytes()).hexdigest()}")
for n in sorted(names):
    print("  " + n)
PY
