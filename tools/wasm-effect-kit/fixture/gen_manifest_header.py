#!/usr/bin/env python3
"""Embed a plug-in manifest as a C header, so the module and plugin.json cannot disagree.

Usage: python3 gen_manifest_header.py plugin.json manifest_bytes.h EC_MANIFEST
"""

import json
import sys


def main(argv):
    if len(argv) != 4:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    json_path, header_path, symbol = argv[1], argv[2], argv[3]
    with open(json_path, "rb") as f:
        raw = f.read()
    # Fail loudly rather than embedding a manifest the host would refuse.
    parsed = json.loads(raw)
    if parsed.get("api") != 1:
        print(f"{json_path}: api must be 1", file=sys.stderr)
        return 1
    data = json.dumps(parsed, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    lines = [
        "/* Generated from %s by build.sh — do not edit. */" % json_path,
        "#include <stddef.h>",
        "",
        "static const unsigned char %s[] = {" % symbol,
    ]
    for i in range(0, len(data), 16):
        chunk = data[i : i + 16]
        lines.append("    " + ", ".join("0x%02x" % b for b in chunk) + ",")
    lines.append("};")
    lines.append("")
    lines.append("#define %s_LEN %d" % (symbol, len(data)))
    lines.append("")
    with open(header_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"{header_path}: {len(data)} bytes of manifest from {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
