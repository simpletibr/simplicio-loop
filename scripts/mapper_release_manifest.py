#!/usr/bin/env python3
"""Build and validate a reproducible, hash-bound Mapper release manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.mapper-release-manifest/v1"


def _reproducibility_key(manifest: dict[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("reproducibility_key", None)
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _version(path: Path, pattern: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise ValueError(f"version missing in {path}")
    return match.group(1)


def _commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise ValueError("git commit is unavailable")
    return result.stdout.strip()


def build_manifest(root: str | Path, artifacts: list[str | Path] | None = None) -> dict[str, Any]:
    base = Path(root).resolve()
    pyproject = base / "pyproject.toml"
    package = base / "package.json"
    init = base / "simplicio_mapper" / "__init__.py"
    cargo = base / "rust" / "Cargo.toml"
    package_version = _version(pyproject, r'^version\s*=\s*"([^"]+)"')
    versions = {
        "pyproject": package_version,
        "package_json": _version(package, r'"version"\s*:\s*"([^"]+)"'),
        "python": _version(init, r'__version__\s*=\s*"([^"]+)"'),
        "rust_crate": _version(cargo, r'^version\s*=\s*"([^"]+)"'),
    }
    if len({versions[name] for name in ("pyproject", "package_json", "python")}) != 1:
        raise ValueError(f"publish version drift: {versions}")
    artifact_rows = []
    for raw_path in artifacts or []:
        path = Path(raw_path)
        if not path.is_absolute():
            path = base / path
        path = path.resolve()
        if not path.is_file():
            raise ValueError(f"artifact missing: {path}")
        artifact_rows.append({"path": str(path.relative_to(base)), "sha256": _sha256(path), "bytes": path.stat().st_size})
    artifact_rows.sort(key=lambda item: item["path"])
    manifest = {
        "schema": SCHEMA,
        "package": "simplicio-mapper",
        "version": package_version,
        "commit": _commit(base),
        "versions": versions,
        "artifacts": artifact_rows,
    }
    manifest["reproducibility_key"] = _reproducibility_key(manifest)
    return manifest


def validate_manifest(root: str | Path, manifest: dict[str, Any]) -> None:
    if (
        manifest.get("schema") != SCHEMA
        or not manifest.get("commit")
        or manifest.get("reproducibility_key") != _reproducibility_key(manifest)
    ):
        raise ValueError("invalid release manifest schema or commit")
    for artifact in manifest.get("artifacts", []):
        path = Path(root) / artifact["path"]
        if not path.is_file() or _sha256(path) != artifact.get("sha256"):
            raise ValueError(f"artifact checksum mismatch: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    manifest = build_manifest(args.root, args.artifact)
    validate_manifest(args.root, manifest)
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
