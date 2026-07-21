#!/usr/bin/env python3
"""Fail-closed inventory gate for Simplicio-owned CLI state files."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 optional backport
    import tomli as tomllib  # type: ignore[no-redef]


def _config(root: Path):
    with (root / "config" / "json-boundaries.toml").open("rb") as handle:
        doc = tomllib.load(handle)
    scanner = doc.get("scanner", {})
    roots = [str(item) for item in scanner.get("internal_roots", [])]
    formats = [str(item) for item in scanner.get("formats", [])]
    exceptions = {}
    for entry in doc.get("exceptions", []):
        path = entry.get("path")
        if not isinstance(path, str) or not path or any(c in path for c in "*?[]"):
            raise ValueError("each exception requires one exact path (wildcards are forbidden)")
        if path in exceptions:
            raise ValueError(f"duplicate exception: {path}")
        missing = [key for key in ("category", "target", "owner", "reason", "expires") if not entry.get(key)]
        if missing:
            raise ValueError(f"{path}: missing {', '.join(missing)}")
        exceptions[path] = entry
    if not roots or not formats:
        raise ValueError("scanner roots and formats are required")
    return roots, formats, exceptions


def check(root: Path) -> list[str]:
    roots, formats, exceptions = _config(root)
    findings = []
    for rel_root in roots:
        directory = root / rel_root
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in formats:
                continue
            rel = path.relative_to(root).as_posix()
            entry = exceptions.get(rel)
            if entry is None:
                findings.append(f"UNCLASSIFIED {rel}")
                continue
            try:
                expiry = dt.date.fromisoformat(str(entry["expires"]))
            except ValueError:
                findings.append(f"INVALID_EXPIRY {rel}")
            else:
                if expiry < dt.date.today():
                    findings.append(f"EXPIRED {rel} ({expiry.isoformat()})")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        findings = check(args.root.resolve())
    except (OSError, ValueError, KeyError) as error:
        print(f"json-boundaries: configuration error: {error}", file=sys.stderr)
        return 2
    for finding in findings:
        print(finding)
    print(f"json-boundaries: {len(findings)} finding(s); strict={'pass' if not findings else 'blocked'}")
    return 1 if findings and args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
