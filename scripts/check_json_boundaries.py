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
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 uses the optional backport
    import tomli as tomllib  # type: ignore[no-redef]


_ALLOWED_TARGETS = {"hbi", "hbp", "toml"}


def _load(root: Path) -> tuple[list[str], list[str], dict[str, dict]]:
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
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"exception path must be repository-relative: {path}")
        required = ("category", "target", "owner", "reason", "expires")
        missing = [key for key in required if not entry.get(key)]
        if missing:
            raise ValueError(f"{path}: missing {', '.join(missing)}")
        if entry["target"] not in _ALLOWED_TARGETS:
            raise ValueError(f"{path}: unsupported target {entry['target']}")
        try:
            entry["expires"] = dt.date.fromisoformat(str(entry["expires"]))
        except ValueError as error:
            raise ValueError(f"{path}: expires must be an ISO date") from error
        exceptions[path] = entry
    roots = scanner.get("internal_roots", [])
    formats = scanner.get("formats", [])
    if not roots or not formats:
        raise ValueError("scanner.internal_roots and scanner.formats are required")
    return (
        [str(item) for item in roots],
        [str(item).lower() for item in formats],
        {str(k): v for k, v in exceptions.items()},
    )


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


def check(root: Path, *, mode: str = "baseline") -> list[str]:
    """Return policy findings.

    ``baseline`` permits only exact, live migration exceptions. ``strict`` is
    the release state: owned JSON is forbidden even when it is inventoried.
    """
    if mode not in {"baseline", "strict"}:
        raise ValueError(f"unsupported mode: {mode}")
    roots, formats, exceptions = _load(root)
    findings: list[str] = []
    today = dt.date.today()
    files = _files(root, roots, formats)
    for path in files:
        entry = exceptions.get(path)
        if entry is None:
            findings.append(f"UNCLASSIFIED {path}")
            continue
        try:
            expiry = entry["expires"]
        except KeyError:
            findings.append(f"INVALID_EXPIRY {path}")
            continue
        if expiry < today:
            findings.append(f"EXPIRED {path} ({expiry.isoformat()})")
        elif mode == "strict":
            findings.append(f"INTERNAL_JSON {path}")
    for path in sorted(set(exceptions) - set(files)):
        findings.append(f"STALE_EXCEPTION {path}")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", type=Path)
    parser.add_argument("--mode", choices=("baseline", "strict"), default="baseline")
    parser.add_argument("--strict", action="store_true", help="deprecated alias for --mode strict")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        mode = "strict" if args.strict else args.mode
        findings = check(root, mode=mode)
    except (OSError, ValueError, KeyError) as error:
        print(f"json-boundaries: configuration error: {error}", file=sys.stderr)
        return 2
    for finding in findings:
        print(finding)
    if findings:
        print(f"json-boundaries: {len(findings)} finding(s); {mode}=blocked")
        return 1
    print(f"json-boundaries: 0 finding(s); {mode}=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
