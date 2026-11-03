#!/bin/sh
# End-to-end check of the WASM kit fixture *inside the real EffectCraft application*, through
# the shipped CLI (same engine, same `effectcraft-plugin` wasmi host, same renderer as the app).
#
#   cargo build -p effectcraft-cli            # or use a release/downloaded binary
#   EFFECTCRAFT_CLI=target/debug/effectcraft-cli tools/wasm-effect-kit/app_check.sh
#
# Stages (pass one to run only it, or none for all):
#   load     the application's own loader accepts the module and its manifest (`effect.plugins.load`)
#   project  comp + solid layer, effect applied, a parameter set, instance inspected
#   render   the effect renders through the real renderer (PNG out), compared with a control
#
# Exit status 0 only when every stage it ran passed. This is the check that turns the kit's
# ABI-level evidence into in-application evidence; `check_host.py` / `check_host.mjs` / `host/`
# remain the pixel-exact checks.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
WASM="$HERE/fixture/ec_gain_blur.wasm"
PLUGIN_ID="org.effectcraft.wasmkit.fixture.gain-blur"
CLI="${EFFECTCRAFT_CLI:-effectcraft-cli}"
OUT="${EFFECTCRAFT_WASM_CHECK_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/effectcraft-wasm-app-check.XXXXXX")}"
# Keep the app's settings, plug-in folder and caches out of the real user profile.
EFFECTCRAFT_CONFIG_DIR="$OUT/config"
export EFFECTCRAFT_CONFIG_DIR
mkdir -p "$OUT"

say() { printf '%s\n' "$*"; }
die() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

command -v "$CLI" >/dev/null 2>&1 || {
    printf 'FAIL: %s not found. Build it with `cargo build -p effectcraft-cli`,\n' "$CLI" >&2
    printf '      or set EFFECTCRAFT_CLI=/path/to/effectcraft-cli.\n' >&2
    exit 1
}
[ -f "$WASM" ] || die "fixture module missing: $WASM (run fixture/build.sh)"

say "cli:    $CLI"
say "wasm:   $WASM"
say "out:    $OUT"

stage_load() {
    say ""
    say "== stage: load (effect.plugins.load through the application's loader) =="
    "$CLI" --empty --json run --commands - >"$OUT/load.json" <<EOF
{"command":"effect.plugins.load","params":{"path":"$WASM"}}
{"command":"effect.plugins.list","params":{}}
EOF
    cat "$OUT/load.json"
    say ""
    python3 - "$OUT/load.json" "$PLUGIN_ID" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
want = sys.argv[2]
steps = doc if isinstance(doc, list) else doc.get("results", doc)
loaded = steps[0]["result"]["loaded"][0]
assert loaded["id"] == want, f"loaded {loaded['id']!r}, expected {want!r}"
assert loaded["api"] == 1, f"api {loaded['api']}"
assert loaded["params"] == 7, f"{loaded['params']} parameters"
listing = steps[1]["result"]
assert listing["wasm"] is True, "this build has no wasm runtime"
ids = [p["id"] for p in listing["plugins"]]
assert want in ids, f"{want} not listed ({ids})"
print(f"PASS load: registered {want} (api {loaded['api']}, {loaded['params']} parameters, wasm runtime available)")
PY
}

stage_project() {
    say ""
    say "== stage: project (comp + solid, plug-in applied, parameter set) =="
    "$CLI" --empty --json run --commands - --save-as "$OUT/with.ecproj" >"$OUT/project.json" <<EOF
{"command":"comp.new","params":{"name":"WasmCheck","width":32,"height":32,"duration":1}}
{"command":"layer.newSolid","params":{"name":"Plate","color":[0.5,0.5,0.5]}}
{"command":"effect.plugins.load","params":{"path":"$WASM"}}
{"command":"effect.apply","params":{"comp":"WasmCheck","layer":"Plate","effect":"$PLUGIN_ID"}}
{"command":"prop.set","params":{"comp":"WasmCheck","layer":"Plate","path":"effects/#1/gain","value":2.0}}
{"command":"props","params":{"comp":"WasmCheck","layer":"Plate"}}
EOF
    cat "$OUT/project.json"
    say ""
    python3 - "$OUT/project.json" "$OUT/with.ecproj" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
steps = doc if isinstance(doc, list) else doc.get("results", doc)
applied = steps[3]["result"]
assert applied, "effect.apply returned nothing"
tree = steps[5]["result"]
flat = json.dumps(tree)
assert "effects/#1/gain" in flat or "gain" in flat, "no gain parameter in the layer's property tree"
print("PASS project: effect applied by id; the instance's parameters are ordinary animatable properties")
PY
    [ -s "$OUT/with.ecproj" ] || die "project was not saved"
    say "PASS project: saved $OUT/with.ecproj"
}

stage_render() {
    say ""
    say "== stage: render (real renderer, PNG out) =="
    mkdir -p "$OUT/with" "$OUT/without"
    "$CLI" --empty --json run --commands - >"$OUT/with.json" <<EOF
{"command":"comp.new","params":{"name":"WasmCheck","width":32,"height":32,"duration":1}}
{"command":"layer.newSolid","params":{"name":"Plate","color":[0.5,0.5,0.5]}}
{"command":"effect.plugins.load","params":{"path":"$WASM"}}
{"command":"effect.apply","params":{"comp":"WasmCheck","layer":"Plate","effect":"$PLUGIN_ID"}}
{"command":"prop.set","params":{"comp":"WasmCheck","layer":"Plate","path":"effects/#1/gain","value":2.0}}
{"command":"renderQueue.add","params":{"comp":"WasmCheck","format":"png","output":"$OUT/with/[#####].png","timeSpan":"comp"}}
{"command":"renderQueue.render","params":{"wait":true}}
EOF
    tail -c 800 "$OUT/with.json"
    say ""
    "$CLI" --empty --json run --commands - >"$OUT/without.json" <<EOF
{"command":"comp.new","params":{"name":"WasmCheck","width":32,"height":32,"duration":1}}
{"command":"layer.newSolid","params":{"name":"Plate","color":[0.5,0.5,0.5]}}
{"command":"renderQueue.add","params":{"comp":"WasmCheck","format":"png","output":"$OUT/without/[#####].png","timeSpan":"comp"}}
{"command":"renderQueue.render","params":{"wait":true}}
EOF
    ls -l "$OUT/with" "$OUT/without" || true
    python3 - "$OUT/with" "$OUT/without" <<'PY'
import glob, os, struct, sys, zlib

def read_png(path):
    """Decode an 8-bit RGB/RGBA non-interlaced PNG (standard library only)."""
    data = open(path, "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos, idat, w = 8, b"", 0
    h, depth, ctype = 0, 8, 6
    while pos < len(data):
        (ln,) = struct.unpack(">I", data[pos:pos + 4])
        typ = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
        elif typ == b"IDAT":
            idat += body
        pos += 12 + ln
    assert depth == 8 and ctype in (2, 6), f"unsupported PNG (depth {depth}, colour type {ctype})"
    ch = 4 if ctype == 6 else 3
    raw = zlib.decompress(idat)
    stride = w * ch
    out, prev = [], bytearray(stride)
    p = 0
    for _ in range(h):
        f = raw[p]; p += 1
        line = bytearray(raw[p:p + stride]); p += stride
        for i in range(stride):
            a = line[i - ch] if i >= ch else 0
            b = prev[i]
            c = prev[i - ch] if i >= ch else 0
            if f == 1:
                line[i] = (line[i] + a) & 0xFF
            elif f == 2:
                line[i] = (line[i] + b) & 0xFF
            elif f == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 0xFF
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out.append(bytes(line))
        prev = line
    return w, h, ch, out

def mean_rgb(folder):
    files = sorted(glob.glob(os.path.join(folder, "*.png")))
    assert files, f"no PNG in {folder}"
    w, h, ch, rows = read_png(files[0])
    tot = [0, 0, 0]
    for row in rows:
        for i in range(0, len(row), ch):
            tot[0] += row[i]; tot[1] += row[i + 1]; tot[2] += row[i + 2]
    n = w * h
    return files[0], (w, h), [round(t / n, 1) for t in tot]

wf, wsize, wmean = mean_rgb(sys.argv[1])
uf, usize, umean = mean_rgb(sys.argv[2])
print(f"with effect:    {os.path.basename(wf)} {wsize} mean RGB {wmean}")
print(f"without effect: {os.path.basename(uf)} {usize} mean RGB {umean}")
assert wsize == usize, "the two renders differ in size"
assert wmean != umean, "the effect did not change the rendered frame"
print("PASS render: the plug-in effect changed the rendered frame through the real renderer")
PY
}

want=${1:-all}
case "$want" in
    all) stage_load; stage_project; stage_render ;;
    load) stage_load ;;
    project) stage_project ;;
    render) stage_render ;;
    *) die "unknown stage '$want' (load|project|render|all)" ;;
esac
say ""
say "app check passed ($want)"
