"""Fail-closed release-train governance for Simplicio Mapper.

This module owns deterministic, side-effect-free release decisions. Network
polling and publication stay in authenticated callers, while the same inputs
always produce the same parity, compatibility, reconciliation, promotion, and
rollback receipts.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import copy
import hashlib
import json
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

GOVERNANCE_SCHEMA = "simplicio.release-governance/v1"
_SBOM_FORMAT = "CycloneDX"
_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class ReleaseGovernanceError(ValueError):
    """Raised when release evidence is malformed or cryptography is unavailable."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _semver_key(version: str) -> tuple[int, int, int]:
    match = _SEMVER_RE.fullmatch(version)
    if match is None:
        raise ReleaseGovernanceError(f"invalid semantic version: {version!r}")
    return tuple(int(part) for part in match.groups())


def _require_manifest(manifest: Mapping[str, Any]) -> None:
    required = (
        "schema",
        "component",
        "version",
        "commit_sha",
        "artifact_digest",
        "schema_versions",
        "capabilities",
    )
    missing = [key for key in required if not manifest.get(key)]
    if manifest.get("schema") != "simplicio.component-release/v1":
        raise ReleaseGovernanceError("manifest schema is not simplicio.component-release/v1")
    if missing:
        raise ReleaseGovernanceError("manifest is missing release identity fields: " + ", ".join(missing))
    _semver_key(str(manifest["version"]))


def classify_release_change(
    previous_manifest: Mapping[str, Any],
    current_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify schema/capability/protocol drift without optimistic guessing."""

    _require_manifest(previous_manifest)
    _require_manifest(current_manifest)

    previous_schemas = dict(previous_manifest.get("schema_versions", {}))
    current_schemas = dict(current_manifest.get("schema_versions", {}))
    previous_capabilities = set(previous_manifest.get("capabilities", []))
    current_capabilities = set(current_manifest.get("capabilities", []))
    previous_protocols = set(previous_manifest.get("protocols", []))
    current_protocols = set(current_manifest.get("protocols", []))

    schema_added = sorted(set(current_schemas) - set(previous_schemas))
    schema_removed = sorted(set(previous_schemas) - set(current_schemas))
    schema_changed = sorted(
        key
        for key in set(previous_schemas) & set(current_schemas)
        if previous_schemas[key] != current_schemas[key]
    )
    capabilities_added = sorted(current_capabilities - previous_capabilities)
    capabilities_removed = sorted(previous_capabilities - current_capabilities)
    protocols_added = sorted(current_protocols - previous_protocols)
    protocols_removed = sorted(previous_protocols - current_protocols)

    compatibility_changed = previous_manifest.get("compatibility") != current_manifest.get("compatibility")
    breaking_reasons = []
    if schema_removed:
        breaking_reasons.append("schema-removed")
    if schema_changed:
        breaking_reasons.append("schema-version-changed")
    if capabilities_removed:
        breaking_reasons.append("capability-removed")
    if protocols_removed:
        breaking_reasons.append("protocol-removed")
    if compatibility_changed:
        breaking_reasons.append("compatibility-range-changed")

    return {
        "schema": GOVERNANCE_SCHEMA,
        "from_version": previous_manifest["version"],
        "to_version": current_manifest["version"],
        "classification": "breaking" if breaking_reasons else "compatible",
        "breaking_reasons": breaking_reasons,
        "schema_versions": {
            "added": schema_added,
            "removed": schema_removed,
            "changed": schema_changed,
        },
        "capabilities": {
            "added": capabilities_added,
            "removed": capabilities_removed,
        },
        "protocols": {
            "added": protocols_added,
            "removed": protocols_removed,
        },
        "compatibility_changed": compatibility_changed,
    }


def check_registry_parity(
    manifest: Mapping[str, Any],
    *,
    pypi_version: str | None,
    npm_version: str | None,
) -> dict[str, Any]:
    """Fail closed unless both public registries report the manifest version."""

    _require_manifest(manifest)
    expected = str(manifest["version"])
    observed = {"pypi": pypi_version, "npm": npm_version}
    failures: dict[str, str] = {}
    for registry, version in observed.items():
        if version is None:
            failures[registry] = "missing-or-unpublished"
        elif version != expected:
            failures[registry] = f"expected {expected}, observed {version}"
    return {
        "schema": GOVERNANCE_SCHEMA,
        "check": "registry-parity",
        "expected_version": expected,
        "observed": observed,
        "status": "blocked" if failures else "passed",
        "failures": failures,
    }


def _signature_payload(manifest: Mapping[str, Any]) -> bytes:
    payload = copy.deepcopy(dict(manifest))
    signing = dict(payload.get("signing", {}))
    signing.pop("digest", None)
    signing.pop("signature", None)
    payload["signing"] = signing
    return _canonical(payload)


def sign_release_manifest(
    manifest: Mapping[str, Any],
    private_key_pem: bytes,
) -> dict[str, Any]:
    """Return a manifest signed with a real Ed25519 private key.

    The private key is accepted as bytes and is never embedded in the result.
    """

    _require_manifest(manifest)
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as error:
        raise ReleaseGovernanceError(
            "Ed25519 signing requires the optional 'release' dependency"
        ) from error

    try:
        private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    except (TypeError, ValueError) as error:
        raise ReleaseGovernanceError("invalid unencrypted PEM private key") from error
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ReleaseGovernanceError("release signing key must be Ed25519")

    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    result = copy.deepcopy(dict(manifest))
    existing = dict(result.get("signing", {}))
    result["signing"] = {
        "status": "signed",
        "algorithm": "Ed25519",
        "key_id": "sha256:" + hashlib.sha256(public_key).hexdigest(),
        "public_key": "base64:" + base64.b64encode(public_key).decode("ascii"),
        "digest": None,
        "signature": None,
        "sbom": existing.get("sbom"),
        "note": "Ed25519 signature covers the canonical manifest, including the SBOM digest.",
    }
    payload = _signature_payload(result)
    result["signing"]["digest"] = "sha256:" + hashlib.sha256(payload).hexdigest()
    result["signing"]["signature"] = "base64:" + base64.b64encode(private_key.sign(payload)).decode(
        "ascii"
    )
    return result


def verify_release_manifest_signature(manifest: Mapping[str, Any]) -> bool:
    """Verify the embedded Ed25519 signature, returning False on any defect."""

    signing = manifest.get("signing")
    if not isinstance(signing, Mapping) or signing.get("status") != "signed":
        return False
    if signing.get("algorithm") != "Ed25519":
        return False
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        return False

    try:
        public_encoded = str(signing["public_key"])
        signature_encoded = str(signing["signature"])
        if not public_encoded.startswith("base64:") or not signature_encoded.startswith("base64:"):
            return False
        public_bytes = base64.b64decode(public_encoded.removeprefix("base64:"), validate=True)
        signature_bytes = base64.b64decode(signature_encoded.removeprefix("base64:"), validate=True)
        payload = _signature_payload(manifest)
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        if digest != signing.get("digest"):
            return False
        key_id = "sha256:" + hashlib.sha256(public_bytes).hexdigest()
        if key_id != signing.get("key_id"):
            return False
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(signature_bytes, payload)
    except (binascii.Error, InvalidSignature, KeyError, TypeError, ValueError):
        return False
    return True


def build_cyclonedx_sbom(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Build a deterministic CycloneDX 1.6 SBOM for published release surfaces."""

    _require_manifest(manifest)
    version = str(manifest["version"])
    distribution = dict(manifest.get("distribution", {}))
    components = [
        {
            "type": "library",
            "name": distribution.get("pypi_package", "simplicio-mapper"),
            "version": version,
            "purl": f"pkg:pypi/simplicio-mapper@{version}",
        },
        {
            "type": "application",
            "name": distribution.get("npm_package", "@wesleysimplicio/llm-project-mapper"),
            "version": version,
            "purl": f"pkg:npm/%40wesleysimplicio/llm-project-mapper@{version}",
        },
    ]
    artifact_hashes = []
    for artifact_type in ("whl", "sdist"):
        entry = manifest.get("artifact_digests", {}).get(artifact_type)
        if isinstance(entry, Mapping) and isinstance(entry.get("digest"), str):
            digest = str(entry["digest"])
            if digest.startswith("sha256:"):
                artifact_hashes.append(
                    {
                        "alg": "SHA-256",
                        "content": digest.removeprefix("sha256:"),
                        "filename": entry.get("filename"),
                    }
                )
    serial_source = str(manifest["artifact_digest"])
    return {
        "bomFormat": _SBOM_FORMAT,
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, serial_source)),
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "simplicio-mapper",
                "version": version,
            },
            "properties": [
                {"name": "simplicio:commit_sha", "value": manifest["commit_sha"]},
                {"name": "simplicio:artifact_digest", "value": manifest["artifact_digest"]},
            ],
        },
        "components": components,
        "properties": [
            {
                "name": "simplicio:release-artifacts",
                "value": json.dumps(artifact_hashes, ensure_ascii=False, sort_keys=True),
            }
        ],
    }


def attach_sbom(
    manifest: Mapping[str, Any],
    sbom: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach the canonical SBOM digest without claiming that the manifest is signed."""

    if sbom.get("bomFormat") != _SBOM_FORMAT:
        raise ReleaseGovernanceError("SBOM must use CycloneDX")
    result = copy.deepcopy(dict(manifest))
    signing = dict(result.get("signing", {}))
    signing["sbom"] = _sha256(sbom)
    result["signing"] = signing
    return result


def _release_event(manifest: Mapping[str, Any]) -> dict[str, Any]:
    _require_manifest(manifest)
    identity = {
        "component": manifest["component"],
        "version": manifest["version"],
        "commit_sha": manifest["commit_sha"],
        "artifact_digest": manifest["artifact_digest"],
    }
    event_id = _sha256(identity)
    return {
        "schema": "simplicio.component-release-event/v1",
        "event_type": "simplicio-component-release",
        "event_id": event_id,
        "dedupe_key": event_id,
        "component": manifest["component"],
        "version": manifest["version"],
        "commit_sha": manifest["commit_sha"],
        "release_manifest_digest": manifest["artifact_digest"],
    }


def reconcile_release_events(
    manifests: Iterable[Mapping[str, Any]],
    *,
    processed_event_ids: set[str],
) -> dict[str, Any]:
    """Reconcile polled releases into a deduplicated, version-ordered event queue."""

    unique: dict[str, dict[str, Any]] = {}
    duplicates_skipped = 0
    for manifest in manifests:
        event = _release_event(manifest)
        if event["event_id"] in unique:
            duplicates_skipped += 1
            continue
        unique[event["event_id"]] = event

    pending = [
        event for event_id, event in unique.items() if event_id not in processed_event_ids
    ]
    pending.sort(key=lambda event: _semver_key(str(event["version"])))
    return {
        "schema": GOVERNANCE_SCHEMA,
        "check": "release-event-reconciliation",
        "pending": pending,
        "already_processed": len(unique) - len(pending),
        "duplicates_skipped": duplicates_skipped,
    }


def build_rollback_plan(
    current_manifest: Mapping[str, Any],
    previous_manifest: Mapping[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    """Build a deterministic, replay-safe revocation and rollback plan."""

    _require_manifest(current_manifest)
    _require_manifest(previous_manifest)
    if _semver_key(str(previous_manifest["version"])) >= _semver_key(str(current_manifest["version"])):
        raise ReleaseGovernanceError("rollback target must precede the current version")
    if not reason.strip():
        raise ReleaseGovernanceError("rollback reason is required")
    plan = {
        "schema": "simplicio.release-rollback/v1",
        "component": current_manifest["component"],
        "revoke": {
            "version": current_manifest["version"],
            "commit_sha": current_manifest["commit_sha"],
            "artifact_digest": current_manifest["artifact_digest"],
        },
        "restore": {
            "version": previous_manifest["version"],
            "commit_sha": previous_manifest["commit_sha"],
            "artifact_digest": previous_manifest["artifact_digest"],
        },
        "reason": reason.strip(),
        "operations": [
            "mark-current-revoked",
            "restore-previous-consumer-pin",
            "emit-idempotent-rollback-event",
            "retain-immutable-artifacts",
        ],
    }
    plan["plan_id"] = _sha256(plan)
    return plan


def evaluate_stable_promotion(
    manifest: Mapping[str, Any],
    *,
    previous_manifest: Mapping[str, Any],
    pypi_version: str | None,
    npm_version: str | None,
    downstream_ack_minutes: int | None,
    benchmark_regressions: Sequence[str],
) -> dict[str, Any]:
    """Promote stable only when every independently verifiable gate is green."""

    parity = check_registry_parity(
        manifest,
        pypi_version=pypi_version,
        npm_version=npm_version,
    )
    change = classify_release_change(previous_manifest, manifest)
    failed_gates: list[str] = []
    if parity["status"] != "passed":
        failed_gates.append("registry-parity")
    if not verify_release_manifest_signature(manifest):
        failed_gates.append("signature")
    if not manifest.get("signing", {}).get("sbom"):
        failed_gates.append("sbom")
    if change["classification"] == "breaking":
        failed_gates.append("compatibility")
    if downstream_ack_minutes is None or downstream_ack_minutes > 15 or downstream_ack_minutes < 0:
        failed_gates.append("downstream-ack")
    if benchmark_regressions:
        failed_gates.append("benchmark")
    return {
        "schema": GOVERNANCE_SCHEMA,
        "check": "stable-promotion",
        "version": manifest["version"],
        "decision": "hold-canary" if failed_gates else "promote-stable",
        "failed_gates": failed_gates,
        "registry_parity": parity,
        "change": change,
        "downstream_ack_minutes": downstream_ack_minutes,
        "benchmark_regressions": list(benchmark_regressions),
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ReleaseGovernanceError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ReleaseGovernanceError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ReleaseGovernanceError(f"{path} must contain a JSON object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_release_governance_cli(argv: list[str]) -> int:
    """Run deterministic release governance without performing network effects."""

    parser = argparse.ArgumentParser(prog="simplicio-mapper release-governance")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parity = subparsers.add_parser("parity")
    parity.add_argument("--manifest", type=Path, required=True)
    parity.add_argument("--pypi-version")
    parity.add_argument("--npm-version")

    classify = subparsers.add_parser("classify")
    classify.add_argument("--previous", type=Path, required=True)
    classify.add_argument("--current", type=Path, required=True)

    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("--manifest", type=Path, action="append", required=True)
    reconcile.add_argument("--ledger", type=Path)

    sign = subparsers.add_parser("sign")
    sign.add_argument("--manifest", type=Path, required=True)
    sign.add_argument("--key", type=Path, required=True)
    sign.add_argument("--output", type=Path, required=True)
    sign.add_argument("--sbom-output", type=Path, required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)

    promote = subparsers.add_parser("promote")
    promote.add_argument("--manifest", type=Path, required=True)
    promote.add_argument("--previous", type=Path, required=True)
    promote.add_argument("--pypi-version")
    promote.add_argument("--npm-version")
    promote.add_argument("--downstream-ack-minutes", type=int)
    promote.add_argument("--benchmark-regression", action="append", default=[])

    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--current", type=Path, required=True)
    rollback.add_argument("--previous", type=Path, required=True)
    rollback.add_argument("--reason", required=True)
    rollback.add_argument("--output", type=Path)

    try:
        args = parser.parse_args(argv)
        if args.command == "parity":
            result = check_registry_parity(
                _read_json(args.manifest),
                pypi_version=args.pypi_version,
                npm_version=args.npm_version,
            )
            status = 0 if result["status"] == "passed" else 1
        elif args.command == "classify":
            result = classify_release_change(
                _read_json(args.previous),
                _read_json(args.current),
            )
            status = 0
        elif args.command == "reconcile":
            processed: set[str] = set()
            if args.ledger is not None:
                ledger = _read_json(args.ledger)
                raw_processed = ledger.get("processed_event_ids", [])
                if not isinstance(raw_processed, list) or not all(
                    isinstance(item, str) for item in raw_processed
                ):
                    raise ReleaseGovernanceError(
                        "ledger.processed_event_ids must be a list of strings"
                    )
                processed = set(raw_processed)
            result = reconcile_release_events(
                [_read_json(path) for path in args.manifest],
                processed_event_ids=processed,
            )
            status = 0
        elif args.command == "sign":
            manifest = _read_json(args.manifest)
            try:
                private_key_pem = args.key.read_bytes()
            except OSError as error:
                raise ReleaseGovernanceError(f"cannot read signing key {args.key}: {error}") from error
            sbom = build_cyclonedx_sbom(manifest)
            signed = sign_release_manifest(attach_sbom(manifest, sbom), private_key_pem)
            _write_json(args.sbom_output, sbom)
            _write_json(args.output, signed)
            result = {
                "schema": GOVERNANCE_SCHEMA,
                "status": "passed",
                "manifest": str(args.output),
                "sbom": str(args.sbom_output),
                "key_id": signed["signing"]["key_id"],
                "digest": signed["signing"]["digest"],
            }
            status = 0
        elif args.command == "verify":
            valid = verify_release_manifest_signature(_read_json(args.manifest))
            result = {
                "schema": GOVERNANCE_SCHEMA,
                "check": "manifest-signature",
                "status": "passed" if valid else "failed",
                "manifest": str(args.manifest),
            }
            status = 0 if valid else 1
        elif args.command == "promote":
            result = evaluate_stable_promotion(
                _read_json(args.manifest),
                previous_manifest=_read_json(args.previous),
                pypi_version=args.pypi_version,
                npm_version=args.npm_version,
                downstream_ack_minutes=args.downstream_ack_minutes,
                benchmark_regressions=args.benchmark_regression,
            )
            status = 0 if result["decision"] == "promote-stable" else 1
        else:
            result = build_rollback_plan(
                _read_json(args.current),
                _read_json(args.previous),
                reason=args.reason,
            )
            if args.output is not None:
                _write_json(args.output, result)
            status = 0
    except (ReleaseGovernanceError, OSError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "schema": GOVERNANCE_SCHEMA,
                    "status": "failed",
                    "error": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return status


__all__ = [
    "ReleaseGovernanceError",
    "attach_sbom",
    "build_cyclonedx_sbom",
    "build_rollback_plan",
    "check_registry_parity",
    "classify_release_change",
    "evaluate_stable_promotion",
    "reconcile_release_events",
    "run_release_governance_cli",
    "sign_release_manifest",
    "verify_release_manifest_signature",
]
