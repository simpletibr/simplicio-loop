#!/usr/bin/env python3
"""Build the authenticated, idempotent release event for Mapper consumers.

The script does not send network requests. It converts a verified component
manifest into a stable GitHub ``repository_dispatch`` payload. An authenticated
manual release caller sends it only after registry and promotion gates pass.
Consumers can deduplicate retries using ``event_id``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

EVENT_SCHEMA = "simplicio.component-release-event/v1"
EVENT_TYPE = "simplicio-component-release"
CONSUMERS = (
    "wesleysimplicio/simplicio-dev-cli",
    "wesleysimplicio/simplicio-loop",
)


class ReleaseEventError(ValueError):
    """Raised when a release manifest is not dispatchable."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def build_release_event(
    manifest: dict[str, Any],
    *,
    channel: str = "canary",
) -> dict[str, Any]:
    if channel not in {"canary", "stable"}:
        raise ReleaseEventError("channel must be canary or stable")
    if manifest.get("schema") != "simplicio.component-release/v1":
        raise ReleaseEventError("manifest schema is not simplicio.component-release/v1")
    required = ("component", "version", "commit_sha", "artifact_digest", "schema_versions", "capabilities", "compatibility")
    if any(not manifest.get(key) for key in required):
        raise ReleaseEventError("manifest is missing a release identity field")
    signing = manifest.get("signing", {})
    signed = False
    if signing.get("status") == "signed":
        from simplicio_mapper.release_governance import verify_release_manifest_signature

        signed = verify_release_manifest_signature(manifest)
    if channel == "stable" and (not signed or not signing.get("sbom")):
        raise ReleaseEventError(
            "stable release events require a valid Ed25519 signature and CycloneDX SBOM digest"
        )
    attestation = "ed25519-signed" if signed else "transport-authenticated-only"
    identity = {
        "component": manifest["component"],
        "version": manifest["version"],
        "commit_sha": manifest["commit_sha"],
        "artifact_digest": manifest["artifact_digest"],
    }
    event_id = _sha256(identity)
    event = {
        "schema": EVENT_SCHEMA,
        "event_type": EVENT_TYPE,
        "event_id": event_id,
        "dedupe_key": event_id,
        "component": manifest["component"],
        "version": manifest["version"],
        "commit_sha": manifest["commit_sha"],
        "release_manifest_schema": manifest["schema"],
        "release_manifest_digest": manifest["artifact_digest"],
        "artifact_digests": manifest.get("artifact_digests", {}),
        "schema_versions": manifest["schema_versions"],
        "capabilities": manifest["capabilities"],
        "compatibility": manifest["compatibility"],
        "attestation": attestation,
        "delivery": {
            "transport": "github.repository_dispatch",
            "authentication": "github-token",
            "secret_name": "RELEASE_TRAIN_DISPATCH_TOKEN",
            "retry_safe": True,
            "consumer_ack_deadline_minutes": 15,
            "channel": channel,
            "stable_requires_consumer_ack": True,
        },
        "consumers": [
            {"repository": repository, "action": "update", "event_type": EVENT_TYPE}
            for repository in CONSUMERS
        ],
        "rollback": {
            "supported": True,
            "strategy": "revoke-current-and-restore-previous-pin",
            "command": "simplicio-mapper release-governance rollback",
            "immutable_artifacts_retained": True,
            "note": "Consumers apply the deterministic rollback plan and deduplicate its immutable event identifier.",
        },
    }
    return event


def github_dispatch_payload(event: dict[str, Any]) -> dict[str, Any]:
    return {"event_type": EVENT_TYPE, "client_payload": event}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-dispatch-payload", action="store_true")
    parser.add_argument("--channel", choices=("canary", "stable"), default="canary")
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        event = build_release_event(manifest, channel=args.channel)
        output = github_dispatch_payload(event) if args.github_dispatch_payload else event
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, ReleaseEventError, TypeError) as error:
        print(f"[error] {error}", file=sys.stderr)
        return 1
    print(f"[ok] wrote {event['schema']} {event['event_id']} to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
