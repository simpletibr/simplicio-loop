#!/usr/bin/env python3
"""Build the signed/provenance-carrying Dev CLI release manifest.

The release workflow supplies the signature, SBOM digest, and provenance
reference from its configured release system. This script only hashes the
bytes in ``dist`` and assembles the versioned manifest; it never invents an
attestation when one is absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from simplicio.component_manifest import (
    COMPONENT_MANIFEST_SCHEMA,
    declared_dependency_range,
    declared_own_version,
    own_commit,
    own_schema_versions,
)

REPOSITORY = "wesleysimplicio/simplicio-dev-cli"


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def build_manifest(
    root: Path,
    artifact_dir: Path,
    *,
    channel: str,
    signature: str,
    sbom: str,
    provenance: str,
    changelog: list[str],
) -> dict[str, Any]:
    """Build a Loop-compatible component-release manifest."""
    version = declared_own_version(root)
    commit = own_commit(root)
    if not version or not commit:
        raise ValueError("release manifest requires a project version and git commit")
    if channel not in {"canary", "stable"}:
        raise ValueError("channel must be canary or stable")
    if not signature or not sbom or not provenance:
        raise ValueError("signature, SBOM digest, and provenance are required")
    if not signature.startswith("base64:"):
        raise ValueError("signature must use the base64: Ed25519 representation")
    if not sbom.startswith("sha256:"):
        raise ValueError("sbom must be a sha256 digest")
    artifacts = []
    for path in sorted(artifact_dir.glob("*.whl")) + sorted(artifact_dir.glob("*.tar.gz")):
        artifacts.append(
            {
                "registry": "pypi",
                "os": "any",
                "arch": "any",
                "digest": _digest(path),
                "size": path.stat().st_size,
                "signature": signature,
                "sbom": sbom,
                "provenance": provenance,
            }
        )
    if not artifacts:
        raise ValueError(f"no wheel or sdist found in {artifact_dir}")
    return {
        "schema": COMPONENT_MANIFEST_SCHEMA,
        "component": "simplicio-dev-cli",
        "repository": REPOSITORY,
        "repo": REPOSITORY,
        "package": "simplicio-cli",
        "version": version,
        "commit": commit,
        "commit_sha": commit,
        "tag": f"v{version}",
        "artifacts": artifacts,
        "schema_versions": own_schema_versions(root),
        "compatibility": {
            "simplicio-mapper": declared_dependency_range("simplicio-mapper", root),
            "simplicio-loop": "component-release/v1",
        },
        "breaking_change": False,
        "changelog": changelog or [f"Release simplicio-cli {version}"],
        "channel": channel,
        "signing": {
            "status": "signed",
            "signature": signature,
            "sbom": sbom,
            "provenance": provenance,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--artifact-dir", type=Path, default=Path("dist"))
    parser.add_argument("--channel", choices=("canary", "stable"), default="stable")
    parser.add_argument("--signature", default=os.environ.get("DEV_CLI_RELEASE_SIGNATURE", ""))
    parser.add_argument("--sbom", default=os.environ.get("DEV_CLI_RELEASE_SBOM", ""))
    parser.add_argument("--provenance", default=os.environ.get("DEV_CLI_RELEASE_PROVENANCE", ""))
    parser.add_argument("--changelog", action="append", default=[])
    parser.add_argument("--output", type=Path, default=Path("dist/component-release.json"))
    args = parser.parse_args(argv)
    try:
        payload = build_manifest(
            args.root.resolve(),
            (
                args.root / args.artifact_dir if not args.artifact_dir.is_absolute() else args.artifact_dir
            ).resolve(),
            channel=args.channel,
            signature=args.signature,
            sbom=args.sbom,
            provenance=args.provenance,
            changelog=args.changelog,
        )
        output = args.output if args.output.is_absolute() else args.root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {"schema": payload["schema"], "status": "built", "output": str(output)}, sort_keys=True
            )
        )
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"schema": COMPONENT_MANIFEST_SCHEMA, "status": "blocked", "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
