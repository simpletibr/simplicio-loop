#!/usr/bin/env python3
"""Fail-closed parity gate for every published simplicio-loop surface."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA = "simplicio.release-manifest/v1"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def _pyproject_version(path: Path) -> str:
    match = re.search(r"(?m)^version\s*=\s*[\"']([^\"']+)[\"']", path.read_text())
    if not match:
        raise ValueError("pyproject.toml has no project version")
    return match.group(1)


def _json_version(path: Path) -> str:
    try:
        value = json.loads(path.read_text()).get("version")
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} has no version")
    return value


def _fallback_versions(path: Path) -> List[str]:
    return re.findall(r"__version__\s*=\s*[\"']([^\"']+)[\"']", path.read_text())


def build_manifest(repo: Path, *, tag: Optional[str] = None) -> Dict[str, Any]:
    sources = {
        "pyproject": (repo / "pyproject.toml", _pyproject_version),
        "cursor_plugin": (repo / ".cursor-plugin" / "plugin.json", _json_version),
    }
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    for name, (path, reader) in sources.items():
        try:
            version = reader(path)
        except (OSError, ValueError) as exc:
            version = ""
            errors.append(str(exc))
        rows.append({"name": name, "path": str(path.relative_to(repo)), "version": version})
    fallback_path = repo / "simplicio_loop" / "__init__.py"
    try:
        fallbacks = _fallback_versions(fallback_path)
    except OSError as exc:
        fallbacks = []
        errors.append(str(exc))
    rows.append({"name": "source_fallback", "path": str(fallback_path.relative_to(repo)),
                 "versions": fallbacks, "version": fallbacks[0] if fallbacks else ""})
    canonical = rows[0]["version"]
    versions = [row["version"] for row in rows if row.get("version")]
    mismatches = [row["name"] for row in rows if row.get("version") != canonical]
    if any(not VERSION_RE.match(version) for version in versions):
        errors.append("all release versions must be semantic MAJOR.MINOR.PATCH")
    if len(set(fallbacks)) != 1 or (fallbacks and fallbacks[0] != canonical):
        mismatches.append("source_fallback")
    tag_version = tag[1:] if tag and tag.startswith("v") else tag
    if tag and (not tag.startswith("v") or tag_version != canonical):
        errors.append(f"tag {tag!r} does not match v{canonical}")
    return {"schema": SCHEMA, "canonical_version": canonical, "tag": tag or "",
            "sources": rows, "mismatches": sorted(set(mismatches)), "errors": errors,
            "ready": bool(canonical) and not mismatches and not errors}


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="release_manifest")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--tag", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = build_manifest(Path(args.repo).resolve(), tag=args.tag)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(f"release manifest: {'READY' if report['ready'] else 'BLOCKED'}")
        for item in report["sources"]:
            print(f"- {item['name']}: {item.get('version') or 'missing'}")
        for error in report["errors"] + report["mismatches"]:
            print(f"- error: {error}")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())