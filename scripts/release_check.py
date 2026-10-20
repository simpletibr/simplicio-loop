#!/usr/bin/env python3
"""simplicio-loop — release-version check (is a newer release available?).

The canonical version lives in `pyproject.toml` (kept in lockstep across every published surface
by `scripts/version_sync.py`). This worker answers one narrow question deterministically: is the
LOCAL canonical version behind the LATEST GitHub release tag? If yes, it prints an explicit,
machine-and-LLM-readable instruction to update — never a silent "you're fine" when a newer release
exists, and never a fabricated "update available" when the network/API is unreachable (fail-open,
tagged UNVERIFIED).

This does NOT perform the update itself — it only detects and reports. The actual update remains
`bash scripts/update.sh [<runtime>]` (README § Update), so a detected-but-declined update is never
silently applied.

Verbs:
    check    Compare local canonical version (pyproject.toml) against the latest GitHub release
             tag for --repo (default: simpletibr/simplicio-loop). Exit 0 = up to date or
             check inconclusive (network/gh unavailable); exit 10 = a newer release exists (for
             `if:` gating in a preflight/doctor chain). Never exits non-zero for a transient
             network failure — that would make an offline dev environment look broken.
    selftest Prove the comparison logic deterministically against fixture version strings — no
             network.

Usage:
    python3 scripts/release_check.py check
    python3 scripts/release_check.py check --repo simpletibr/simplicio-loop --json
    python3 scripts/release_check.py selftest
"""
import json
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_GH_REPO = "simpletibr/simplicio-loop"

_VERSION_RE = re.compile(r'version\s*=\s*"([^"]+)"')
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


def log(msg):
    print(msg, flush=True)


def read_local_version(repo=REPO):
    """The canonical version — same file version_sync.py treats as source of truth."""
    pyproject = os.path.join(repo, "pyproject.toml")
    text = open(pyproject, encoding="utf-8").read()
    m = _VERSION_RE.search(text)
    if not m:
        raise ValueError("no version = \"...\" found in pyproject.toml")
    return m.group(1)


def parse_semver(version):
    """(major, minor, patch) tuple; a version this can't parse sorts as (-1, -1, -1)
    (older than anything real) so a malformed tag never blocks the check silently."""
    m = _SEMVER_RE.match(version.lstrip("v"))
    if not m:
        return (-1, -1, -1)
    return tuple(int(x) for x in m.groups())


def compare_versions(local, remote):
    """Return 'behind' | 'current' | 'ahead' (local vs remote)."""
    local_t, remote_t = parse_semver(local), parse_semver(remote)
    if local_t < remote_t:
        return "behind"
    if local_t > remote_t:
        return "ahead"
    return "current"


def _gh_latest_release_tag(gh_repo):
    try:
        out = subprocess.run(
            ["gh", "release", "view", "--repo", gh_repo, "--json", "tagName"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=15, cwd=REPO,
        )
        if out.returncode != 0:
            return None
        return json.loads(out.stdout).get("tagName")
    except Exception:
        return None


def cmd_check(opts):
    gh_repo = opts.get("repo", DEFAULT_GH_REPO)
    as_json = bool(opts.get("json"))
    try:
        local_version = read_local_version()
    except (OSError, ValueError) as exc:
        payload = {"schema": "simplicio.release-check/v1", "status": "UNVERIFIED",
                  "reason_code": "local_version_unreadable", "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False) if as_json
             else f"UNVERIFIED|{payload['reason_code']}: {exc}")
        return 0

    remote_tag = _gh_latest_release_tag(gh_repo)
    if remote_tag is None:
        payload = {"schema": "simplicio.release-check/v1", "status": "UNVERIFIED",
                  "reason_code": "gh_unavailable", "local_version": local_version}
        print(json.dumps(payload, ensure_ascii=False) if as_json
             else f"UNVERIFIED|release-check: gh unavailable/unauthenticated — "
                  f"local version {local_version}, could not check for a newer release")
        return 0

    remote_version = remote_tag.lstrip("v")
    comparison = compare_versions(local_version, remote_version)
    payload = {
        "schema": "simplicio.release-check/v1",
        "status": "MEASURED",
        "local_version": local_version,
        "latest_release_tag": remote_tag,
        "latest_release_version": remote_version,
        "comparison": comparison,
    }

    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
    elif comparison == "behind":
        print(
            f"MEASURED|release-check: a newer release is available — local {local_version} < "
            f"latest {remote_version}. Update before continuing: "
            f"`bash scripts/update.sh` (or `pip install -U simplicio-loop`), "
            f"then re-verify with `python3 scripts/version_sync.py check`."
        )
    elif comparison == "current":
        print(f"MEASURED|release-check: up to date (local {local_version} == "
             f"latest {remote_version})")
    else:
        print(f"MEASURED|release-check: local {local_version} is ahead of the latest published "
             f"release {remote_version} (expected on a dev checkout before a release is cut)")

    return 10 if comparison == "behind" else 0


def cmd_selftest(_opts):
    checks = []

    def chk(name, got, want):
        checks.append((name, got == want, got, want))

    chk("parse_semver_basic", parse_semver("3.38.0"), (3, 38, 0))
    chk("parse_semver_strips_v_prefix", parse_semver("v3.38.0"), (3, 38, 0))
    chk("parse_semver_malformed_sorts_lowest", parse_semver("not-a-version"), (-1, -1, -1))
    chk("compare_behind", compare_versions("3.37.0", "3.38.0"), "behind")
    chk("compare_current", compare_versions("3.38.0", "3.38.0"), "current")
    chk("compare_ahead", compare_versions("3.39.0", "3.38.0"), "ahead")
    chk("compare_behind_minor", compare_versions("3.9.0", "3.10.0"), "behind")
    chk("compare_malformed_remote_never_blocks_as_behind",
        compare_versions("3.38.0", "not-a-real-tag"), "ahead")

    ok = True
    for name, passed, got, want in checks:
        tag = "PASS" if passed else "FAIL"
        print(f"  [{tag}] {name} (got={got!r} want={want!r})")
        ok = ok and passed

    n = len(checks)
    passed_n = sum(1 for _, p, _, _ in checks if p)
    if ok:
        print(f"MEASURED|release_check selftest: {passed_n}/{n} checks passed")
        return 0
    print(f"UNVERIFIED|release_check selftest: {passed_n}/{n} checks passed (FAILURES ABOVE)")
    return 1


def _parse(args):
    opts = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a[2:]
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                opts[key] = args[i + 1]
                i += 2
            else:
                opts[key] = True
                i += 1
        else:
            i += 1
    return opts


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        sys.exit(2)
    if argv[0] == "--describe-cli":
        print(json.dumps({
            "verbs": ["check", "selftest"],
            "flags": ["--repo", "--json"],
        }))
        sys.exit(0)
    sub, opts = argv[0], _parse(argv[1:])
    handler = {"check": cmd_check, "selftest": cmd_selftest}.get(sub)
    if handler is None:
        print("unknown command '%s'. choices: check selftest" % sub)
        sys.exit(2)
    sys.exit(handler(opts) or 0)


if __name__ == "__main__":
    main()
