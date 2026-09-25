#!/usr/bin/env python3
"""check-version-sync.py — align pyproject.toml and __init__.py.

Two release sources of truth must stay in lockstep (this package is
Python-only; there is no npm/package.json metadata to track):

* pyproject.toml (PyPI / hatch metadata)
* simplicio_mapper/__init__.py (`__version__` fallback string)

Exits 0 when both match, 1 otherwise.

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

PYPROJECT = "pyproject.toml"
INIT_PY = Path("simplicio_mapper") / "__init__.py"

_PYPROJECT_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
# Prefer the first top-level assignment so importlib.metadata overrides later
# in the file do not confuse the static guard.
_INIT_VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)


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
    messages.append("Release bumps must update both files in the same commit:")
    messages.append("  python scripts/check-version-sync.py")
    return False, sources, messages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail if pyproject.toml and simplicio_mapper/__init__.py versions disagree."
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
