"""Verify one extracted precompiled native bundle without a Rust toolchain."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

try:
    from scripts.build_native_manifest import ABI, SUPPORTED
except ModuleNotFoundError:  # direct `python scripts/verify_native_bundle.py`
    from build_native_manifest import ABI, SUPPORTED


SCHEMA = "simplicio.fast-native-verification/v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def verify(
    root: Path,
    *,
    expected_platform: str,
    expected_version: str,
) -> dict[str, Any]:
    failures: list[str] = []
    if expected_platform not in SUPPORTED:
        failures.append("PLATFORM_UNSUPPORTED")
    directory = root / ABI.replace("/", "_")
    manifest_path = directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        manifest = {}
        failures.append("MANIFEST_MISSING")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        manifest = {}
        failures.append("MANIFEST_INVALID")
    if manifest.get("abi") != ABI:
        failures.append("ABI_MISMATCH")
    if manifest.get("platform") != expected_platform:
        failures.append("PLATFORM_MISMATCH")
    if manifest.get("version") != expected_version:
        failures.append("VERSION_MISMATCH")
    source_commit = manifest.get("source_commit")
    if not isinstance(source_commit, str) or COMMIT_RE.fullmatch(source_commit) is None:
        failures.append("SOURCE_COMMIT_INVALID")
    filename = manifest.get("filename")
    if not isinstance(filename, str) or not filename or Path(filename).name != filename:
        failures.append("FILENAME_INVALID")
        artifact = None
    else:
        artifact = directory / filename
    if artifact is None or not artifact.is_file():
        failures.append("ARTIFACT_MISSING")
        actual_sha = None
        actual_size = None
    else:
        content = artifact.read_bytes()
        actual_sha = hashlib.sha256(content).hexdigest()
        actual_size = len(content)
        if not content:
            failures.append("ARTIFACT_EMPTY")
    expected_sha = manifest.get("sha256")
    if not isinstance(expected_sha, str) or SHA256_RE.fullmatch(expected_sha) is None:
        failures.append("SHA256_INVALID")
    elif actual_sha != expected_sha:
        failures.append("SHA256_MISMATCH")
    if actual_size != manifest.get("size"):
        failures.append("SIZE_MISMATCH")
    return {
        "schema": SCHEMA,
        "status": "pass" if not failures else "fail",
        "platform": expected_platform,
        "version": expected_version,
        "artifact": str(artifact) if artifact else None,
        "sha256": actual_sha,
        "failures": sorted(set(failures)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected-platform", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    receipt = verify(
        args.root,
        expected_platform=args.expected_platform,
        expected_version=args.expected_version,
    )
    if args.json:
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    else:
        print(f"{receipt['status']}: {receipt['platform']} {receipt['version']}")
    return int(receipt["status"] != "pass")


if __name__ == "__main__":
    raise SystemExit(main())
