#!/usr/bin/env python3
"""simplicio-loop — Repository size budget guard (#294, step 1-2 of the governance plan).

`.claude/skills/simplicio-loop` ships as a lean skill/adapter tree, but nothing in the local gate
noticed if a NEW commit added a large binary/media blob to the tracked working tree — the exact
failure mode the #294 audit flagged (README/PyPI/changelog claims aside, the tracked tree itself
can silently balloon one big video/screenshot at a time). This guard is scoped deliberately
NARROW and SAFE: it measures and gates the CURRENT tracked working tree only. It never touches
git history, never rewrites refs, and never runs `git filter-repo` — that migration is called out
in the issue as requiring an explicit, separately-approved maintainer decision (backup, dry-run,
communicated window). This script is step 1 ("measure and classify") and step 2 ("stop new
commits from making it worse") of that plan; the history-rewrite step is intentionally NOT here.

What it does:
  - lists every git-tracked file with its on-disk size (`git ls-files` + `os.stat`, so it reads
    the current worktree, not blobs from old history);
  - reports the N largest tracked files (default 20) — the "biggest blobs" report the issue asks
    to "publish before any rewrite";
  - enforces a **per-file** hard cap (`MAX_SINGLE_FILE_BYTES`) for any NEW file that was not
    already over the cap in the committed baseline (catches "someone just committed a 40MB
    video") — pre-existing oversized files (e.g. the doc hero images already in the tree) are
    grandfathered by the baseline so this gate does not retroactively fail on history it did not
    create, but they may not grow past `THRESHOLD_GROWTH` themselves either;
  - enforces a **total tracked tree** budget via a committed baseline
    (`scripts/repository_budget_baseline.json`), same pattern as `scripts/token_budget.py` (#121):
    growth past `THRESHOLD_GROWTH` over the last deliberately-reviewed baseline fails the gate.

Usage:
    python3 scripts/repository_budget.py                    # report + gate against the baseline
    python3 scripts/repository_budget.py --check             # same, quiet unless it fails
    python3 scripts/repository_budget.py --update-baseline   # regenerate the baseline after a
                                                               # deliberate, reviewed size change
    python3 scripts/repository_budget.py --top 20             # report N largest tracked files

Exit codes: 0 = within budget, 1 = budget exceeded (total growth or a single oversized file).
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
BASELINE_PATH = os.path.join(HERE, "repository_budget_baseline.json")
ALLOWLIST_PATH = os.path.join(HERE, "repository_budget_allowlist.json")
GITATTRIBUTES_PATH = os.path.join(REPO, ".gitattributes")

# A single tracked file over this size fails the gate immediately, independent of the baseline.
# 2 MiB is generous for source/docs/small fixtures but catches an accidentally-committed video,
# archive, or dataset the #294 audit is specifically about.
MAX_SINGLE_FILE_BYTES = 2 * 1024 * 1024

# Allowed growth of the TOTAL tracked tree size over the committed baseline before the guard
# fails. Mirrors token_budget.py's THRESHOLD_GROWTH so both budget guards behave predictably.
THRESHOLD_GROWTH = 0.25

DEFAULT_TOP_N = 20

# Paths that must NEVER carry raw (non-LFS) media. A committed file under one of
# these prefixes that is NOT routed to LFS by .gitattributes fails the gate — the
# media must be served via LFS / GitHub Releases / release artifacts instead
# (#294 step 2.2/2.4, AC "mídia em caminho proibido bloqueia").
FORBIDDEN_RAW_MEDIA_PREFIXES = (
    "video/out/",
    "rust/target/",
    "node_modules/",
    "dist/",
    "build/",
)

# Extensions that count as "large generated media" and therefore require LFS
# routing (or must not be committed at all). Mirrors .gitattributes' LFS filters.
LFS_MEDIA_SUFFIXES = (
    ".mp4", ".mov", ".webm", ".avi", ".wav", ".mp3", ".m4a", ".flac", ".ogg",
    ".zip", ".tar.gz", ".tgz", ".iso", ".bin",
)

# `.gitattributes` patterns that declare LFS routing. We parse them so the gate
# can recognize, from the committed .gitattributes, exactly which suffixes/prefixes
# are LFS-exempt. Kept in sync with the LFS filters in .gitattributes.
_LFS_SUFFIX_PAT = re.compile(r"^\*\.(mp4|mov|webm|avi|wav|mp3|m4a|flac|ogg|zip|tar\.gz|tgz|iso|bin)\s+filter=lfs", re.M)
_LFS_PREFIX_PAT = re.compile(r"^([^\s#]+?)\s+filter=lfs", re.M)


def _load_allowlist():
    """Explicit, reviewed exceptions from ALLOWLIST_PATH (never a wildcard).

    Each entry names an exact tracked path plus the reason it is real,
    needed content rather than a generated/dogfood artifact -- see
    scripts/repository_budget_allowlist.json. Missing/malformed file means
    an empty allowlist (fail closed to "not exempt", never silently permit).
    """
    try:
        with open(ALLOWLIST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}, {}
    return (
        dict(data.get("oversized_files") or {}),
        dict(data.get("forbidden_raw_media") or {}),
    )


def _lfs_exempt_patterns():
    """Return (set_of_lower_suffixes, set_of_prefixes) declared LFS in .gitattributes."""
    suffixes = set()
    prefixes = set()
    if not os.path.exists(GITATTRIBUTES_PATH):
        return suffixes, prefixes
    text = ""
    try:
        with open(GITATTRIBUTES_PATH, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return suffixes, prefixes
    for m in _LFS_SUFFIX_PAT.finditer(text):
        suffixes.add("." + m.group(1).lower())
    for m in _LFS_PREFIX_PAT.finditer(text):
        p = m.group(1).strip()
        # `*.foo` handled above; anything else is a path prefix / glob.
        if p.startswith("*.") or p == "*":
            continue
        prefixes.add(p.rstrip("*").rstrip("/"))
    return suffixes, prefixes


def _is_lfs_exempt(rel):
    """True if `rel` is routed to LFS per the committed .gitattributes."""
    suffixes, prefixes = _lfs_exempt_patterns()
    low = rel.lower()
    ext = os.path.splitext(low)[1]
    if ext in suffixes:
        return True
    for p in prefixes:
        if low.startswith(p.lower()):
            return True
    return False


def _new_forbidden_raw_media(entries):
    """Block media that should not be a raw git blob.

    Two distinct rules, evaluated in order:

    1. FORBIDDEN PREFIX — `video/out/`, `rust/target/`, `node_modules/`, `dist/`,
       `build/` are ephemeral / gitignored outputs that must NEVER be committed to
       the git tree at all, raw OR LFS. They are blocked unconditionally (AC
       "mídia em caminho proibido bloqueia"). They are reproduced by build tooling
       or fetched from GitHub Releases / artifact storage, never stored in git.

    2. LARGE MEDIA SUFFIX — a `.mp4`/`.zip`/etc. committed anywhere ELSE (e.g.
       `assets/_lfs/demo.mp4`) is only allowed if `.gitattributes` routes it to LFS
       (`filter=lfs`). An LFS-routed file is a small pointer, not a raw blob, so it
       does not inflate the pack (AC "asset LFS permitido passa"). A large-media
       suffix with no LFS filter is a raw blob and is blocked.
    """
    _, media_allowlist = _load_allowlist()
    flagged = []
    for rel, size in entries:
        if rel in media_allowlist:
            continue
        low = rel.lower()
        if low.startswith(FORBIDDEN_RAW_MEDIA_PREFIXES):
            flagged.append((rel, size, "forbidden-path"))  # rule 1: always block
            continue
        if low.endswith(LFS_MEDIA_SUFFIXES) and not _is_lfs_exempt(rel):
            flagged.append((rel, size, "forbidden-raw-media"))  # rule 2: must be LFS
    return flagged


def _run_git(args):
    r = subprocess.run(["git"] + args, cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout


def list_tracked_files():
    """Return sorted list of (rel_path, size_bytes) for every git-tracked file currently on disk.

    Uses `git ls-files -z` (not a filesystem walk) so build artifacts / .gitignore'd caches never
    count against the budget — only what is ACTUALLY tracked and would ship in a clone.
    """
    out = _run_git(["ls-files", "-z"])
    rels = [p for p in out.split("\0") if p]
    entries = []
    for rel in rels:
        abspath = os.path.join(REPO, rel)
        try:
            size = os.path.getsize(abspath)
        except OSError:
            # Tracked but missing on disk (e.g. a submodule gitlink) — not a size concern here.
            continue
        entries.append((rel, size))
    return entries


def measure():
    entries = list_tracked_files()
    total = sum(size for _, size in entries)
    return entries, total


def load_baseline():
    if not os.path.exists(BASELINE_PATH):
        return None
    try:
        with open(BASELINE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_baseline(entries, total):
    # Grandfather any file already over the per-file cap at the time the baseline is (re)written
    # -- the gate's job is to stop NEW growth, not to retroactively fail on assets that already
    # shipped. Re-running --update-baseline after adding a new oversized file bakes it in too,
    # which is the deliberate/reviewed escape hatch the docstring calls out.
    known_oversized = {rel: size for rel, size in entries if size > MAX_SINGLE_FILE_BYTES}
    payload = {
        "$schema_note": "simplicio-loop repository size budget baseline (#294). Regenerate with "
                        "`python3 scripts/repository_budget.py --update-baseline` after a "
                        "deliberate, reviewed size change -- never to silence a regression you "
                        "haven't looked at.",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "threshold_growth": THRESHOLD_GROWTH,
        "max_single_file_bytes": MAX_SINGLE_FILE_BYTES,
        "tracked_file_count": len(entries),
        "total_bytes": total,
        "known_oversized_files": known_oversized,
    }
    with open(BASELINE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    return payload


def _fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024.0:
            return "%.1f%s" % (n, unit)
        n /= 1024.0
    return "%.1fTB" % n


def _new_oversized_files(entries, baseline):
    """Files over the per-file cap that are NOT grandfathered by the baseline (new, or grew past
    their recorded baseline size by more than THRESHOLD_GROWTH)."""
    known = (baseline or {}).get("known_oversized_files", {}) or {}
    oversized_allowlist, _ = _load_allowlist()
    flagged = []
    for rel, size in entries:
        if size <= MAX_SINGLE_FILE_BYTES:
            continue
        if rel in oversized_allowlist:
            continue
        base_size = known.get(rel)
        if base_size is None:
            flagged.append((rel, size, None))
            continue
        threshold = int(base_size * (1 + THRESHOLD_GROWTH))
        if size > threshold:
            flagged.append((rel, size, base_size))
    return flagged


def report(entries, total, baseline, top_n, quiet=False):
    """Print the report and return True if everything is within budget."""
    ok = True
    oversized = _new_oversized_files(entries, baseline)
    forbidden = _new_forbidden_raw_media(entries)
    if oversized or forbidden:
        ok = False

    lines = []
    lines.append("tracked files: %d, total size: %s" % (len(entries), _fmt_bytes(total)))

    largest = sorted(entries, key=lambda e: e[1], reverse=True)[:top_n]
    lines.append("--- %d largest tracked files ---" % len(largest))
    for rel, size in largest:
        flag = " [OVER %s CAP]" % _fmt_bytes(MAX_SINGLE_FILE_BYTES) if size > MAX_SINGLE_FILE_BYTES else ""
        lines.append("  %10s  %s%s" % (_fmt_bytes(size), rel, flag))

    if forbidden:
        lines.append("[FAIL] %d forbidden raw media path(s) (large media/archive must be LFS-routed "
                      "or not committed — see .gitattributes + docs/REPOSITORY_GOVERNANCE.md):" % len(forbidden))
        for rel, size, _ in forbidden:
            lines.append("  %10s  %s" % (_fmt_bytes(size), rel))

    if baseline is not None:
        base_total = baseline.get("total_bytes", 0)
        threshold = int(base_total * (1 + THRESHOLD_GROWTH)) if base_total else total
        delta = total - base_total
        pct = (delta / base_total * 100) if base_total else 0.0
        status = "ok"
        if total > threshold:
            status = "FAIL"
            ok = False
        sign = "+" if delta >= 0 else ""
        lines.append("[%s] total tree size %s (baseline %s, %s%s, %+.1f%%, threshold %s)" % (
            status, _fmt_bytes(total), _fmt_bytes(base_total), sign, _fmt_bytes(delta), pct,
            _fmt_bytes(threshold)))
    else:
        lines.append("[NEW] no baseline yet at %s" % BASELINE_PATH)

    if oversized:
        lines.append("[FAIL] %d file(s) exceed the per-file cap of %s (new or grown past their "
                      "grandfathered baseline size):" % (len(oversized), _fmt_bytes(MAX_SINGLE_FILE_BYTES)))
        for rel, size, base_size in oversized:
            if base_size is None:
                lines.append("  %10s  %s  (new)" % (_fmt_bytes(size), rel))
            else:
                lines.append("  %10s  %s  (baseline %s)" % (_fmt_bytes(size), rel, _fmt_bytes(base_size)))

    if not quiet or not ok:
        print("=== repository size budget ===")
        for line in lines:
            print(line)
        print("repository-budget: %s" % ("PASS" if ok else "FAIL"))
    return ok


def main():
    args = sys.argv[1:]
    update = "--update-baseline" in args
    quiet = "--check" in args
    top_n = DEFAULT_TOP_N
    if "--top" in args:
        idx = args.index("--top")
        if idx + 1 < len(args):
            try:
                top_n = int(args[idx + 1])
            except ValueError:
                pass

    entries, total = measure()

    if update:
        payload = write_baseline(entries, total)
        print("wrote %s (%d tracked files, %s total)" % (
            BASELINE_PATH, payload["tracked_file_count"], _fmt_bytes(payload["total_bytes"])))
        return 0

    baseline = load_baseline()
    if baseline is None:
        print("no baseline at %s -- run --update-baseline first" % BASELINE_PATH)
        # First run ever: still report + still enforce the per-file cap, but don't fail the gate
        # on a missing baseline (same policy as token_budget.py). Without a baseline nothing is
        # grandfathered, so any currently-oversized file is reported but does not fail this
        # first-ever run -- it will fail on the NEXT run once a baseline exists, unless
        # --update-baseline grandfathers it deliberately.
        report(entries, total, None, top_n, quiet=False)
        return 0

    ok = report(entries, total, baseline, top_n, quiet=quiet)
    return 0 if ok else 1


def selftest():
    """Cheap in-process sanity check (no subprocess) that the core measurement plumbing works."""
    checks = []
    try:
        entries, total = measure()
        checks.append(("measure() returns tracked files", len(entries) > 0))
        checks.append(("total_bytes matches sum of entries", total == sum(s for _, s in entries)))
    except Exception as exc:  # pragma: no cover - defensive
        checks.append(("measure() raised: %s" % exc, False))
    checks.append(("MAX_SINGLE_FILE_BYTES is positive", MAX_SINGLE_FILE_BYTES > 0))
    checks.append(("THRESHOLD_GROWTH is between 0 and 1", 0 < THRESHOLD_GROWTH < 1))
    # Forbidden-path / LFS-exemption logic (P2 acceptance tests — no subprocess, pure checks).
    rel_entries = [("docs/REPO_SIZE_REPORT.md", 1024), ("assets/simplicio-loop-logo.png", 4924 * 1024)]
    checks.append(("no false-positive forbidden media on real tracked source",
                   _new_forbidden_raw_media(rel_entries) == []))
    # An mp4 under a forbidden prefix with NO LFS exemption must be flagged.
    bad = [("video/out/demo.mp4", 50 * 1024 * 1024)]
    flagged = _new_forbidden_raw_media(bad)
    checks.append(("forbidden raw .mp4 under video/out/ is flagged", len(flagged) == 1))
    # video/out/ is a forbidden PREFIX — blocked even if the suffix were LFS-routable.
    checks.append(("forbidden prefix video/out/ always blocked (raw or lfs)",
                   _new_forbidden_raw_media([("video/out/x.mp4", 1)]) != []))
    checks.append(("forbidden prefix rust/target/ always blocked",
                   _new_forbidden_raw_media([("rust/target/big.o", 1)]) != []))
    # The same media routed through the LFS staging area is exempt (AC: asset LFS permitido passa).
    suffixes, prefixes = _lfs_exempt_patterns()
    checks.append((".gitattributes declares LFS for the assets/_lfs/ staging area",
                   any("assets/_lfs" in p for p in prefixes)))
    checks.append(("no GLOBAL suffix LFS rule (stray root media must stay blocked)",
                   not suffixes))  # only a scoped prefix is LFS-exempt, never bare *.ext
    checks.append(("LFS-exempt .mp4 is recognized as exempt",
                   _is_lfs_exempt("assets/_lfs/demo.mp4") is True))
    checks.append(("plain source .py is NOT LFS-exempt",
                   _is_lfs_exempt("scripts/check.py") is False))
    ok = all(v for _, v in checks)
    for name, v in checks:
        print("  [%s] %s" % ("ok" if v else "XX", name))
    print("repository_budget selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        sys.exit(selftest())
    sys.exit(main())
