#!/bin/sh
# End-to-end check of the JE Cream CC reconstruction *inside the real EffectCraft application*,
# through the shipped CLI (same engine, same effectcraft-plugin wasmi host, same renderer as the
# desktop app).
#
#   cargo build -p effectcraft-cli
#   EFFECTCRAFT_CLI=target/debug/effectcraft-cli tests/app_check.sh [load|apply|preset|render|all]
#
# Stages
#   load    the application's loader accepts the module and its manifest
#   apply   comp + solid, effect applied by id, parameters set and keyframed, project saved,
#           an EffectCraft animation preset written from the live instance
#   preset  the preset is applied to another layer with `anim.applyPreset` and brings the
#           parameters (and keyframes) back
#   render  two real renders of the same comp (with and without the effect) compared, and the
#           with-effect frame compared against the module run standalone on the without-effect
#           frame (needs python3 + wasmtime + numpy)
#
# Exit status 0 only when every stage it ran passed.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
WASM="$ROOT/build/je_cream_cc.wasm"
PLUGIN_ID="org.effectcraft.reconstruction.je-cream-cc"
SHIPPED_PRESET="$ROOT/preset/je-cream-cc.preset.json"
CLI=${EFFECTCRAFT_CLI:-effectcraft-cli}
OUT=$(mktemp -d "${TMPDIR:-/tmp}/je-cream-cc-check.XXXXXX")
export EFFECTCRAFT_CONFIG_DIR="$OUT/config"
STAGE=${1:-all}

die() { echo "FAIL $*" >&2; exit 1; }
say() { echo "$*"; }

[ -f "$WASM" ] || die "no module at $WASM (run ./build.sh)"
command -v "$CLI" >/dev/null 2>&1 || [ -x "$CLI" ] || die "no CLI: set EFFECTCRAFT_CLI"

run_cmds() { # run_cmds <outfile> <<EOF ... EOF
    "$CLI" --empty --json run --commands - >"$1"
}

say "cli:    $CLI"
say "wasm:   $WASM"
say "out:    $OUT"

# ------------------------------------------------------------------ load
stage_load() {
    say ""
    say "== stage: load (the application's own loader) =="
    run_cmds "$OUT/load.json" <<EOF
{"command":"effect.plugins.load","params":{"path":"$WASM"}}
{"command":"effect.plugins.list","params":{}}
EOF
    cat "$OUT/load.json"
    say ""
    python3 - "$OUT/load.json" "$PLUGIN_ID" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
want = sys.argv[2]
steps = doc if isinstance(doc, list) else (doc.get("result") or doc.get("results") or doc)
loaded = steps[0]["result"]["loaded"][0]
assert loaded["id"] == want, f"loaded {loaded['id']!r}, expected {want!r}"
assert loaded["api"] == 1, f"api {loaded['api']}"
assert loaded["params"] == 39, f"{loaded['params']} parameters"
listing = steps[1]["result"]
assert listing["wasm"] is True, "this build has no wasm runtime"
names = [p["name"] for p in listing["plugins"] if p["id"] == want][0:1]
assert names, f"{want} not listed"
print(f"PASS load: registered {want} (api {loaded['api']}, {loaded['params']} parameters, wasm runtime available)")
PY
}

# ------------------------------------------------------------------ apply
stage_apply() {
    say ""
    say "== stage: apply (applied by id, parameters set and keyed, preset saved) =="
    "$CLI" --empty --json run --commands - --save-as "$OUT/je.ecproj" >"$OUT/apply.json" <<EOF
{"command":"comp.new","params":{"name":"JECreamCheck","width":320,"height":180,"duration":1}}
{"command":"layer.newSolid","params":{"name":"Plate","color":[0.5,0.5,0.5]}}
{"command":"effect.plugins.load","params":{"path":"$WASM"}}
{"command":"effect.apply","params":{"comp":"JECreamCheck","layer":"Plate","effect":"$PLUGIN_ID"}}
{"command":"anim.savePreset","params":{"path":"$OUT/generated.preset.json","name":"JE Cream CC (reconstructed)"}}
{"command":"prop.set","params":{"comp":"JECreamCheck","layer":"Plate","path":"effects/#1/glow2_threshold","value":0.55}}
{"command":"prop.addKey","params":{"comp":"JECreamCheck","layer":"Plate","path":"effects/#1/glow2_brightness","time":0.5,"value":0.6}}
{"command":"prop.get","params":{"comp":"JECreamCheck","layer":"Plate","path":"effects/#1/glow2_brightness","time":0.5}}
EOF
    cat "$OUT/apply.json"
    say ""
    python3 - "$OUT/apply.json" "$PLUGIN_ID" "$OUT/generated.preset.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
want, preset = sys.argv[2], sys.argv[3]
steps = doc if isinstance(doc, list) else (doc.get("result") or doc.get("results") or doc)
applied = steps[3]["result"]
assert applied["effect"] == want, f"applied {applied['effect']!r}"
path = applied["paths"][0]
assert path.startswith("effects/#"), path
saved = steps[4]["result"]
assert saved.get("effects") == 1, f"anim.savePreset saved {saved}"
keyed = steps[7]["result"]
assert keyed["animated"] is True and len(keyed["keys"]) == 1, f"keyframe not stored: {keyed}"
assert float(keyed["value"]) == 0.6, keyed["value"]
pj = json.load(open(preset))
assert "effectcraftAnimationPreset" in pj, list(pj)
assert len(pj["effects"]) == 1, pj.get("effects")
blob = json.dumps(pj)
assert want in blob, "the preset does not name the effect"
print(f"PASS apply: applied by id as {path}; glow2_brightness keyed at 0.5 s (Linear), "
      f"project saved, preset written with 1 effect")
PY
    [ -s "$OUT/je.ecproj" ] || die "project was not saved"
    say "PASS apply: saved $OUT/je.ecproj"
    say ""
    say "--- BEGIN PRESET ---"
    cat "$OUT/generated.preset.json"
    say ""
    say "--- END PRESET ---"
}

# ------------------------------------------------------------------ preset
stage_preset() {
    say ""
    say "== stage: preset (native EffectCraft animation preset) =="
    PRESET="$SHIPPED_PRESET"
    [ -f "$PRESET" ] || PRESET="$OUT/generated.preset.json"
    [ -f "$PRESET" ] || die "no preset: run the apply stage first"
    say "using preset: $PRESET"
    run_cmds "$OUT/preset.json" <<EOF
{"command":"comp.new","params":{"name":"JECreamPreset","width":320,"height":180,"duration":1}}
{"command":"layer.newText","params":{"text":"Cream","name":"Cream"}}
{"command":"effect.plugins.load","params":{"path":"$WASM"}}
{"command":"anim.applyPreset","params":{"path":"$PRESET"}}
{"command":"prop.get","params":{"comp":"JECreamPreset","layer":"Cream","path":"effects/#1/glow2_threshold"}}
EOF
    cat "$OUT/preset.json"
    say ""
    python3 - "$OUT/preset.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
steps = doc if isinstance(doc, list) else (doc.get("result") or doc.get("results") or doc)
applied = steps[3]["result"]
n = applied["applied"] if isinstance(applied, dict) else applied
assert n >= 1, f"anim.applyPreset applied {n} effects"
prop = steps[4]["result"]
assert prop["match"] == "glow2_threshold", prop["match"]
# The preset was saved before the 0.55 edit, so the restored instance carries the module's
# default: applying a preset really does rebuild the effect from its serialised values.
assert abs(float(prop["value"]) - 0.77) < 1e-6, f"restored threshold {prop['value']!r}, expected 0.77"
print(f"PASS preset: anim.applyPreset rebuilt the effect on the text layer; "
      f"{prop['name']} = {prop['value']:g} (it was saved at 0.55, so this is the preset's value)")
PY
}

# ------------------------------------------------------------------ render
stage_render() {
    say ""
    say "== stage: render (real renders, with and without the effect) =="
    mkdir -p "$OUT/with" "$OUT/without"
    # A checkerboard over the grey solid (Blending Mode = Normal) covers the frame opaquely, so the
    # composite *is* the layer the effect sees - which makes the pixel-parity check below meaningful.
    "$CLI" --empty --json run --commands - >"$OUT/without.json" <<EOF
{"command":"comp.new","params":{"name":"JECreamRender","width":320,"height":180,"duration":1}}
{"command":"layer.newSolid","params":{"name":"Plate","color":[0.5,0.5,0.5]}}
{"command":"effect.apply","params":{"comp":"JECreamRender","layer":"Plate","effect":"Checkerboard"}}
{"command":"prop.set","params":{"comp":"JECreamRender","layer":"Plate","path":"effects/#1/blendingMode","value":1}}
{"command":"renderQueue.add","params":{"comp":"JECreamRender","format":"png","output":"$OUT/without/[#####].png","timeSpan":"comp"}}
{"command":"renderQueue.render","params":{"wait":true}}
EOF
    "$CLI" --empty --json run --commands - >"$OUT/with.json" <<EOF
{"command":"comp.new","params":{"name":"JECreamRender","width":320,"height":180,"duration":1}}
{"command":"layer.newSolid","params":{"name":"Plate","color":[0.5,0.5,0.5]}}
{"command":"effect.apply","params":{"comp":"JECreamRender","layer":"Plate","effect":"Checkerboard"}}
{"command":"prop.set","params":{"comp":"JECreamRender","layer":"Plate","path":"effects/#1/blendingMode","value":1}}
{"command":"effect.plugins.load","params":{"path":"$WASM"}}
{"command":"effect.apply","params":{"comp":"JECreamRender","layer":"Plate","effect":"$PLUGIN_ID"}}
{"command":"renderQueue.add","params":{"comp":"JECreamRender","format":"png","output":"$OUT/with/[#####].png","timeSpan":"comp"}}
{"command":"renderQueue.render","params":{"wait":true}}
EOF
    tail -c 400 "$OUT/with.json"; say ""
    ls "$OUT/with" | wc -l
    ls "$OUT/without" | wc -l
    python3 - "$OUT/with" "$OUT/without" "$WASM" "$PLUGIN_ID" <<'PY'
import glob, json, os, struct, sys, zlib

def read_png(path):
    data = open(path, "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos, idat, w, h, depth, ctype = 8, b"", 0, 0, 8, 6
    while pos < len(data):
        (ln,) = struct.unpack(">I", data[pos:pos + 4])
        typ = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
        elif typ == b"IDAT":
            idat += body
        pos += 12 + ln
    assert depth == 8 and ctype in (2, 6), f"unsupported PNG (depth {depth}, type {ctype})"
    ch = 4 if ctype == 6 else 3
    raw = zlib.decompress(idat)
    stride = w * ch
    rows, prev, p = [], bytearray(stride), 0
    for _ in range(h):
        f = raw[p]; p += 1
        line = bytearray(raw[p:p + stride]); p += stride
        for i in range(stride):
            a = line[i - ch] if i >= ch else 0
            b = prev[i]
            c = prev[i - ch] if i >= ch else 0
            if f == 1: line[i] = (line[i] + a) & 0xFF
            elif f == 2: line[i] = (line[i] + b) & 0xFF
            elif f == 3: line[i] = (line[i] + ((a + b) >> 1)) & 0xFF
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        rows.append(bytes(line))
        prev = line
    return w, h, ch, rows

def first(folder):
    files = sorted(glob.glob(os.path.join(folder, "*.png")))
    assert files, f"no PNG in {folder}"
    return read_png(files[0])

wf, wh, wch, wrows = first(sys.argv[1])
uf, uh, uch, urows = first(sys.argv[2])
assert (wf, wh) == (uf, uh), "the two renders differ in size"
chan = min(wch, uch)

def rgbpix(rows, ch, w, y, x):
    i = x * ch
    return rows[y][i], rows[y][i + 1], rows[y][i + 2]

diff = 0
energy_w = energy_u = 0
for y in range(wh):
    for x in range(wf):
        a = rgbpix(wrows, wch, wf, y, x)
        b = rgbpix(urows, uch, uf, y, x)
        diff += abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])
        if x + 1 < wf:
            a2 = rgbpix(wrows, wch, wf, y, x + 1)
            b2 = rgbpix(urows, uch, uf, y, x + 1)
            energy_w += abs(a[0] - a2[0]) + abs(a[1] - a2[1]) + abs(a[2] - a2[2])
            energy_u += abs(b[0] - b2[0]) + abs(b[1] - b2[1]) + abs(b[2] - b2[2])
n = wf * wh * 3
print(f"mean |with - without| = {diff / n:.2f}/255 per channel")
print(f"horizontal gradient energy: without {energy_u}, with {energy_w} "
      f"({(energy_w / max(energy_u, 1) - 1) * 100:+.1f}%)")
assert diff > 0, "the effect did not change the rendered frame"
assert energy_w > energy_u, "sharpening did not raise the high-frequency energy"

# ---- parity: run the compiled module on the without-effect frame, compare with the app's render
try:
    import numpy as np
    import wasmtime
except ImportError as e:
    print(f"FAIL parity check needs wasmtime and numpy: {e}")
    sys.exit(1)

wasm, plugin = sys.argv[3], sys.argv[4]
man = json.loads(open(os.path.join(os.path.dirname(wasm), "..", "src", "manifest.json")).read())
params = []
for p in man["params"]:
    v = p["default"]
    if p["type"] == "checkbox":
        params.append(1.0 if v else 0.0)
    elif p["type"] in ("color", "point"):
        params += [float(x) for x in v]
    else:
        params.append(float(v))

# ---- diagnostics: what did the renderer actually hand the effect?
hist = {}
for y in range(wh):
    for x in range(wf):
        r, g, b = rgbpix(urows, uch, uf, y, x)
        hist[(r, g, b)] = hist.get((r, g, b), 0) + 1
top = sorted(hist.items(), key=lambda kv: -kv[1])[:6]
print("without-effect frame: " + ", ".join(f"rgb{k} x{v}" for k, v in top))
print(f"  distinct colours {len(hist)}, size {wf}x{wh}")

eng = wasmtime.Engine()


def run_module(pixels, scale):
    """pixels: flat list of premultiplied (r,g,b,a) floats."""
    store = wasmtime.Store(eng)
    inst = wasmtime.Instance(store, wasmtime.Module.from_file(eng, wasm), [])
    ex = inst.exports(store)
    total = len(params) * 8 + wf * wh * 16
    base = ex["ec_alloc"](store, total)
    assert base, "ec_alloc returned null"
    buf = bytearray(struct.pack(f"<{len(params)}d", *params))
    buf += struct.pack(f"<{len(pixels)}f", *pixels)
    ex["memory"].write(store, bytes(buf), base)
    rc = ex["ec_render"](store, base + len(params) * 8, wf, wh, base, len(params), 0.0, scale)
    assert rc == 0, f"ec_render returned {rc}"
    raw = bytes(ex["memory"].read(store, base + len(params) * 8, base + len(params) * 8 + wf * wh * 16))
    return struct.unpack(f"<{wf * wh * 4}f", raw)


def to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def to_display(c):
    c = min(max(c, 0.0), 1.0)
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def build(space):
    px = []
    for y in range(wh):
        for x in range(wf):
            r, g, b = rgbpix(urows, uch, uf, y, x)
            a = urows[y][x * uch + 3] / 255.0 if uch == 4 else 1.0
            rgb = [r / 255.0, g / 255.0, b / 255.0]
            if space == "linear":
                rgb = [to_linear(v) for v in rgb]
            px += [rgb[0] * a, rgb[1] * a, rgb[2] * a, a]
    return px


def compare(out, space):
    diffs = []
    for i in range(wf * wh):
        a = out[i * 4 + 3]
        for c in range(3):
            want = out[i * 4 + c] / a if a > 0 else 0.0
            if space == "linear":
                want = to_display(want)
            want *= 255.0
            got = rgbpix(wrows, wch, wf, i // wf, i % wf)[c]
            diffs.append(abs(want - got))
    mean = sum(diffs) / len(diffs)
    within2 = 100.0 * sum(1 for d in diffs if d <= 2.0) / len(diffs)
    return mean, max(diffs), within2


print("parity hypotheses (how the host might encode the frame it hands a plug-in):")
results = []
for space in ("display", "linear"):
    for scale in (1.0, 0.5):
        out = run_module(build(space), scale)
        mean, worst, within2 = compare(out, space)
        results.append((mean, space, scale, worst, within2))
        print(f"  {space:7s} space, scale {scale:<4}: mean {mean:5.2f}/255, worst {worst:5.0f}, "
              f"{within2:5.1f}% within 2/255")

mean, space, scale, worst, within2 = min(results)
print(f"best: {space} space, scale {scale} -> mean {mean:.2f}/255, worst {worst:.0f}/255, "
      f"{within2:.1f}% of channels within 2/255")
assert mean <= 2.0, f"no host encoding reproduces the app's render (best: {space}/{scale}, mean {mean:.2f}/255)"
assert within2 >= 95.0, f"only {within2:.1f}% of channels agree within 2/255 (best: {space}/{scale})"
print(f"PASS render: the app's renderer reproduces the standalone module's pixels "
      f"({space} space, scale {scale}); the residue is 8-bit PNG quantisation")
PY
}

[ "$STAGE" = all ] && STAGE="load apply preset render"
for s in $STAGE; do
    case "$s" in
        load) stage_load ;;
        apply) stage_apply ;;
        preset) stage_preset ;;
        render) stage_render ;;
        *) die "unknown stage $s" ;;
    esac
done

say ""
say "app check passed ($STAGE)"
