#!/bin/sh
# Build the fixtures and run every check the sandbox can run.
#
#   ./run_tests.sh            build + wasmtime + node
#   PYTHON=/path ./run_tests.sh
#
# Exit status 0 only when every check passes. The Rust real-host check
# (host/, tools/wasm-effect-kit/README.md) needs cargo and is not run here.
set -eu
cd "$(dirname "$0")"

echo "== build =="
PYTHON="${PYTHON:-}" ./fixture/build.sh

# A Python with wasmtime: $PYTHON, then python3, then a local .venv.
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
    for candidate in python3 .venv/bin/python ../.venv/bin/python ../../.venv/bin/python; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import wasmtime" >/dev/null 2>&1; then
            PY="$candidate"
            break
        fi
    done
fi
if [ -z "$PY" ]; then
    echo "run_tests.sh: no Python with the 'wasmtime' package (pip install wasmtime)" >&2
    exit 1
fi

echo
echo "== ABI conformance (wasmtime) =="
"$PY" fixture/check_host.py

if command -v node >/dev/null 2>&1; then
    echo
    echo "== ABI conformance (Node / V8) =="
    node fixture/check_host.mjs
else
    echo
    echo "node not found: skipping the V8 runtime check" >&2
fi

echo
echo "all checks passed"
