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



def _parse_hatch_packages_and_force_include(pyproject_text: str) -> tuple[list[str], dict[str, str]]:
    """Parse packages + wheel force-include entries from pyproject.toml text.

    Intentionally small/local (no tomllib dependency on older runtimes beyond
    3.10 — tomllib is stdlib from 3.11; use a line scanner that matches the
    project's current hatch tables only).
    """
    packages: list[str] = []
    force: dict[str, str] = {}
    section: str | None = None
    for raw in pyproject_text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].strip()
            continue
        if section == 'tool.hatch.build.targets.wheel' and line.startswith('packages'):
            # packages = ["a", "b"]
            left, _, right = line.partition('=')
            items = right.strip().strip('[]')
            packages = [p.strip().strip('"').strip("'") for p in items.split(',') if p.strip()]
            continue
        if section == 'tool.hatch.build.targets.wheel.force-include' and '=' in line:
            src, _, dest = line.partition('=')
            force[src.strip().strip('"').strip("'")] = dest.strip().strip('"').strip("'")
    return packages, force


def check_force_include_no_package_overlap(root: str | Path) -> list[str]:
    """Return error strings if force-include re-ships package-internal paths.

    Hatch auto-includes non-Python package data under `packages`. Re-listing
    those paths in force-include produces:
      ValueError: A second file is being added to the wheel archive at the same path
    (issue #553 — neural assets). Only out-of-package trees (e.g. `contracts/`)
    belong in force-include.
    """
    base = Path(root).resolve()
    pyproject = base / 'pyproject.toml'
    packages, force = _parse_hatch_packages_and_force_include(
        pyproject.read_text(encoding='utf-8')
    )
    errors: list[str] = []
    for src, dest in force.items():
        src_norm = src.replace('\\', '/').rstrip('/')
        dest_norm = dest.replace('\\', '/').rstrip('/')
        for pkg in packages:
            pkg_norm = pkg.replace('\\', '/').rstrip('/')
            # Source already lives inside a declared package tree.
            if src_norm == pkg_norm or src_norm.startswith(pkg_norm + '/'):
                errors.append(
                    f'force-include source {src!r} overlaps package {pkg!r} '
                    f'(dest={dest!r}); remove it — Hatch already ships package data '
                    f'(issue #553)'
                )
            # Dest collides with package path that package walk will also emit.
            if dest_norm == pkg_norm or dest_norm.startswith(pkg_norm + '/'):
                # Allow mapping EXTERNAL sources into the package (contracts -> package/contracts).
                if not (src_norm == pkg_norm or src_norm.startswith(pkg_norm + '/')):
                    continue
                errors.append(
                    f'force-include {src!r} -> {dest!r} duplicates package tree {pkg!r} '
                    f'(issue #553)'
                )
    return errors


def build_manifest(root: str | Path, artifacts: list[str | Path] | None = None) -> dict[str, Any]:
    base = Path(root).resolve()
    overlap = check_force_include_no_package_overlap(base)
    if overlap:
        raise ValueError("; ".join(overlap))
    pyproject = base / "pyproject.toml"
    init = base / "simplicio_mapper" / "__init__.py"
    package_version = _version(pyproject, r'^version\s*=\s*"([^"]+)"')
    versions = {
        "pyproject": package_version,
        "python": _version(init, r'__version__\s*=\s*"([^"]+)"'),
    }
    if len({versions[name] for name in ("pyproject", "python")}) != 1:
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
