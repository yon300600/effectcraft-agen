#!/bin/sh
# Build the JE Cream CC reconstruction module (wasm32-freestanding, no libc, no imports).
#
#   ./build.sh                 # writes build/je_cream_cc.wasm
#   ZIG=/path/to/zig ./build.sh
#
# The compiler is Zig's clang frontend (Zig >= 0.13); any clang with a wasm32 target works too:
#   clang --target=wasm32 -O2 -ffp-contract=off -nostdlib -Wl,--no-entry ...
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
OUT="$HERE/build"
mkdir -p "$OUT"

PY=${PYTHON:-python3}
[ -x /tmp/venv/bin/python ] && [ -z "${PYTHON:-}" ] && PY=/tmp/venv/bin/python
"$PY" "$HERE/src/gen_manifest.py"

if [ -n "${ZIG:-}" ]; then
    set -- "$ZIG" cc
elif "$PY" -c "import ziglang" >/dev/null 2>&1; then
    set -- "$PY" -m ziglang cc
else
    set -- zig cc
fi

"$@" -target wasm32-freestanding -mcpu=mvp+bulk_memory -O2 \
    -ffp-contract=off -fno-math-errno -fno-builtin -nostdlib \
    -Wl,--no-entry -Wl,--initial-memory=2097152 -Wl,--export-memory \
    -Wl,--strip-all \
    -o "$OUT/je_cream_cc.wasm" "$HERE/src/je_cream_cc.c"

ls -l "$OUT/je_cream_cc.wasm"
"$PY" - "$OUT/je_cream_cc.wasm" <<'PY'
import hashlib, sys, pathlib
b = pathlib.Path(sys.argv[1]).read_bytes()
print(f"sha256 {hashlib.sha256(b).hexdigest()}  {len(b)} bytes")
assert b[:4] == b"\0asm", "not a wasm module"
PY
