#!/usr/bin/env python3
"""simplicio-loop — sync the pip-package bundle tree (`simplicio_loop/_bundle/`) from source (#98).

The repo ships `simplicio_loop/_bundle/` inside the `simplicio-loop` pip package so a plain
`pip install simplicio-loop` carries the skills/hooks/runtime-helper-scripts/parity-tests it
needs without requiring the whole git repo. Unlike the LEAN marketplace `plugin/` tree (see
`sync_plugin.py`), the pip bundle mirrors `.claude/skills/` and `hooks/` in FULL (every file,
including the pip-only capture proxy / dashboard / watcher) — only `scripts/` and `tests/` are
filtered down to the LEAN_SCRIPTS/LEAN_TESTS subset (`mirror_manifest.py`, the single source of
truth for that filter, shared with `scripts/claims_audit.py`'s `check_bundle_parity`).

Previously this mirror was kept in sync BY HAND (see docs/adr/0001-keep-versioned-mirrors-over-
build-time-vendoring.md, "Known gap" section) — `scripts/claims_audit.py` check 4
(`bundle-parity`) only ever DETECTED drift, nothing regenerated it. This script is the missing
write side, wired into `hooks/pre-commit.py` alongside `sync_plugin.py` (#98) so both mirrors
regenerate automatically on commit; `claims_audit.py` remains the fail-closed backstop for
commits made without the hook (or where it failed open).

Usage:  python3 scripts/sync_bundle.py         # rewrite simplicio_loop/_bundle/ from source
        python3 scripts/sync_bundle.py --check # exit 1 if _bundle/ is out of sync (no writes)
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

if HERE not in sys.path:
    sys.path.insert(0, HERE)
from mirror_manifest import LEAN_SCRIPTS, LEAN_TESTS  # noqa: E402 — single source of truth (#74)

SRC_SKILLS = os.path.join(REPO, ".claude", "skills")
DST_SKILLS = os.path.join(REPO, "simplicio_loop", "_bundle", "skills")
SRC_HOOKS = os.path.join(REPO, "hooks")
DST_HOOKS = os.path.join(REPO, "simplicio_loop", "_bundle", "hooks")
SRC_SCRIPTS = os.path.join(REPO, "scripts")
DST_SCRIPTS = os.path.join(REPO, "simplicio_loop", "_bundle", "scripts")
SRC_TESTS = os.path.join(REPO, "tests")
DST_TESTS = os.path.join(REPO, "simplicio_loop", "_bundle", "tests")
# #1410: the Claude adapter `hooks/user_prompt_submit.py` imports ships with the wheel too.
SRC_ADAPTER = os.path.join(REPO, "adapters", "claude")
DST_ADAPTER = os.path.join(REPO, "simplicio_loop", "_bundle", "adapters", "claude")

# (tag, src root, dst root, include filter or None for a full mirror) — mirrors the same pairs
# `claims_audit.check_bundle_parity` validates, so the two never drift apart in what they cover.
_PAIRS = [
    ("skills", SRC_SKILLS, DST_SKILLS, None),
    ("hooks", SRC_HOOKS, DST_HOOKS, None),
    ("scripts", SRC_SCRIPTS, DST_SCRIPTS, LEAN_SCRIPTS),
    ("tests", SRC_TESTS, DST_TESTS, LEAN_TESTS),
    ("adapters", SRC_ADAPTER, DST_ADAPTER, None),
]


def _read(p):
    with open(p, "rb") as f:
        return f.read()


def _walk_rel(root, include=None):
    out = []
    if not os.path.isdir(root):
        return out
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for n in files:
            if n.endswith((".pyc", ".pyo")):
                continue
            rel = os.path.relpath(os.path.join(r, n), root)
            if include is not None and rel not in include:
                continue
            out.append(rel)
    return sorted(out)


def sync():
    counts = {}
    for tag, src_root, dst_root, include in _PAIRS:
        if include is None:
            # full byte-identical mirror (skills, hooks)
            if os.path.isdir(dst_root):
                shutil.rmtree(dst_root)
            if os.path.isdir(src_root):
                shutil.copytree(src_root, dst_root,
                                 ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            # filtered mirror — only the LEAN_* subset (scripts, tests)
            if os.path.isdir(dst_root):
                shutil.rmtree(dst_root)
            os.makedirs(dst_root, exist_ok=True)
            for name in include:
                src = os.path.join(src_root, name)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(dst_root, name))
        counts[tag] = len(_walk_rel(dst_root))
    print("synced simplicio_loop/_bundle/: %d skill files, %d hook files, %d script files, "
          "%d test files, %d adapter files" % (counts["skills"], counts["hooks"], counts["scripts"],
                                               counts["tests"], counts["adapters"]))


def check():
    """Return list of drift strings (empty == in sync)."""
    drift = []
    for tag, src_root, dst_root, include in _PAIRS:
        if not os.path.isdir(dst_root):
            drift.append("_bundle/%s missing — run scripts/sync_bundle.py" % tag)
            continue
        want = set(include) if include is not None else None
        src_files = set(_walk_rel(src_root, want))
        dst_files = set(_walk_rel(dst_root, want if want is not None else None))
        for rel in sorted(src_files - dst_files):
            drift.append("_bundle/%s: missing %s" % (tag, rel))
        for rel in sorted(dst_files - src_files):
            drift.append("_bundle/%s: orphan %s (no matching source file)" % (tag, rel))
        for rel in sorted(src_files & dst_files):
            if _read(os.path.join(src_root, rel)) != _read(os.path.join(dst_root, rel)):
                drift.append("_bundle/%s: differs %s" % (tag, rel))
    return drift


def main():
    if "--check" in sys.argv[1:]:
        drift = check()
        if drift:
            print("bundle sync: DRIFT (%d)" % len(drift))
            for d in drift:
                print("  " + d)
            sys.exit(1)
        print("bundle sync: ok (simplicio_loop/_bundle/ == source)")
        sys.exit(0)
    sync()


if __name__ == "__main__":
    main()
