#!/usr/bin/env python3
"""check-version-sync.py — align package.json, pyproject.toml, and __init__.py.

Three release sources of truth must stay in lockstep:

* package.json (npm metadata)
* pyproject.toml (PyPI / hatch metadata)
* simplicio_mapper/__init__.py (`__version__` fallback string)

Exits 0 when all three match, 1 otherwise. Preferred over the legacy
`scripts/check-version-sync.js` sibling (same contract). Wire into CI via
`.github/workflows/version-sync.yml` so a partial version bump fails on PR.

Usage:
    python scripts/check-version-sync.py
    python scripts/check-version-sync.py --root /path/to/repo
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PACKAGE_JSON = "package.json"
PYPROJECT = "pyproject.toml"
INIT_PY = Path("simplicio_mapper") / "__init__.py"

_PYPROJECT_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
# Prefer the first top-level assignment so importlib.metadata overrides later
# in the file do not confuse the static guard.
_INIT_VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)


def read_package_json_version(root: Path) -> str:
    data = json.loads((root / PACKAGE_JSON).read_text(encoding="utf-8"))
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"could not find non-empty string version in {PACKAGE_JSON}")
    return version.strip()


def read_pyproject_version(root: Path) -> str:
    text = (root / PYPROJECT).read_text(encoding="utf-8")
    match = _PYPROJECT_VERSION_RE.search(text)
    if match is None:
        raise ValueError(f'could not find `version = "..."` in {PYPROJECT}')
    return match.group(1)


def read_init_version(root: Path) -> str:
    text = (root / INIT_PY).read_text(encoding="utf-8")
    match = _INIT_VERSION_RE.search(text)
    if match is None:
        raise ValueError(f'could not find `__version__ = "..."` in {INIT_PY.as_posix()}')
    return match.group(1)


def collect_versions(root: Path) -> dict[str, str]:
    return {
        PACKAGE_JSON: read_package_json_version(root),
        PYPROJECT: read_pyproject_version(root),
        INIT_PY.as_posix(): read_init_version(root),
    }


def check_versions(root: Path) -> tuple[bool, dict[str, str], list[str]]:
    """Return (ok, sources, messages)."""
    sources = collect_versions(root)
    unique = set(sources.values())
    if len(unique) == 1:
        version = next(iter(unique))
        return True, sources, [f"[ok] version {version} aligned across {len(sources)} sources"]
    messages = ["[err] version mismatch across release sources:"]
    width = max(len(name) for name in sources)
    for name, value in sources.items():
        messages.append(f"  {name.ljust(width)}  {value}")
    messages.append("")
    messages.append("Release bumps must update all three files in the same commit.")
    messages.append("See .specs/workflow/RELEASE.md (version bump checklist) and run:")
    messages.append("  python scripts/check-version-sync.py")
    return False, sources, messages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail if package.json, pyproject.toml, and "
            "simplicio_mapper/__init__.py versions disagree."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="repository root (default: parent of scripts/)",
    )
    args = parser.parse_args(argv)
    root = (args.root or Path(__file__).resolve().parent.parent).resolve()
    try:
        ok, _sources, messages = check_versions(root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[err] {error}", file=sys.stderr)
        return 1
    stream = sys.stdout if ok else sys.stderr
    for line in messages:
        print(line, file=stream)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
