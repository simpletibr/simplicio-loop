#!/usr/bin/env python3
"""Fail-closed inventory gate for Simplicio-owned JSON state."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import tarfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 optional backport
    import tomli as tomllib  # type: ignore[no-redef]

_WILDCARDS = "*?[]{}"
_TARGETS = {"hbp", "hbi", "toml"}


@dataclass(frozen=True)
class Policy:
    roots: tuple[str, ...]
    formats: frozenset[str]
    exceptions: dict[str, dict[str, object]]


def _exact_relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or any(char in value for char in _WILDCARDS):
        raise ValueError(f"{label} requires one exact path (wildcards are forbidden)")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise ValueError(f"{label} must be a normalized repository-relative path")
    return value


def load_policy(root: Path) -> Policy:
    with (root / "config" / "json-boundaries.toml").open("rb") as handle:
        doc = tomllib.load(handle)
    if doc.get("version") != 1 or doc.get("policy") != "internal-json-deny":
        raise ValueError("policy version=1 and policy='internal-json-deny' are required")
    scanner = doc.get("scanner", {})
    roots = tuple(
        _exact_relative_path(item, "each scanner root") for item in scanner.get("internal_roots", [])
    )
    formats = frozenset(str(item).lower() for item in scanner.get("formats", []))
    if not roots or not formats or any(not item.startswith(".") for item in formats):
        raise ValueError("scanner roots and dot-prefixed formats are required")
    exceptions: dict[str, dict[str, object]] = {}
    for raw_entry in doc.get("exceptions", []):
        if not isinstance(raw_entry, dict):
            raise ValueError("each exception must be a TOML table")
        entry = dict(raw_entry)
        path = _exact_relative_path(entry.get("path"), "each exception")
        if path in exceptions:
            raise ValueError(f"duplicate exception: {path}")
        missing = [key for key in ("category", "target", "owner", "reason", "expires") if not entry.get(key)]
        if missing:
            raise ValueError(f"{path}: missing {', '.join(missing)}")
        if entry["target"] not in _TARGETS:
            raise ValueError(f"{path}: target must be one of {sorted(_TARGETS)}")
        if not any(path == item or path.startswith(f"{item}/") for item in roots):
            raise ValueError(f"{path}: exception is outside configured internal roots")
        try:
            dt.date.fromisoformat(str(entry["expires"]))
        except ValueError as error:
            raise ValueError(f"{path}: expires must be an ISO date") from error
        exceptions[path] = entry
    return Policy(roots, formats, exceptions)


def _owned_json(paths: Iterable[str], policy: Policy) -> Iterable[str]:
    for raw_path in paths:
        archive_path = PurePosixPath(raw_path)
        if archive_path.suffix.lower() not in policy.formats:
            continue
        parts = archive_path.parts
        for root in policy.roots:
            root_parts = PurePosixPath(root).parts
            width = len(root_parts)
            if any(parts[index : index + width] == root_parts for index in range(len(parts) - width + 1)):
                yield archive_path.as_posix()
                break


def _archive_paths(path: Path) -> list[str]:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return [item.filename for item in archive.infolist() if not item.is_dir()]
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as archive:
            return [item.name for item in archive.getmembers() if item.isfile()]
    raise ValueError(f"unsupported artifact archive: {path}")


def check(root: Path, artifacts: Iterable[Path] = ()) -> list[str]:
    policy = load_policy(root)
    findings: list[str] = []
    for rel_root in policy.roots:
        directory = root / rel_root
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in policy.formats:
                continue
            rel = path.relative_to(root).as_posix()
            entry = policy.exceptions.get(rel)
            if entry is None:
                findings.append(f"UNCLASSIFIED {rel}")
                continue
            expiry = dt.date.fromisoformat(str(entry["expires"]))
            if expiry < dt.date.today():
                findings.append(f"EXPIRED {rel} ({expiry.isoformat()})")
    for artifact in artifacts:
        for rel in sorted(_owned_json(_archive_paths(artifact), policy)):
            findings.append(f"PACKAGED_INTERNAL_JSON {artifact.name}!{rel}")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--artifact", type=Path, action="append", default=[])
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        action="append",
        default=[],
        help="scan every wheel and source archive in a release directory",
    )
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        artifacts = list(args.artifact)
        for directory in args.artifact_dir:
            if not directory.is_dir():
                raise ValueError(f"artifact directory does not exist: {directory}")
            discovered = [
                path
                for path in sorted(directory.iterdir())
                if path.is_file() and (path.suffix == ".whl" or path.name.endswith(".tar.gz"))
            ]
            if not discovered:
                raise ValueError(f"artifact directory contains no wheel or source archives: {directory}")
            artifacts.extend(discovered)
        findings = check(args.root.resolve(), artifacts)
    except (OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"json-boundaries: configuration error: {error}", file=sys.stderr)
        return 2
    for finding in findings:
        print(finding)
    print(f"json-boundaries: {len(findings)} finding(s); strict={'pass' if not findings else 'blocked'}")
    return 1 if findings and args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
