#!/usr/bin/env python3
"""Fail-closed inventory gate for Simplicio Loop-owned JSON state."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 optional backport
    import tomli as tomllib  # type: ignore[no-redef]

# A registry entry is a permanent classification of one exact file. It has no expiry and no
# migration target: any other key is rejected, so a dated waiver can never turn the inventory
# red on a calendar date. The dev-cli registry uses the same key set.
_ENTRY_KEYS = frozenset({"path", "category", "owner", "reason"})
_REQUIRED_KEYS = ("category", "owner", "reason")


def _config(root: Path):
    with (root / "config" / "json-boundaries.toml").open("rb") as handle:
        doc = tomllib.load(handle)
    scanner = doc.get("scanner", {})
    roots = [str(item) for item in scanner.get("internal_roots", [])]
    formats = [str(item) for item in scanner.get("formats", [])]
    exceptions = {}
    for entry in doc.get("exceptions", []):
        path = entry.get("path")
        if (
            not isinstance(path, str)
            or not path
            or path.endswith("/")
            or any(c in path for c in "*?[]")
        ):
            raise ValueError(
                "each exception requires one exact path (wildcards and directory entries are forbidden)"
            )
        if path in exceptions:
            raise ValueError(f"duplicate exception: {path}")
        unsupported = sorted(set(entry) - _ENTRY_KEYS)
        if unsupported:
            raise ValueError(
                f"{path}: unsupported keys {', '.join(unsupported)}; "
                "exceptions are permanent classifications with no expiry or migration target"
            )
        missing = [key for key in _REQUIRED_KEYS if not entry.get(key)]
        if missing:
            raise ValueError(f"{path}: missing {', '.join(missing)}")
        exceptions[path] = entry
    if not roots or not formats:
        raise ValueError("scanner roots and formats are required")
    return roots, formats, exceptions


def _tracked_paths(root: Path, roots: list[str]) -> set[str] | None:
    """Return the Git inventory, or None when root is not a Git worktree."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", *roots],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return {
        path.decode("utf-8", errors="surrogateescape")
        for path in result.stdout.split(b"\0")
        if path
    }


def check(root: Path) -> list[str]:
    roots, formats, exceptions = _config(root)
    tracked = _tracked_paths(root, roots)
    findings = []
    for rel_root in roots:
        directory = root / rel_root
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in formats:
                continue
            rel = path.relative_to(root).as_posix()
            if tracked is not None and rel not in tracked:
                continue
            if rel not in exceptions:
                findings.append(f"UNCLASSIFIED {rel}")
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
    print(
        f"json-boundaries: {len(findings)} finding(s); strict={'pass' if not findings else 'blocked'}"
    )
    return 1 if findings and args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
