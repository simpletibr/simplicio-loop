#!/usr/bin/env python3
"""simplicio-loop — wheel/sdist package content check (#294 AC11, step 6.5 of the plan).

"Prove that wheel/plugin don't carry media or unneeded mirrors" (issue step 6, item 5). This
actually BUILDS the real artifacts (`python -m build --sdist --wheel`) into a throwaway temp
directory and inspects their REAL contents — it does not guess from `pyproject.toml`
declarations alone, because a stray `include_package_data` glob or a `MANIFEST.in` wildcard is
exactly the kind of drift that only shows up in the actual built artifact.

Per repo convention (`scripts/video_evidence.py`, `scripts/repository_budget.py`, etc.): a missing
toolchain BLOCKS (exit 1, clearly reported), it never silently skips and reports a fake pass.

Checks:
  - sdist (`python -m build --sdist`): every member's path is checked against a small deny-list of
    directories that must never ship (`video/out/`, `node_modules/`, `.git/`), and no
    single member exceeds `MAX_MEMBER_BYTES`.
  - wheel (`python -m build --wheel`): same deny-list + per-member size cap check against the
    real `.whl` (a zip) contents.

This repo ships a Python-only package at the root (100% Python, #1298); there is no npm launcher
to build or check here anymore.

Usage:
    python3 scripts/package_content_check.py            # run both checks, print report
    python3 scripts/package_content_check.py --json      # machine-readable report
    python3 scripts/package_content_check.py --only sdist,wheel

Exit codes: 0 = every buildable artifact is clean, 1 = a member violated the deny-list/size cap
OR a required toolchain (the `build` module) is missing (fail-closed, not a skip).
"""
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# Same cap `scripts/repository_budget.py` uses for the tracked-tree gate — a built artifact should
# never carry a member bigger than a single tracked file is already allowed to be.
MAX_MEMBER_BYTES = 2 * 1024 * 1024

# Directory/name fragments that must NEVER appear inside a shipped artifact — generated build
# output, generated media, VCS internals, or a node toolchain cache accidentally swept in by a
# wildcard MANIFEST.in glob.
DENY_FRAGMENTS = ("video/out/", "node_modules/", "/.git/", ".git/")


def _fmt_bytes(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024.0:
            return "%.1f%s" % (n, unit)
        n /= 1024.0
    return "%.1fTB" % n


def _violations(members):
    """members: list of (path, size). Returns list of violation strings."""
    bad = []
    for path, size in members:
        norm = path.replace("\\", "/")
        for frag in DENY_FRAGMENTS:
            if frag in norm:
                bad.append("denied path shipped: %s (matches %r)" % (path, frag))
                break
        if size > MAX_MEMBER_BYTES:
            bad.append("oversized member: %s (%s > cap %s)" % (
                path, _fmt_bytes(size), _fmt_bytes(MAX_MEMBER_BYTES)))
    return bad


def check_sdist():
    try:
        import build  # noqa: F401
    except ImportError:
        return False, "python 'build' module not installed (pip install build) -- BLOCKED, not skipped"
    tmpdir = tempfile.mkdtemp(prefix="simplicio-sdist-")
    try:
        r = subprocess.run([sys.executable, "-m", "build", "--sdist", "--outdir", tmpdir],
                           cwd=REPO, capture_output=True, text=True)
        if r.returncode != 0:
            return False, "sdist build failed: %s" % (r.stderr or r.stdout)[-800:]
        archives = [f for f in os.listdir(tmpdir) if f.endswith(".tar.gz")]
        if not archives:
            return False, "sdist build produced no .tar.gz"
        path = os.path.join(tmpdir, archives[0])
        with tarfile.open(path) as tf:
            members = [(m.name, m.size) for m in tf.getmembers() if m.isfile()]
        bad = _violations(members)
        total = sum(s for _, s in members)
        detail = "sdist %s: %d files, %s total" % (archives[0], len(members), _fmt_bytes(total))
        if bad:
            return False, detail + " -- " + "; ".join(bad[:10])
        return True, detail
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def check_wheel():
    try:
        import build  # noqa: F401
    except ImportError:
        return False, "python 'build' module not installed (pip install build) -- BLOCKED, not skipped"
    tmpdir = tempfile.mkdtemp(prefix="simplicio-wheel-")
    try:
        r = subprocess.run([sys.executable, "-m", "build", "--wheel", "--outdir", tmpdir],
                           cwd=REPO, capture_output=True, text=True)
        if r.returncode != 0:
            return False, "wheel build failed: %s" % (r.stderr or r.stdout)[-800:]
        archives = [f for f in os.listdir(tmpdir) if f.endswith(".whl")]
        if not archives:
            return False, "wheel build produced no .whl"
        path = os.path.join(tmpdir, archives[0])
        with zipfile.ZipFile(path) as zf:
            members = [(i.filename, i.file_size) for i in zf.infolist()
                       if not i.filename.endswith("/")]
        bad = _violations(members)
        total = sum(s for _, s in members)
        detail = "wheel %s: %d files, %s total" % (archives[0], len(members), _fmt_bytes(total))
        if bad:
            return False, detail + " -- " + "; ".join(bad[:10])
        return True, detail
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


CHECKS = {"sdist": check_sdist, "wheel": check_wheel}


def main(argv=None):
    args = list(argv if argv is not None else sys.argv[1:])
    as_json = "--json" in args
    only = None
    if "--only" in args:
        only = set(args[args.index("--only") + 1].split(","))

    results = []
    for name, fn in CHECKS.items():
        if only and name not in only:
            continue
        try:
            ok, detail = fn()
        except Exception as exc:  # fail-closed: a crashing check is a failed check
            ok, detail = False, "check crashed: %s" % exc
        results.append({"check": name, "ok": ok, "detail": detail})

    failed = [r for r in results if not r["ok"]]
    if as_json:
        print(json.dumps({"ok": not failed, "results": results}, indent=2, ensure_ascii=False))
    else:
        print("=== package content check (#294 AC11) ===")
        for r in results:
            print("[%s] %s — %s" % ("ok" if r["ok"] else "XX", r["check"], r["detail"]))
        print("package-content-check: %s (%d/%d)" % (
            "PASS" if not failed else "FAIL", len(results) - len(failed), len(results)))
    return 0 if not failed else 1


def selftest():
    """Prove the deny-list/size-cap logic works without needing an actual build (fast, no network,
    no subprocess) -- the real build is exercised by `main()`/CI, not by this cheap unit check."""
    checks = []
    clean = [("simplicio_loop/cli.py", 1000), ("README.md", 200)]
    dirty_path = [("node_modules/pkg/index.js", 1000)]
    dirty_size = [("simplicio_loop/big.bin", MAX_MEMBER_BYTES + 1)]
    checks.append(("clean member list has no violations", _violations(clean) == []))
    checks.append(("denied path is flagged", len(_violations(dirty_path)) == 1))
    checks.append(("oversized member is flagged", len(_violations(dirty_size)) == 1))
    checks.append(("MAX_MEMBER_BYTES positive", MAX_MEMBER_BYTES > 0))
    checks.append(("CHECKS has sdist/wheel", set(CHECKS) == {"sdist", "wheel"}))
    ok = all(v for _, v in checks)
    for name, v in checks:
        print("  [%s] %s" % ("ok" if v else "XX", name))
    print("package_content_check selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        sys.exit(selftest())
    if len(sys.argv) > 1 and sys.argv[1] == "--describe-cli":
        print(json.dumps({
            "verbs": ["selftest"],
            "flags": ["--json", "--only", "--describe-cli"],
        }))
        sys.exit(0)
    sys.exit(main())
