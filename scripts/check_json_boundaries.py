#!/usr/bin/env python3
"""Fail-closed inventory check for Simplicio-owned JSON state.

This is intentionally a small policy gate, not a serializer.  JSON remains
valid at explicit CLI/export edges, while JSON files below the owned state
roots require an exact, dated migration exception in config/json-boundaries.toml.
The strict gate is safe to run before Runtime HBI/HBP is installed and never
silently treats an unknown artifact as migrated.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 uses the optional backport
    import tomli as tomllib  # type: ignore[no-redef]


def _load(root: Path) -> tuple[list[str], dict[str, dict]]:
    with (root / "config" / "json-boundaries.toml").open("rb") as handle:
        doc = tomllib.load(handle)
    scanner = doc.get("scanner", {})
    exceptions = {}
    for entry in doc.get("exceptions", []):
        path = entry.get("path")
        if not isinstance(path, str) or not path or path in exceptions:
            raise ValueError("exceptions must contain unique exact path values")
        if any(char in path for char in "*?[]"):
            raise ValueError(f"wildcard exception is forbidden: {path}")
        required = ("category", "target", "owner", "reason", "expires")
        missing = [key for key in required if not entry.get(key)]
        if missing:
            raise ValueError(f"{path}: missing {', '.join(missing)}")
        exceptions[path] = entry
    roots = scanner.get("internal_roots", [])
    formats = scanner.get("formats", [])
    if not roots or not formats:
        raise ValueError("scanner.internal_roots and scanner.formats are required")
    return [str(root) for root in roots], {str(k): v for k, v in exceptions.items()}


def _files(root: Path, roots: list[str], formats: list[str] | None = None) -> list[str]:
    formats = formats or [".json", ".jsonl", ".ndjson"]
    result: list[str] = []
    for rel_root in roots:
        directory = root / rel_root
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in formats:
                result.append(path.relative_to(root).as_posix())
    return sorted(result)


def check(root: Path) -> list[str]:
    roots, exceptions = _load(root)
    findings: list[str] = []
    today = dt.date.today()
    with (root / "config" / "json-boundaries.toml").open("rb") as handle:
        formats = tomllib.load(handle).get("scanner", {}).get("formats", [])
    for path in _files(root, roots, formats):
        entry = exceptions.get(path)
        if entry is None:
            findings.append(f"UNCLASSIFIED {path}")
            continue
        try:
            expiry = dt.date.fromisoformat(str(entry["expires"]))
        except ValueError:
            findings.append(f"INVALID_EXPIRY {path}")
            continue
        if expiry < today:
            findings.append(f"EXPIRED {path} ({expiry.isoformat()})")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", type=Path)
    parser.add_argument("--strict", action="store_true", help="return non-zero for policy findings")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        findings = check(root)
    except (OSError, ValueError, KeyError) as error:
        print(f"json-boundaries: configuration error: {error}", file=sys.stderr)
        return 2
    for finding in findings:
        print(finding)
    if findings and args.strict:
        return 1
    print(f"json-boundaries: {len(findings)} finding(s); strict={'pass' if not findings else 'blocked'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
