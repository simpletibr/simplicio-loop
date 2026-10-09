#!/usr/bin/env python3
"""simplicio-loop — sync the LEAN marketplace plugin tree (`plugin/`) from source.

The repo doubles as a pip package (engine + proxy + token-monitor dashboard) AND a Claude
marketplace plugin. A marketplace install copies the WHOLE plugin source to the user's cache, so the
plugin must NOT carry the heavy pip-only assets. `plugin/` is therefore a SLIM mirror containing only
what the plugin actually loads or transitively depends on at runtime:

  plugin/skills/   <- byte-identical copy of .claude/skills/  (the 7 skills)
  plugin/hooks/    <- ONLY the hooks wired by hooks.claude.json (+ orient_clamp, a runtime dep)
  plugin/scripts/  <- helper scripts invoked by the shipped loop hook
  plugin/tests/    <- minimal parity/self-run tests for the shipped loop behavior

Excluded by design (pip-only, never wired into the plugin): the capture proxy (`engine/`), the
token-monitor dashboard (`hooks/simplicio_dashboard.py`), the 24/7 watcher (`hooks/simplicio_watch.py`),
the Cursor-only `loop_capture.py`/`hooks.json`, and every non-runtime helper under `scripts/` /
`tests/`. Run this after editing skills or a shipped runtime file; `scripts/claims_audit.py`
(check 5) fails if `plugin/` drifts from source.

Usage:  python3 scripts/sync_plugin.py        # rewrite shipped plugin trees from source
        python3 scripts/sync_plugin.py --check # exit 1 if plugin/ is out of sync (no writes)
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

if HERE not in sys.path:
    sys.path.insert(0, HERE)
from mirror_manifest import LEAN_HOOKS, LEAN_SCRIPTS, LEAN_TESTS  # noqa: E402 — single source of truth (#74)

SRC_SKILLS = os.path.join(REPO, ".claude", "skills")
DST_SKILLS = os.path.join(REPO, "plugin", "skills")
SRC_HOOKS = os.path.join(REPO, "hooks")
DST_HOOKS = os.path.join(REPO, "plugin", "hooks")
SRC_SCRIPTS = os.path.join(REPO, "scripts")
DST_SCRIPTS = os.path.join(REPO, "plugin", "scripts")
SRC_TESTS = os.path.join(REPO, "tests")
DST_TESTS = os.path.join(REPO, "plugin", "tests")

# #458 item 2: the canonical stage-agents contracts tree must be mirrored into the
# pip-package bundle so `simplicio_loop/_contracts/stage-agents/v1/` never drifts from
# `contracts/stage-agents/v1/` (the source of truth). Byte-identical, bidirectional.
SRC_CONTRACTS = os.path.join(REPO, "contracts", "stage-agents", "v1")
DST_CONTRACTS = os.path.join(REPO, "simplicio_loop", "_contracts", "stage-agents", "v1")
# #1612: the closed model-response schemas ship in the bundle the same way.
SRC_STRUCTURED = os.path.join(REPO, "contracts", "structured-output", "v1")
DST_STRUCTURED = os.path.join(REPO, "simplicio_loop", "_contracts", "structured-output", "v1")
CONTRACT_TREES = ((SRC_CONTRACTS, DST_CONTRACTS), (SRC_STRUCTURED, DST_STRUCTURED))


def _read(p):
    with open(p, "rb") as f:
        return f.read()


def _walk_rel(root):
    out = []
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for n in files:
            if n.endswith((".pyc", ".pyo")):
                continue
            out.append(os.path.relpath(os.path.join(r, n), root))
    return sorted(out)


def sync():
    # skills: full byte-identical mirror
    if os.path.isdir(DST_SKILLS):
        shutil.rmtree(DST_SKILLS)
    shutil.copytree(SRC_SKILLS, DST_SKILLS, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # hooks: only the lean wired set
    if os.path.isdir(DST_HOOKS):
        shutil.rmtree(DST_HOOKS)
    os.makedirs(DST_HOOKS, exist_ok=True)
    for name in LEAN_HOOKS:
        src = os.path.join(SRC_HOOKS, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(DST_HOOKS, name))
    # scripts: only helpers the shipped hook calls directly
    if os.path.isdir(DST_SCRIPTS):
        shutil.rmtree(DST_SCRIPTS)
    os.makedirs(DST_SCRIPTS, exist_ok=True)
    for name in LEAN_SCRIPTS:
        src = os.path.join(SRC_SCRIPTS, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(DST_SCRIPTS, name))
    # tests: minimal shipped parity checks for the loop/runtime helpers
    if os.path.isdir(DST_TESTS):
        shutil.rmtree(DST_TESTS)
    os.makedirs(DST_TESTS, exist_ok=True)
    for name in LEAN_TESTS:
        src = os.path.join(SRC_TESTS, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(DST_TESTS, name))
    # contracts: the canonical stage-agents tree mirrored into the pip bundle (#458)
    for src_tree, dst_tree in CONTRACT_TREES:
        if os.path.isdir(dst_tree):
            shutil.rmtree(dst_tree)
        if os.path.isdir(src_tree):
            shutil.copytree(src_tree, dst_tree, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print("synced plugin/: %d skill files, %d hook files, %d script files, %d test files" % (
        len(_walk_rel(DST_SKILLS)), len(_walk_rel(DST_HOOKS)),
        len(_walk_rel(DST_SCRIPTS)), len(_walk_rel(DST_TESTS))))
    if os.path.isdir(DST_CONTRACTS):
        print("synced contracts/: %d stage-agent contract files" % len(_walk_rel(DST_CONTRACTS)))


def check_contracts():
    """#458 item 2 and #1612: drift between each contracts/<name>/v1/ (source) and
    simplicio_loop/_contracts/<name>/v1/ (pip bundle). Returns drift list
    (empty == in sync), checked in BOTH directions."""
    drift = []
    for src_tree, dst_tree in CONTRACT_TREES:
        name = os.path.relpath(src_tree, os.path.join(REPO, "contracts")).replace(os.sep, "/")
        if not os.path.isdir(src_tree):
            drift.append("contracts/%s missing — source of truth gone" % name)
            continue
        if not os.path.isdir(dst_tree):
            drift.append("simplicio_loop/_contracts/%s missing — run scripts/sync_plugin.py" % name)
            continue
        src = set(_walk_rel(src_tree))
        dst = set(_walk_rel(dst_tree))
        for rel in sorted(src - dst):
            drift.append("contracts: missing in bundle: %s/%s" % (name, rel))
        for rel in sorted(dst - src):
            drift.append("contracts: orphan in bundle (no matching source): %s/%s" % (name, rel))
        for rel in sorted(src & dst):
            if _read(os.path.join(src_tree, rel)) != _read(os.path.join(dst_tree, rel)):
                drift.append("contracts: differs: %s/%s" % (name, rel))
    return drift


def check():
    """Return list of drift strings (empty == in sync)."""
    drift = []
    if not os.path.isdir(DST_SKILLS):
        return ["plugin/skills missing — run scripts/sync_plugin.py"]
    src = set(_walk_rel(SRC_SKILLS))
    dst = set(_walk_rel(DST_SKILLS))
    for rel in sorted(src - dst):
        drift.append("plugin/skills: missing %s" % rel)
    for rel in sorted(dst - src):
        drift.append("plugin/skills: extra %s" % rel)
    for rel in sorted(src & dst):
        if _read(os.path.join(SRC_SKILLS, rel)) != _read(os.path.join(DST_SKILLS, rel)):
            drift.append("plugin/skills: differs %s" % rel)
    # hooks: exactly the lean set, each byte-identical to source; none of the excluded files present
    have = set(_walk_rel(DST_HOOKS)) if os.path.isdir(DST_HOOKS) else set()
    want = set(n for n in LEAN_HOOKS if os.path.exists(os.path.join(SRC_HOOKS, n)))
    for rel in sorted(want - have):
        drift.append("plugin/hooks: missing %s" % rel)
    for rel in sorted(have - want):
        drift.append("plugin/hooks: unexpected %s (lean plugin ships only the wired set)" % rel)
    for rel in sorted(want & have):
        if _read(os.path.join(SRC_HOOKS, rel)) != _read(os.path.join(DST_HOOKS, rel)):
            drift.append("plugin/hooks: differs %s" % rel)
    # scripts: exactly the lean runtime helper set used by the shipped loop hook
    have = set(_walk_rel(DST_SCRIPTS)) if os.path.isdir(DST_SCRIPTS) else set()
    want = set(n for n in LEAN_SCRIPTS if os.path.exists(os.path.join(SRC_SCRIPTS, n)))
    for rel in sorted(want - have):
        drift.append("plugin/scripts: missing %s" % rel)
    for rel in sorted(have - want):
        drift.append("plugin/scripts: unexpected %s (lean plugin ships only the runtime helper set)" % rel)
    for rel in sorted(want & have):
        if _read(os.path.join(SRC_SCRIPTS, rel)) != _read(os.path.join(DST_SCRIPTS, rel)):
            drift.append("plugin/scripts: differs %s" % rel)
    # tests: keep the shipped plugin parity tests byte-identical to source
    have = set(_walk_rel(DST_TESTS)) if os.path.isdir(DST_TESTS) else set()
    want = set(n for n in LEAN_TESTS if os.path.exists(os.path.join(SRC_TESTS, n)))
    for rel in sorted(want - have):
        drift.append("plugin/tests: missing %s" % rel)
    for rel in sorted(have - want):
        drift.append("plugin/tests: unexpected %s (lean plugin ships only the minimal loop parity tests)" % rel)
    for rel in sorted(want & have):
        if _read(os.path.join(SRC_TESTS, rel)) != _read(os.path.join(DST_TESTS, rel)):
            drift.append("plugin/tests: differs %s" % rel)
    return drift


def main():
    if "--check-contracts" in sys.argv[1:]:
        drift = check_contracts()
        if drift:
            print("contracts sync: DRIFT (%d)" % len(drift))
            for d in drift:
                print("  " + d)
            sys.exit(1)
        print("contracts sync: ok (simplicio_loop/_contracts/<name>/v1 == contracts/<name>/v1)")
        sys.exit(0)
    if "--check" in sys.argv[1:]:
        drift = check()
        cdrift = check_contracts()
        if drift:
            print("plugin sync: DRIFT (%d)" % len(drift))
            for d in drift:
                print("  " + d)
        if cdrift:
            print("contracts sync: DRIFT (%d)" % len(cdrift))
            for d in cdrift:
                print("  " + d)
        if drift or cdrift:
            sys.exit(1)
        print("plugin sync: ok (plugin/ == source)")
        print("contracts sync: ok (simplicio_loop/_contracts/stage-agents/v1 == contracts/stage-agents/v1)")
        sys.exit(0)
    sync()


if __name__ == "__main__":
    main()
