#!/usr/bin/env python3
"""simplicio-loop — canonical product manifest (#294 AC6/AC7).

Before this module, "the source of truth" for the published surface was actually SEVERAL
independent sources of truth, each covering one slice:
  - `scripts/release_manifest.py` / `scripts/version_sync.py` — version numbers only.
  - `scripts/claims_audit.py` (checks 2/6) — extension-point count and skill count, each checked
    against README/AGENTS.md/INSTALL.md/PYPI.md, but NOT against CHANGELOG.md.
  - `scripts/claims_manifest.py` — quantitative claims (percentages) with receipt/unverified
    status.
  - `scripts/mirror_manifest.py` — the lean hook/script/test mirror sets shipped in `_bundle/`
    and `plugin/`.

This module does not replace any of those (they stay the single owners of their own domain data
and logic — re-implementing them here would just create a SECOND drift risk). It is the ONE
place that pulls them together into a single, versioned, machine-readable manifest and adds the
cross-surface checks the issue calls "manifest canônico": the runtime/adapter count, and the
CHANGELOG.md version-drift check that no existing script covered.

Usage:
    python3 scripts/canonical_manifest.py                 # build + print the manifest
    python3 scripts/canonical_manifest.py --json           # machine-readable manifest
    python3 scripts/canonical_manifest.py check            # fail-closed drift gate (exit 1 on
                                                            # any mismatch)
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

if HERE not in sys.path:
    sys.path.insert(0, HERE)

import release_manifest  # noqa: E402
from claims_manifest import CLAIMS  # noqa: E402
from mirror_manifest import LEAN_HOOKS, LEAN_SCRIPTS, LEAN_TESTS  # noqa: E402

SCHEMA = "simplicio.canonical-manifest/v1"

SKILLS_DIR = os.path.join(REPO, ".claude", "skills")
ADAPTERS_DIR = os.path.join(REPO, "adapters")
CHANGELOG_PATH = os.path.join(REPO, "CHANGELOG.md")
MATRIX_PATH = os.path.join(ADAPTERS_DIR, "MATRIX.md")

# `hermes` is the deliberately-kept legacy shim for `simplicio_agent` (#262 rename) — both
# directories exist under adapters/ for the compat window, but they are ONE canonical runtime,
# not two, for the supported-runtime count the README/MATRIX badges advertise. `grok` is a host
# rule shim, not a separate supported runtime entry in that matrix.
ADAPTER_ALIASES = {"hermes": "simplicio_agent"}
ADAPTER_NON_CANONICAL = {"grok"}

CORE_SKILL_NAMES = frozenset({
    "simplicio-loop",
    "simplicio-tasks",
    "simplicio-orient",
    "simplicio-review",
    "simplicio-compress",
    "simplicio-learn",
    "simplicio-autoresearch",
})

RUNTIME_COUNT_RES = [
    re.compile(r"\b(\d{1,2})\s+distinct runtimes", re.I),
    re.compile(r"\b(\d{1,2})\s+runtimes\b", re.I),
    re.compile(r"runtimes-(\d{1,2})%20", re.I),
]

CHANGELOG_VERSION_RE = re.compile(r"^##\s*\[(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\]", re.M)


def _read(path):
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def count_skills():
    if not os.path.isdir(SKILLS_DIR):
        return 0
    return len([n for n in os.listdir(SKILLS_DIR)
                if n in CORE_SKILL_NAMES
                and os.path.isfile(os.path.join(SKILLS_DIR, n, "SKILL.md"))])


def count_runtimes():
    """Canonical runtime count: every directory under adapters/, with legacy-shim aliases
    (hermes -> simplicio_agent) collapsed to their canonical name so a compat shim never
    double-counts a runtime."""
    if not os.path.isdir(ADAPTERS_DIR):
        return 0, []
    dirs = [n for n in os.listdir(ADAPTERS_DIR)
            if n not in ADAPTER_NON_CANONICAL
            and os.path.isdir(os.path.join(ADAPTERS_DIR, n))]
    canonical = sorted({ADAPTER_ALIASES.get(n, n) for n in dirs})
    return len(canonical), canonical


def latest_changelog_version():
    text = _read(CHANGELOG_PATH)
    m = CHANGELOG_VERSION_RE.search(text)
    return m.group(1) if m else None


def _doc_runtime_claims():
    found = {}
    for doc in (os.path.join(REPO, "README.md"), MATRIX_PATH):
        txt = _read(doc)
        for rx in RUNTIME_COUNT_RES:
            for n in rx.findall(txt):
                found.setdefault(int(n), set()).add(os.path.relpath(doc, REPO))
    return found


def build_manifest():
    release = release_manifest.build_manifest(Path(REPO))
    skill_count = count_skills()
    runtime_count, runtime_names = count_runtimes()
    changelog_version = latest_changelog_version()
    claim_statuses = {c["id"]: c["status"] for c in CLAIMS}

    issues = []

    if changelog_version and changelog_version != release["canonical_version"]:
        issues.append(
            "CHANGELOG.md's latest released entry [%s] does not match the canonical version %s "
            "(pyproject.toml)" % (changelog_version, release["canonical_version"]))

    runtime_claims = _doc_runtime_claims()
    if runtime_claims:
        bad = {n: sorted(files) for n, files in runtime_claims.items() if n != runtime_count}
        if bad:
            issues.append(
                "runtime-count claim(s) disagree with adapters/ tree (%d canonical runtimes: %s): %s"
                % (runtime_count, ", ".join(runtime_names), json.dumps(bad)))

    if release["mismatches"] or release["errors"]:
        issues.extend("release-manifest: %s" % m for m in (release["mismatches"] + release["errors"]))

    manifest = {
        "schema": SCHEMA,
        "canonical_version": release["canonical_version"],
        "version_sources": release["sources"],
        "skill_count": skill_count,
        "runtime_count": runtime_count,
        "runtime_names": runtime_names,
        "adapter_aliases": ADAPTER_ALIASES,
        "adapter_non_canonical": sorted(ADAPTER_NON_CANONICAL),
        "changelog_latest_version": changelog_version,
        "quantitative_claims": claim_statuses,
        "lean_mirror": {
            "hooks": LEAN_HOOKS,
            "scripts": LEAN_SCRIPTS,
            "tests": LEAN_TESTS,
        },
        "issues": issues,
        "ready": not issues,
    }
    return manifest


def cmd_check(_args=None):
    manifest = build_manifest()
    if manifest["ready"]:
        print("canonical-manifest: READY (version=%s, skills=%d, runtimes=%d)" % (
            manifest["canonical_version"], manifest["skill_count"], manifest["runtime_count"]))
        return 0
    print("canonical-manifest: BLOCKED")
    for issue in manifest["issues"]:
        print("- %s" % issue)
    return 1


def selftest():
    checks = []
    try:
        manifest = build_manifest()
        checks.append(("build_manifest() returns a dict", isinstance(manifest, dict)))
        checks.append(("skill_count > 0", manifest["skill_count"] > 0))
        checks.append(("runtime_count > 0", manifest["runtime_count"] > 0))
        checks.append(("canonical_version is set", bool(manifest["canonical_version"])))
        checks.append(("lean_mirror has hooks/scripts/tests keys",
                        set(manifest["lean_mirror"]) == {"hooks", "scripts", "tests"}))
    except Exception as exc:  # pragma: no cover - defensive
        checks.append(("build_manifest() raised: %s" % exc, False))
    ok = all(v for _, v in checks)
    for name, v in checks:
        print("  [%s] %s" % ("ok" if v else "XX", name))
    print("canonical_manifest selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None):
    args = list(argv if argv is not None else sys.argv[1:])
    as_json = "--json" in args
    if args and args[0] == "check":
        return cmd_check(args[1:])
    manifest = build_manifest()
    if as_json:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        print("=== canonical manifest (#294) ===")
        print("version: %s" % manifest["canonical_version"])
        print("skills: %d" % manifest["skill_count"])
        print("runtimes: %d (%s)" % (manifest["runtime_count"], ", ".join(manifest["runtime_names"])))
        print("changelog latest: %s" % manifest["changelog_latest_version"])
        print("ready: %s" % manifest["ready"])
        for issue in manifest["issues"]:
            print("- %s" % issue)
    return 0 if manifest["ready"] else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        sys.exit(selftest())
    if len(sys.argv) > 1 and sys.argv[1] == "--describe-cli":
        print(json.dumps({
            "verbs": ["check", "selftest"],
            "flags": ["--json", "--describe-cli"],
        }))
        sys.exit(0)
    sys.exit(main())
