#!/usr/bin/env python3
"""Read an `effectcraft.ffx.v2` reconstruction JSON and print the inventory used by ANALYSIS.md.

    tools/analyze.py "/path/JE Cream CC.effectcraft.json" > tables.md

It reads **only** what the reconstruction JSON itself decoded: effect identity, parameter names,
types, values, ranges, options, units, keyframe/expression counts, and the *identity* of opaque
payloads (size + SHA-256 + first bytes). Binary payloads are never parsed, decoded beyond
classification, or used to infer an algorithm - see EFFECTCRAFT_RECONSTRUCTION_RULES.md §B0.
"""
import base64
import hashlib
import json
import sys

SLOTS = {"slider": 1, "angle": 1, "checkbox": 1, "popup": 1, "point": 2, "color": 4}


def fmt(v, width=46):
    if isinstance(v, dict) and "rgba" in v:
        v = v["rgba"]
    s = json.dumps(v) if not isinstance(v, str) else v
    s = s.replace("|", "\\|")
    return s if len(s) <= width else s[: width - 1] + "…"


def main(path):
    d = json.load(open(path))
    print(f"file: `{d['fileName']}` — {d['fileSize']} bytes on disk, {d['fileSize']} bytes of FaFX\n")
    c = d["container"]
    print(f"* container: `{c['fourCC']}` / `{c['formType']}`, {c['endian']}-endian, valid: {c['valid']}")
    print(f"* declared size {c['declaredSize']}, actual end {c['actualEnd']}")
    print(f"* written by After Effects {c['afterEffectsVersion']['major']}.{c['afterEffectsVersion']['minor']}")
    acc = d["accounting"]
    print(f"* {acc['effects']} effects, {acc['editableParameters']} editable parameters "
          f"({acc['decodedParameters']} decoded, {acc['partiallyDecodedParameters']} partial), "
          f"{acc['parameterDescriptors']} descriptors, {acc['keyframes']} keyframes, "
          f"{acc['expressions']} expressions, {acc['unknownChunks']} unknown chunks, "
          f"{acc['totalBinaryRecords']} binary records")
    print()

    print("| # | match name | display name | vendor | suite | parameters |")
    print("|---|---|---|---|---|---|")
    for e in d["effects"]:
        print(f"| {e['order']} | `{e['matchName']}` | {e['displayName']} | {e['vendor']} "
              f"({e['vendorSource']}) | {e['suite']} | {len(e['properties'])} |")
    print()

    for e in d["effects"]:
        print(f"### {e['order']}. `{e['matchName']}` ({e['displayName']})\n")
        print("| parameter | control | type | value | min..max | slider | units | options | notes |")
        print("|---|---|---|---|---|---|---|---|---|")
        for p in e["properties"]:
            notes = []
            if p.get("hidden"):
                notes.append("hidden")
            if p.get("hasKeyframes"):
                notes.append(f"{len(p['keyframes'])} keyframes")
            if p.get("expression"):
                notes.append("expression")
            if p.get("decodeStatus") not in (None, "decoded"):
                notes.append(p["decodeStatus"])
            opts = p.get("options") or []
            print(f"| {p['displayName']} | {p['controlType'] or '—'} | {p['valueType'] or '—'} | "
                  f"{fmt(p['value'], 30)} | {fmt(p['minimum'], 8)}..{fmt(p['maximum'], 8)} | "
                  f"{fmt(p['sliderMinimum'], 6)}..{fmt(p['sliderMaximum'], 6)} | "
                  f"{p['units'] or '—'} | {fmt(opts, 40) if opts else '—'} | "
                  f"{', '.join(notes) or '—'} |")
        print()

    print("### Opaque payloads (identified, never interpreted)\n")
    print("| id | effect | signature | bytes | SHA-256 | first bytes | status |")
    print("|---|---|---|---|---|---|---|")
    for pd in d["pluginData"]:
        raw = base64.b64decode(pd["rawBase64"] or "")
        print(f"| {pd['id']} | {pd['effectId']} | `{pd['signature']}` | {len(raw)} | "
              f"`{hashlib.sha256(raw).hexdigest()}` | `{raw[:4].hex()}` | {pd['decodeStatus']} |")
    print()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/arena-coding-uploads/JE Cream CC.effectcraft.json")
