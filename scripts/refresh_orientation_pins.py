#!/usr/bin/env python3
"""Re-pin every ``<key>.sha256`` in docs/LLM_ORIENTATION.toon to the current
bytes of its ``<key>.path`` file. Run after editing any pinned source."""
from __future__ import annotations

import hashlib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(ROOT, "docs", "LLM_ORIENTATION.toon")
PATH_RE = re.compile(r"^fact (?P<key>\S+)\.path=(?P<path>.+)$")
SHA_RE = re.compile(r"^fact (?P<key>\S+)\.sha256=(?P<sha>[0-9a-f]{64})$")


def refresh(pack: str = PACK, root: str = ROOT) -> int:
    with open(pack, encoding="utf-8") as handle:
        lines = handle.read().splitlines(keepends=True)
    paths = {}
    for line in lines:
        match = PATH_RE.match(line.rstrip("\n"))
        if match:
            paths[match.group("key")] = match.group("path").strip()
    changed = 0
    for index, line in enumerate(lines):
        match = SHA_RE.match(line.rstrip("\n"))
        if not match or match.group("key") not in paths:
            continue
        with open(os.path.join(root, paths[match.group("key")]), "rb") as source:
            digest = hashlib.sha256(source.read()).hexdigest()
        if digest != match.group("sha"):
            lines[index] = f"fact {match.group('key')}.sha256={digest}\n"
            changed += 1
    with open(pack, "w", encoding="utf-8") as handle:
        handle.writelines(lines)
    return changed


if __name__ == "__main__":
    print(f"re-pinned {refresh()} digest(s)")
    sys.exit(0)
