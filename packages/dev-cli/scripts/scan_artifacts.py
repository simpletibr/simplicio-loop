#!/usr/bin/env python3
"""Scan built sdist/wheel artifacts for stray legacy-brand mentions (#167).

Issue #167 (Ecosystem Rebrand) step 24 says "Escanear artifacts com regra
Agent #194" — Agent #194 (`wesleysimplicio/simplicio-agent`) is a *sibling
repo's* CI guard that inspects packaged artifacts (wheel/sdist/Electron/
container/installer) for regressed "Hermes" branding, using an
inventory/allowlist so unclassified occurrences fail loudly. That checker
lives in the Agent repo, not here, and this repo has no access to its
allowlist/inventory format.

What this script does instead: it applies *this repo's own* documented
Hermes-mention allowlist (`tests/python/test_naming_contract.py`'s
``ALLOWED_HERMES_FILES``) to the actual contents of the built
`dist/*.whl` / `dist/*.tar.gz` artifacts, not just the source tree. The
naming-contract test already guards the source tree; nothing previously
verified that packaging didn't carry a stray mention into the artifact a
user actually installs (or drop the compat-surface exception files
without noticing the rest of the guard no longer applies to what ships).

This is deliberately narrow and self-contained (stdlib `zipfile`/
`tarfile` + regex, no new dependency): it is not a re-implementation of
Agent #194's contextual/CI-tier scanner (case/spacing variants,
generated-file provenance, false-positive corpus, Windows path/encoding
edge cases, etc. — see that issue's acceptance criteria). Treat this as
the one hop of the plan step this repo can complete on its own; the
sibling repo's specific rule set remains the fuller, authoritative scan.

Usage:
    python3 scripts/scan_artifacts.py --check
        Scans dist/*.whl and dist/*.tar.gz (must already be built via
        `python -m build`). Exit 0 if every "hermes" mention found inside
        the artifacts lives in an allowlisted package file, exit 1 (with
        the offending member paths) otherwise. Exit 1 with a clear message
        if no dist artifacts exist yet.
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist"

HERMES_PATTERN = re.compile(rb"hermes", re.IGNORECASE)

# Package-relative (posix, no version/dist-info prefix) paths allowed to
# carry a "hermes" mention into the built artifact. Mirrors the source-tree
# allowlist in tests/python/test_naming_contract.py's ALLOWED_HERMES_FILES,
# narrowed to the subset of those files that actually get packaged (docs,
# CHANGELOG.md, bench/, and tests/ are not included in the sdist/wheel).
ALLOWED_ARTIFACT_MEMBERS = {
    "simplicio/runtime_contracts.py",
    "simplicio/commands/runtime.py",
    "simplicio/plan_compiler/compat_adapter.py",
}


def _iter_wheel_members(path: Path) -> list[tuple[str, bytes]]:
    members: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue
            members.append((name, z.read(name)))
    return members


def _iter_sdist_members(path: Path) -> list[tuple[str, bytes]]:
    members: list[tuple[str, bytes]] = []
    with tarfile.open(path) as t:
        for member in t.getmembers():
            if not member.isfile():
                continue
            # Strip the leading "<name>-<version>/" prefix sdists wrap
            # everything in, so member paths compare like wheel members.
            rel = member.name.split("/", 1)[1] if "/" in member.name else member.name
            extracted = t.extractfile(member)
            if extracted is None:
                continue
            members.append((rel, extracted.read()))
    return members


def scan_artifact(path: Path) -> list[str]:
    """Return the list of offending member paths (empty if clean)."""
    if path.suffix == ".whl":
        members = _iter_wheel_members(path)
    elif path.name.endswith(".tar.gz"):
        members = _iter_sdist_members(path)
    else:
        raise ValueError(f"unrecognized artifact type: {path}")

    offenders: list[str] = []
    for member_path, data in members:
        if not HERMES_PATTERN.search(data):
            continue
        if member_path in ALLOWED_ARTIFACT_MEMBERS:
            continue
        offenders.append(f"{path.name}:{member_path}")
    return offenders


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if a built artifact contains an unallowlisted 'hermes' mention",
    )
    args = parser.parse_args(argv)

    if not args.check:
        parser.print_help()
        return 0

    artifacts = sorted(DIST_DIR.glob("*.whl")) + sorted(DIST_DIR.glob("*.tar.gz"))
    if not artifacts:
        print(
            "FAIL: no artifacts found in dist/ — build first with:\n"
            "  python -m build\n"
            "then re-run: python3 scripts/scan_artifacts.py --check",
            file=sys.stderr,
        )
        return 1

    offenders: list[str] = []
    for artifact in artifacts:
        offenders.extend(scan_artifact(artifact))

    if offenders:
        print(
            "FAIL: stray 'hermes' mention(s) found in packaged artifact(s) "
            f"outside the documented compat surface: {offenders}\n"
            "Either remove the leftover mention, or — if it genuinely belongs "
            "to the documented N-1/legacy-alias compat surface — add it to "
            "ALLOWED_ARTIFACT_MEMBERS in scripts/scan_artifacts.py (and its "
            "source-tree counterpart in tests/python/test_naming_contract.py).",
            file=sys.stderr,
        )
        return 1

    names = ", ".join(a.name for a in artifacts)
    print(f"OK: no unallowlisted 'hermes' mentions found in {names}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
