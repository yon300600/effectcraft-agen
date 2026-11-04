#!/bin/sh
# Build the module and run every check that can run on this machine.
#
#   ./run_tests.sh          # build + ABI + pixel checks (needs python3 with wasmtime, numpy; node)
#   ./run_tests.sh --app    # also the in-app check (needs EFFECTCRAFT_CLI, or a built CLI)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PYTHON:-python3}

"$HERE/build.sh"

echo
echo "== ABI conformance (wasmtime) =="
"$PY" "$HERE/tests/check_abi.py"

echo
echo "== pixels against the independent reference =="
"$PY" "$HERE/tests/check_pixels.py"

if [ "${1:-}" = "--app" ]; then
    echo
    echo "== in the application (effectcraft-cli) =="
    "$HERE/tests/app_check.sh"
fi
