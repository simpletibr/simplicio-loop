#!/usr/bin/env python3
"""Fail closed when a tagged Mapper release is internally inconsistent.

The check is intentionally local and deterministic. It validates the tag
identity, the three package-version sources, the generated
``simplicio.component-release/v1`` manifest, and (when supplied) captured PyPI
or GitHub Release JSON. Network access belongs to the release workflow; the
checker accepts captured responses so CI and offline tests exercise the same
rules without inventing registry state.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from simplicio_mapper.release_manifest import (
    RELEASE_MANIFEST_SCHEMA,
    build_release_artifact_digest,
    build_release_manifest,
)

TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+)$")


class ReleaseReconciliationError(ValueError):
    """Raised when a release surface disagrees with the immutable tag."""


def _run_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0 or not result.stdout.strip():
        detail = (result.stderr or "").strip() or "git command failed"
        raise ReleaseReconciliationError(detail)
    return result.stdout.strip()


def _source_versions(root: Path) -> dict[str, str]:
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    init = (root / "simplicio_mapper" / "__init__.py").read_text(encoding="utf-8")
    py_match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    init_match = re.search(r'^__version__\s*=\s*"([^"]+)"', init, re.MULTILINE)
    if not py_match or not init_match or not isinstance(package.get("version"), str):
        raise ReleaseReconciliationError("one or more package version sources is missing")
    return {
        "package.json": package["version"],
        "pyproject.toml": py_match.group(1),
        "simplicio_mapper/__init__.py": init_match.group(1),
    }


def _verify_artifact_assets(root: Path, dist_dir: Path, assets: list[dict[str, Any]]) -> list[str]:
    checked: list[str] = []
    local = {path.name: path for path in dist_dir.glob("*") if path.is_file()}
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            continue
        name = asset["name"]
        path = local.get(name)
        if path is None:
            continue
        digest = asset.get("digest")
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise ReleaseReconciliationError(f"GitHub asset {name!r} has no SHA256 digest")
        import hashlib

        actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            raise ReleaseReconciliationError(f"GitHub asset digest mismatch for {name}")
        checked.append(name)
    return checked


def reconcile_release(
    root: str | Path,
    tag: str,
    *,
    dist_dir: str | Path | None = None,
    manifest_path: str | Path | None = None,
    pypi_metadata_path: str | Path | None = None,
    github_release_path: str | Path | None = None,
) -> dict[str, Any]:
    base = Path(root).resolve()
    match = TAG_RE.fullmatch(tag)
    if not match:
        raise ReleaseReconciliationError("tag must match immutable vX.Y.Z")
    version = match.group(1)
    versions = _source_versions(base)
    if len(set(versions.values())) != 1 or next(iter(versions.values())) != version:
        raise ReleaseReconciliationError(f"version sources do not match {tag}: {versions}")

    head_sha = _run_git(base, "rev-parse", "HEAD")
    tag_sha = _run_git(base, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    if head_sha != tag_sha:
        raise ReleaseReconciliationError(f"HEAD {head_sha} is not the immutable tag target {tag_sha}")

    resolved_dist = Path(dist_dir).resolve() if dist_dir else base / "dist"
    generated = build_release_manifest(root=str(base), dist_dir=str(resolved_dist))
    if generated["schema"] != RELEASE_MANIFEST_SCHEMA:
        raise ReleaseReconciliationError("generated manifest has an unexpected schema")
    if generated["version"] != version or generated["commit_sha"] != head_sha:
        raise ReleaseReconciliationError("generated manifest does not match tag identity")
    if generated["artifact_digest"] != build_release_artifact_digest(generated):
        raise ReleaseReconciliationError("generated release identity digest is not reproducible")

    manifest_source = "generated"
    if manifest_path:
        manifest_source = str(manifest_path)
        captured = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        if captured != generated:
            # ``generated_at`` is presentation-only; every identity field must
            # match, while a captured manifest may have been created earlier.
            for key in generated:
                if key == "generated_at":
                    continue
                if captured.get(key) != generated.get(key):
                    raise ReleaseReconciliationError(f"captured manifest differs in {key}")

    pypi_checked: list[str] = []
    if pypi_metadata_path:
        metadata = json.loads(Path(pypi_metadata_path).read_text(encoding="utf-8"))
        info = metadata.get("info") if isinstance(metadata, dict) else None
        if not isinstance(info, dict) or info.get("version") != version:
            raise ReleaseReconciliationError("captured PyPI metadata does not match the tag version")
        if not isinstance(info.get("name"), str) or info["name"].lower().replace("_", "-") != "simplicio-mapper":
            raise ReleaseReconciliationError("captured PyPI metadata has the wrong package name")
        pypi_files = {item.get("filename"): item for item in metadata.get("urls", []) if isinstance(item, dict)}
        for path in resolved_dist.glob("*"):
            if not path.is_file() or path.name not in pypi_files:
                continue
            expected = pypi_files[path.name].get("digests", {}).get("sha256")
            import hashlib

            if expected != hashlib.sha256(path.read_bytes()).hexdigest():
                raise ReleaseReconciliationError(f"PyPI digest mismatch for {path.name}")
            pypi_checked.append(path.name)

    github_checked: list[str] = []
    if github_release_path:
        release = json.loads(Path(github_release_path).read_text(encoding="utf-8"))
        if release.get("tag_name") != tag or release.get("draft") or release.get("prerelease"):
            raise ReleaseReconciliationError("captured GitHub Release is not the stable requested tag")
        github_checked = _verify_artifact_assets(base, resolved_dist, release.get("assets", []))

    return {
        "schema": "simplicio.mapper-release-reconciliation/v1",
        "tag": tag,
        "version": version,
        "commit_sha": head_sha,
        "versions": versions,
        "manifest": manifest_source,
        "pypi_artifacts_checked": sorted(pypi_checked),
        "github_assets_checked": sorted(github_checked),
        "status": "reconciled",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--dist-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--pypi-metadata", type=Path)
    parser.add_argument("--github-release", type=Path)
    args = parser.parse_args(argv)
    try:
        result = reconcile_release(
            args.root,
            args.tag,
            dist_dir=args.dist_dir,
            manifest_path=args.manifest,
            pypi_metadata_path=args.pypi_metadata,
            github_release_path=args.github_release,
        )
    except (OSError, json.JSONDecodeError, ReleaseReconciliationError, ValueError) as error:
        print(f"[error] {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
