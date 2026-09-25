#!/usr/bin/env python3
"""Drift gate for TOON-CONTRACT.md + fixtures/toon-golden/ (issue #149).

This repo is the *canonical host* of the contract (mirrors the existing
pattern for YOOL_TUPLE_HAMT.md, per AGENTS.md). This script does not vendor
into or verify the other ecosystem repos' copies — that is out of scope
here (see TOON-CONTRACT.md §8, "Cross-repo adoption").

What it does check, locally: that the contract text and the golden corpus
have not drifted from the committed hash without a deliberate re-sync. If
someone edits `TOON-CONTRACT.md` or `fixtures/toon-golden/**` and forgets to
run `update`, `check` fails loudly instead of shipping a stale hash.

Usage:
  python3 scripts/sync_toon_contract.py check    # exit 1 on drift
  python3 scripts/sync_toon_contract.py update   # recompute + write the hash
"""

from __future__ import annotations

import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT_PATH = os.path.join(ROOT, "TOON-CONTRACT.md")
CORPUS_DIR = os.path.join(ROOT, "fixtures", "toon-golden")
HASH_PATH = os.path.join(CORPUS_DIR, ".contract-hash")


def _iter_corpus_files() -> list[str]:
    paths: list[str] = []
    for current, _dirs, files in os.walk(CORPUS_DIR):
        for name in files:
            if name == ".contract-hash":
                continue
            paths.append(os.path.join(current, name))
    return sorted(paths)


def compute_hash() -> str:
    digest = hashlib.sha256()
    with open(CONTRACT_PATH, "rb") as handle:
        digest.update(handle.read())
    for path in _iter_corpus_files():
        digest.update(os.path.relpath(path, CORPUS_DIR).replace(os.sep, "/").encode("utf-8"))
        with open(path, "rb") as handle:
            digest.update(handle.read())
    return digest.hexdigest()


def cmd_update() -> int:
    current = compute_hash()
    with open(HASH_PATH, "w", encoding="utf-8") as handle:
        handle.write(current + "\n")
    print(f"Wrote {HASH_PATH}: {current}")
    return 0


def cmd_check() -> int:
    if not os.path.isfile(HASH_PATH):
        print(
            f"::error::{HASH_PATH} missing. Run `python3 scripts/sync_toon_contract.py update` "
            "and commit the result.",
            file=sys.stderr,
        )
        return 1
    with open(HASH_PATH, encoding="utf-8") as handle:
        committed = handle.read().strip()
    current = compute_hash()
    if committed != current:
        print(
            "::error::TOON-CONTRACT.md / fixtures/toon-golden/ drifted from the committed "
            f".contract-hash (committed={committed}, current={current}). Run "
            "`python3 scripts/sync_toon_contract.py update` and commit the change.",
            file=sys.stderr,
        )
        return 1
    print(f"TOON-CONTRACT drift check OK ({current})")
    return 0


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "check"
    if command == "update":
        return cmd_update()
    if command == "check":
        return cmd_check()
    print(f"Unknown command: {command!r} (expected check|update)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
