#!/bin/sh
# Build the WASM kit fixtures: real .wasm binaries for the EffectCraft plug-in API v1.
#
# The compiler is Zig's clang frontend (target wasm32-freestanding), because this toolchain
# needs no crates.io/registry access and produces a dependency-free module, which is exactly
# what the plug-in ABI requires (a module with no imports). Where a Rust toolchain is
# available, `rustc` can build the same ABI — see tools/wasm-effect-kit/README.md.
#
# Usage: ./build.sh            (writes ec_gain_blur.wasm and ec_spin.wasm next to this file)
set -eu

cd "$(dirname "$0")"

ZIG="${ZIG:-}"
if [ -z "$ZIG" ]; then
    if command -v zig >/dev/null 2>&1; then
        ZIG="zig"
    else
        # A Python with the `ziglang` wheel (pip install ziglang) can run Zig itself.
        for py in "${PYTHON:-}" python3 python ../.venv/bin/python ../../.venv/bin/python; do
            [ -n "$py" ] || continue
            command -v "$py" >/dev/null 2>&1 || continue
            if "$py" -c "import ziglang" >/dev/null 2>&1; then
                ZIG="$py -m ziglang"
                break
            fi
        done
    fi
fi
if [ -z "$ZIG" ]; then
    echo "build.sh: no WebAssembly compiler found." >&2
    echo "  Install Zig (0.13+), or 'pip install ziglang' in a virtualenv," >&2
    echo "  or set ZIG=/path/to/zig or PYTHON=/path/to/python-with-ziglang." >&2
    exit 1
fi

CC_FLAGS="-target wasm32-freestanding -O2 -ffreestanding -nostdlib -ffp-contract=off"
LINK_FLAGS="-Wl,--no-entry -Wl,--export-memory -Wl,--initial-memory=2097152 -Wl,--max-memory=1073741824 -Wl,--strip-all"

python3 gen_manifest_header.py plugin.json manifest_bytes.h EC_MANIFEST
python3 gen_manifest_header.py plugin_spin.json manifest_bytes_spin.h EC_MANIFEST

echo "cc: $ZIG"
# shellcheck disable=SC2086
$ZIG cc $CC_FLAGS $LINK_FLAGS -o ec_gain_blur.wasm ec_gain_blur.c
# shellcheck disable=SC2086
$ZIG cc $CC_FLAGS $LINK_FLAGS -o ec_spin.wasm ec_spin.c

ls -l ec_gain_blur.wasm ec_spin.wasm
