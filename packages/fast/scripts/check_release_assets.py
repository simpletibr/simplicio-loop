"""Fail-closed verification for Python release assets and their PyPI digests."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import tarfile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile


SCHEMA = "simplicio.fast.release-assets/v1"
PROJECT = "simplicio-fast"
NORMALIZED_PROJECT = "simplicio_fast"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
WHEEL_RE = re.compile(r"^simplicio_fast-(?P<version>[^-]+)-.+\.whl$")
SDIST_RE = re.compile(r"^simplicio[_-]fast-(?P<version>[^-]+)\.tar\.gz$")


@dataclass(frozen=True)
class Asset:
    name: str
    kind: str
    version: str
    size: int
    sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "sha256": self.sha256,
            "size": self.size,
            "version": self.version,
        }


class GateError(ValueError):
    """Raised when a release asset gate cannot prove a valid publication."""


def _metadata(raw: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        key, separator, value = line.partition(":")
        if separator and key in {"Name", "Version"}:
            values[key] = value.strip()
    return values


def _wheel_metadata(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        candidates = [
            name for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        if len(candidates) != 1:
            raise GateError(f"{path.name}: expected one wheel METADATA file")
        return _metadata(archive.read(candidates[0]))


def _sdist_metadata(path: Path) -> dict[str, str]:
    with tarfile.open(path, mode="r:gz") as archive:
        candidates = [
            member for member in archive.getmembers()
            if (member.name.endswith("/PKG-INFO") or member.name == "PKG-INFO")
            and member.name.count("/") <= 1
        ]
        if len(candidates) != 1:
            raise GateError(f"{path.name}: expected one sdist PKG-INFO file")
        handle = archive.extractfile(candidates[0])
        if handle is None:
            raise GateError(f"{path.name}: PKG-INFO is not readable")
        return _metadata(handle.read())


def _asset(path: Path, expected_version: str) -> Asset:
    if path.name.endswith(".whl"):
        match = WHEEL_RE.fullmatch(path.name)
        kind = "wheel"
        metadata = _wheel_metadata(path)
    elif path.name.endswith(".tar.gz"):
        match = SDIST_RE.fullmatch(path.name)
        kind = "sdist"
        metadata = _sdist_metadata(path)
    else:
        raise GateError(f"unsupported release file: {path.name}")
    if match is None:
        raise GateError(f"{path.name}: filename does not identify {PROJECT}")
    version = match.group("version")
    if version != expected_version:
        raise GateError(
            f"{path.name}: filename version {version!r} != {expected_version!r}"
        )
    if metadata.get("Name", "").lower().replace("-", "_") != NORMALIZED_PROJECT:
        raise GateError(f"{path.name}: package metadata name is not {PROJECT}")
    if metadata.get("Version") != expected_version:
        raise GateError(f"{path.name}: embedded metadata version mismatch")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return Asset(path.name, kind, version, size, digest.hexdigest())


def inspect_dist(dist: Path, expected_version: str) -> list[Asset]:
    if not dist.is_dir():
        raise GateError(f"distribution directory does not exist: {dist}")
    paths = sorted(
        path for path in dist.iterdir()
        if path.is_file() and (path.name.endswith(".whl") or path.name.endswith(".tar.gz"))
    )
    if not paths:
        raise GateError("distribution directory contains no wheel or sdist")
    assets = [_asset(path, expected_version) for path in paths]
    if not any(asset.kind == "wheel" for asset in assets):
        raise GateError("distribution is missing a wheel")
    if not any(asset.kind == "sdist" for asset in assets):
        raise GateError("distribution is missing an sdist")
    if len({asset.name for asset in assets}) != len(assets):
        raise GateError("distribution contains duplicate asset names")
    return assets


def _canonical_assets(assets: list[Asset]) -> list[dict[str, Any]]:
    return [asset.as_dict() for asset in sorted(assets, key=lambda item: item.name)]


def _digest(assets: list[Asset]) -> str:
    encoded = json.dumps(
        _canonical_assets(assets), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def receipt(
    assets: list[Asset], expected_version: str, source_commit: str | None
) -> dict[str, Any]:
    if source_commit is not None and not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise GateError("source commit must be a 40-character lowercase SHA")
    return {
        "artifact_digest": _digest(assets),
        "artifacts": _canonical_assets(assets),
        "project": PROJECT,
        "schema": SCHEMA,
        "source_commit": source_commit,
        "status": "pass",
        "version": expected_version,
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GateError(f"invalid manifest: {path}") from error
    if not isinstance(value, dict):
        raise GateError(f"manifest must be an object: {path}")
    return value


def verify_manifest(path: Path, expected: dict[str, Any]) -> None:
    observed = _load_json(path)
    for key in ("schema", "project", "version", "source_commit", "artifacts", "artifact_digest"):
        if observed.get(key) != expected.get(key):
            raise GateError(f"manifest mismatch for {key}: {path}")


def verify_pypi(
    manifest: dict[str, Any], url: str, *, retries: int, delay_seconds: float
) -> dict[str, Any]:
    import time

    expected_names = {
        item["name"]: item["sha256"] for item in manifest["artifacts"]
    }
    last_error = "pypi metadata unavailable"
    for attempt in range(1, retries + 1):
        try:
            request = Request(url, headers={"Accept": "application/json"})
            with urlopen(request, timeout=20) as response:
                payload = json.load(response)
            observed = {
                item["filename"]: item.get("digests", {}).get("sha256")
                for item in payload.get("urls", [])
                if isinstance(item, dict) and item.get("filename") in expected_names
            }
            version = payload.get("info", {}).get("version")
            if version != manifest["version"]:
                raise GateError(f"PyPI version {version!r} != {manifest['version']!r}")
            missing = sorted(set(expected_names) - set(observed))
            mismatched = sorted(
                name for name, digest in expected_names.items()
                if observed.get(name) != digest
            )
            if missing or mismatched:
                raise GateError(
                    f"PyPI asset digest mismatch; missing={missing}, mismatched={mismatched}"
                )
            return {"attempt": attempt, "status": "pass", "url": url}
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, GateError) as error:
            last_error = str(error)
            if attempt < retries:
                time.sleep(delay_seconds)
    raise GateError(f"PyPI verification failed after {retries} attempts: {last_error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--write-manifest", type=Path)
    parser.add_argument("--verify-manifest", type=Path)
    parser.add_argument("--pypi-url")
    parser.add_argument("--pypi-retries", type=int, default=12)
    parser.add_argument("--pypi-delay", type=float, default=5.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        assets = inspect_dist(args.dist, args.expected_version)
        result = receipt(assets, args.expected_version, args.source_commit)
        if args.write_manifest is not None:
            args.write_manifest.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        if args.verify_manifest is not None:
            verify_manifest(args.verify_manifest, result)
        if args.pypi_url:
            result["pypi"] = verify_pypi(
                result,
                args.pypi_url,
                retries=max(1, args.pypi_retries),
                delay_seconds=max(0.0, args.pypi_delay),
            )
    except GateError as error:
        result = {"schema": SCHEMA, "status": "fail", "error": str(error)}
        if args.json:
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        else:
            print(f"fail: {error}")
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print(f"pass: {PROJECT} {args.expected_version} {result['artifact_digest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
