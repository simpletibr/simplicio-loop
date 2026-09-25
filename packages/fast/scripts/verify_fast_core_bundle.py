"""Verify the precompiled Rust-core release bundle without a Rust toolchain."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "simplicio.fast.core-verification/v1"
MANIFEST_SCHEMA = "simplicio.fast.engine-manifest/v1"
REQUIRED_CAPABILITIES = frozenset({"stats", "query", "context"})


def verify(
    binary: Path, manifest_path: Path, *, expected_version: str
) -> dict[str, Any]:
    """Validate a staged core binary and its build-time handshake receipt."""
    failures: list[str] = []
    if not binary.is_file():
        failures.append("ARTIFACT_MISSING")
        digest = None
        size = None
    else:
        content = binary.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        size = len(content)
        if not content:
            failures.append("ARTIFACT_EMPTY")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        manifest = {}
        failures.append("MANIFEST_MISSING")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        manifest = {}
        failures.append("MANIFEST_INVALID")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        failures.append("MANIFEST_SCHEMA_MISMATCH")
    if manifest.get("engine") != "rust" or manifest.get("status") != "available":
        failures.append("ENGINE_UNAVAILABLE")
    if manifest.get("version") != expected_version:
        failures.append("VERSION_MISMATCH")
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, list) or not REQUIRED_CAPABILITIES.issubset(
        capabilities
    ):
        failures.append("CAPABILITIES_MISSING")
    conformance = manifest.get("conformance")
    digest_value = conformance.get("digest") if isinstance(conformance, dict) else None
    if (
        not isinstance(conformance, dict)
        or conformance.get("passed") is not True
        or not isinstance(digest_value, str)
        or not digest_value.strip()
    ):
        failures.append("CONFORMANCE_MISSING")
    return {
        "schema": SCHEMA,
        "status": "pass" if not failures else "fail",
        "artifact": str(binary),
        "sha256": digest,
        "size": size,
        "version": expected_version,
        "failures": sorted(set(failures)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    receipt = verify(args.binary, args.manifest, expected_version=args.expected_version)
    print(
        json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        if args.json
        else receipt["status"]
    )
    return int(receipt["status"] != "pass")


if __name__ == "__main__":
    raise SystemExit(main())
