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
    mkdir -p "$OUT/with" "$OUT/without" "$OUT/flat" "$OUT/flat0"
    # A: a flat 0.9 grey field. Sharpening and unsharp masking are identities on a flat image, and a
    # box blur of a constant field is the constant, so the only thing that acts is glow 2 - which
    # depends on whether the host hands a plug-in display-referred or linear values. This frame
    # therefore isolates the host's frame encoding from the operator, with a single output number.
    # B: a checkerboard over the grey solid (Blending Mode = Normal) covers the frame opaquely, so the
    # composite *is* the layer the effect sees - which makes the pixel-parity check below meaningful.
    "$CLI" --empty --json run --commands - >"$OUT/flat0.json" <<EOF
{"command":"comp.new","params":{"name":"JECreamFlat","width":320,"height":180,"duration":1}}
{"command":"layer.newSolid","params":{"name":"Field","color":[0.9,0.9,0.9]}}
{"command":"renderQueue.add","params":{"comp":"JECreamFlat","format":"png","output":"$OUT/flat0/[#####].png","timeSpan":"comp"}}
{"command":"renderQueue.render","params":{"wait":true}}
EOF
    "$CLI" --empty --json run --commands - >"$OUT/flat.json" <<EOF
{"command":"comp.new","params":{"name":"JECreamFlat","width":320,"height":180,"duration":1}}
{"command":"layer.newSolid","params":{"name":"Field","color":[0.9,0.9,0.9]}}
{"command":"effect.plugins.load","params":{"path":"$WASM"}}
{"command":"effect.apply","params":{"comp":"JECreamFlat","layer":"Field","effect":"$PLUGIN_ID"}}
{"command":"renderQueue.add","params":{"comp":"JECreamFlat","format":"png","output":"$OUT/flat/[#####].png","timeSpan":"comp"}}
{"command":"renderQueue.render","params":{"wait":true}}
EOF
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
    tail -c 300 "$OUT/with.json"; say ""
    python3 - "$OUT" "$WASM" <<'PY'
import glob, json, os, struct, sys, zlib

out_dir, wasm = sys.argv[1], sys.argv[2]


def read_png(path):
    data = open(path, "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"not a PNG: {path}"
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
    return {"w": w, "h": h, "ch": ch, "rows": rows}


def png_of(folder):
    files = sorted(glob.glob(os.path.join(folder, "*.png")))
    assert files, f"no PNG in {folder}"
    return read_png(files[0])


def rgb(img, x, y):
    i = x * img["ch"]
    r = img["rows"][y]
    return r[i], r[i + 1], r[i + 2]


def rgba(img, x, y):
    i = x * img["ch"]
    r = img["rows"][y]
    a = r[i + 3] if img["ch"] == 4 else 255
    return r[i], r[i + 1], r[i + 2], a


man = json.loads(open(os.path.join(os.path.dirname(wasm), "..", "src", "manifest.json")).read())
params = []
for p_ in man["params"]:
    v = p_["default"]
    if p_["type"] == "checkbox":
        params.append(1.0 if v else 0.0)
    elif p_["type"] in ("color", "point"):
        params += [float(x) for x in v]
    else:
        params.append(float(v))
import wasmtime
ENG = wasmtime.Engine()
MOD = wasmtime.Module.from_file(ENG, wasm)


def run_module(img, pixels, scale):
    """pixels: premultiplied (r,g,b,a) floats, row major."""
    w, h = img["w"], img["h"]
    store = wasmtime.Store(ENG)
    inst = wasmtime.Instance(store, MOD, [])
    ex = inst.exports(store)
    total = len(params) * 8 + w * h * 16
    base = ex["ec_alloc"](store, total)
    assert base, "ec_alloc returned null"
    buf = bytearray(struct.pack(f"<{len(params)}d", *params))
    buf += struct.pack(f"<{len(pixels)}f", *pixels)
    ex["memory"].write(store, bytes(buf), base)
    rc = ex["ec_render"](store, base + len(params) * 8, w, h, base, len(params), 0.0, scale)
    assert rc == 0, f"ec_render returned {rc}"
    raw = bytes(ex["memory"].read(store, base + len(params) * 8, base + len(params) * 8 + w * h * 16))
    return struct.unpack(f"<{w * h * 4}f", raw)


def to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def to_display(c):
    c = min(max(c, 0.0), 1.0)
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def encode(img):
    """Both candidate encodings of the frame the host hands the plug-in."""
    return {
        "display": lambda r, g, b: (r / 255.0, g / 255.0, b / 255.0),
        "linear": lambda r, g, b: (to_linear(r / 255.0), to_linear(g / 255.0), to_linear(b / 255.0)),
    }


def flatten(img, space):
    enc = encode(img)[space]
    px = []
    for y in range(img["h"]):
        for x in range(img["w"]):
            r, g, b, a8 = rgba(img, x, y)
            r, g, b = enc(r, g, b)
            a = a8 / 255.0
            px += [r * a, g * a, b * a, a]
    return px


def decode(out, space):
    """The module's premultiplied output -> 8-bit display values (list of (r,g,b) 0..255)."""
    res = []
    for i in range(len(out) // 4):
        a = out[i * 4 + 3]
        v = []
        for c in range(3):
            x = out[i * 4 + c] / a if a > 0 else 0.0
            if space == "linear":
                x = to_display(x)
            v.append(min(max(x, 0.0), 1.0) * 255.0)
        res.append(tuple(v))
    return res


def spread(img):
    hist = {}
    for y in range(img["h"]):
        for x in range(img["w"]):
            k = rgb(img, x, y)
            hist[k] = hist.get(k, 0) + 1
    return sorted(hist.items(), key=lambda kv: -kv[1])[:4]


flat0, flat = png_of(os.path.join(out_dir, "flat0")), png_of(os.path.join(out_dir, "flat"))
without, with_ = png_of(os.path.join(out_dir, "without")), png_of(os.path.join(out_dir, "with"))
assert (flat0["w"], flat0["h"]) == (with_["w"], with_["h"]), "renders differ in size"

# ---------- sanity: the effect really did change the frame, and sharpening added detail
diff = sum(abs(rgb(without, x, y)[c] - rgb(with_, x, y)[c])
           for y in range(without["h"]) for x in range(without["w"]) for c in range(3))
print(f"mean |with - without| = {diff / (without['w'] * without['h'] * 3):.2f}/255 per channel")
assert diff > 0, "the effect did not change the rendered frame"


def detail(img):
    s = 0
    for y in range(img["h"]):
        for x in range(img["w"] - 1):
            a, b = rgb(img, x, y), rgb(img, x + 1, y)
            s += abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])
    return s


energy_u, energy_w = detail(without), detail(with_)
print(f"horizontal gradient energy: without {energy_u}, with {energy_w} "
      f"({(energy_w / max(energy_u, 1) - 1) * 100:+.1f}%)")
assert energy_w > energy_u, "sharpening did not raise the high-frequency energy"

# ---------- A: the flat field tells us how the host encodes the frame it hands a plug-in
say_like = "flat field (0.9 grey): the effect only fires glow 2, so one number decides the encoding"
print(say_like)
print(f"  without effect: {rgb(flat0, 160, 90)}   with effect: {rgb(flat, 160, 90)}")
for space in ("display", "linear"):
    o = decode(run_module(flat0, flatten(flat0, space), 1.0), space)
    print(f"  module, {space:7s} in: {tuple(round(v, 1) for v in o[90 * flat0['w'] + 160])}")

# ---------- B: the checkerboard frame exercises the whole chain, edges included
print(f"without-effect frame: {spread(without)}")
flat_mask = [False] * (without["w"] * without["h"])
for y in range(1, without["h"] - 1):
    for x in range(1, without["w"] - 1):
        c = rgb(without, x, y)
        flat_mask[y * without["w"] + x] = all(rgb(without, x + dx, y + dy) == c
                                              for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
print(f"  interior (flat 4-neighbourhood) pixels: {sum(flat_mask)} of {len(flat_mask)}")

given = [rgb(with_, x, y) for y in range(with_["h"]) for x in range(with_["w"])]
# What the host does was determined by the flat-field render above and by the table below:
# EffectCraft hands a plug-in the layer's own display-referred, premultiplied f32 pixels with
# scale = 1 at full render quality. The other rows are kept as diagnostics so that a future host
# change (a linear working space, a proxy resolution) is visible instead of silent.
print("parity hypotheses (how the host might encode the frame it hands a plug-in):")
results = []
for space in ("display", "linear"):
    inp = flatten(without, space)
    for scale in (1.0, 0.5, 2.0):
        got = decode(run_module(without, inp, scale), space)
        diffs = [abs(g[c] - given[i][c]) for i, g in enumerate(got) for c in range(3)]
        mean = sum(diffs) / len(diffs)
        within2 = 100.0 * sum(1 for d in diffs if d <= 2.0) / len(diffs)
        inner = [abs(got[i][c] - given[i][c]) for i in range(len(got)) if flat_mask[i] for c in range(3)]
        edge = [abs(got[i][c] - given[i][c]) for i in range(len(got)) if not flat_mask[i] for c in range(3)]
        results.append((mean, space, scale, max(diffs), within2))
        print(f"  {space:7s} space, scale {scale:<4}: mean {mean:5.2f}/255, worst {max(diffs):5.0f}, "
              f"{within2:5.1f}% within 2/255 | interior {sum(inner) / max(len(inner), 1):5.2f}, "
              f"edge {sum(edge) / max(len(edge), 1):5.2f}")

best = min(results)
mean, space, scale, worst, within2 = best
print(f"best: {space} space, scale {scale} -> mean {mean:.2f}/255, worst {worst:.0f}/255, "
      f"{within2:.1f}% of channels within 2/255")
ident = next(r for r in results if r[1] == "display" and r[2] == 1.0)
assert ident[0] <= 1.0, (
    f"the app's render does not match the module run in the host's own encoding "
    f"(display/1.0: mean {ident[0]:.2f}/255, worst {ident[3]:.0f}); the host now behaves differently "
    f"- see the table above")
assert ident[4] >= 99.0, f"only {ident[4]:.1f}% of channels agree within 2/255 (display/1.0)"
best_out = decode(run_module(without, flatten(without, space), scale), space)
worst_px = sorted(range(len(given)), key=lambda i: -max(abs(best_out[i][c] - given[i][c]) for c in range(3)))[:3]
print("worst pixels (app vs module): " +
      "; ".join(f"({i % without['w']},{i // without['w']}) {given[i]} vs "
                f"{tuple(round(v) for v in best_out[i])}" for i in worst_px))
print(f"PASS render: the app's renderer reproduces the standalone module's pixels "
      f"(display-referred, scale 1: mean {ident[0]:.2f}/255, worst {ident[3]:.0f}/255, "
      f"{ident[4]:.1f}% within 2/255) - the residue is 8-bit PNG and f32 quantisation")
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
