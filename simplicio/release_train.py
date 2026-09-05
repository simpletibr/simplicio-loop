"""Fail-closed release-train contracts for the Mapper consumer.

The decisions in this module are deterministic and side-effect free. GitHub
transport, package publication, PR creation and Loop dispatch remain explicit
authenticated adapters outside the Dev CLI.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .component_manifest import (
    COMPATIBLE,
    check_version_against_range,
    compare_versions,
    declared_dependency_range,
    tested_dependency_version,
)

MANIFEST_SCHEMA = "simplicio.component-release/v1"
EVENT_SCHEMA = "simplicio.component-release-event/v1"
EVENT_TYPE = "simplicio-component-release"
PLAN_SCHEMA = "simplicio.dev-cli.release-train/v1"
DOCTOR_SCHEMA = "simplicio.release-train-doctor/v1"
MAPPER_COMPONENT = "simplicio-mapper"
LOOP_REPOSITORY = "wesleysimplicio/simplicio-loop"

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_GREEN = {"green", "passed", "pass", "ok", "success", True}


class ReleaseTrainError(ValueError):
    """Raised when a release-train input cannot be safely evaluated."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _digests(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        result: set[str] = set()
        for item in value.values():
            if isinstance(item, Mapping) and isinstance(item.get("digest"), str):
                result.add(item["digest"])
            result.update(_digests(item))
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result = set()
        for item in value:
            result.update(_digests(item))
        return result
    return set()


def _strings(data: Any, field_name: str, *, non_empty: bool = True) -> list[str]:
    if not isinstance(data, list) or (non_empty and not data) or not all(_text(item) for item in data):
        return [f"{field_name} must be a non-empty list of strings"]
    if len(set(data)) != len(data):
        return [f"{field_name} must not contain duplicates"]
    return []


def _manifest_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "component": value.get("component"),
        "version": value.get("version"),
        "commit_sha": value.get("commit_sha"),
        "artifact_digest": value.get("artifact_digest"),
    }


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    """Hash the complete canonical producer manifest."""
    return canonical_digest(dict(manifest))


def validate_mapper_manifest(manifest: Any, *, require_signed: bool = False) -> list[str]:
    """Validate the Mapper component-release/v1 schema and release identity."""
    if not isinstance(manifest, Mapping):
        return ["manifest must be an object"]

    allowed = {
        "schema", "component", "version", "commit_sha", "commit_sha_source",
        "generated_at", "distribution", "schema_versions", "protocols",
        "capabilities", "compatibility", "artifact_digest", "artifact_digests",
        "signing", "downstream_events",
    }
    unknown = sorted(set(manifest) - allowed, key=str)
    errors = [f"unknown manifest field(s): {unknown}"] if unknown else []
    required = (
        "schema", "component", "version", "commit_sha", "commit_sha_source",
        "generated_at", "distribution", "schema_versions", "protocols",
        "capabilities", "compatibility", "artifact_digest", "artifact_digests",
        "signing", "downstream_events",
    )
    errors.extend(f"missing required manifest field: {name}" for name in required if name not in manifest)

    if manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append(f"manifest.schema must be {MANIFEST_SCHEMA!r}")
    if manifest.get("component") != MAPPER_COMPONENT:
        errors.append(f"manifest.component must be {MAPPER_COMPONENT!r}")

    version = manifest.get("version")
    if not _text(version):
        errors.append("manifest.version must be a non-empty string")
    else:
        try:
            from .component_manifest import parse_version

            parse_version(version)
        except (TypeError, ValueError) as error:
            errors.append(f"manifest.version is not comparable: {error}")

    if not isinstance(manifest.get("commit_sha"), str) or not _COMMIT_RE.fullmatch(manifest["commit_sha"]):
        errors.append("manifest.commit_sha must be a 40-character lowercase commit SHA")
    for name in ("commit_sha_source", "generated_at"):
        if not _text(manifest.get(name)):
            errors.append(f"manifest.{name} must be a non-empty string")

    distribution = manifest.get("distribution")
    if not isinstance(distribution, Mapping):
        errors.append("manifest.distribution must be an object")
    elif distribution.get("pypi_package") != MAPPER_COMPONENT:
        errors.append("manifest.distribution.pypi_package must be simplicio-mapper")

    for name in ("protocols", "capabilities"):
        errors.extend(f"manifest.{error}" for error in _strings(manifest.get(name), name))
    schemas = manifest.get("schema_versions")
    if not isinstance(schemas, Mapping) or not schemas:
        errors.append("manifest.schema_versions must be a non-empty object")
    elif any(not isinstance(k, str) or not isinstance(v, (str, int)) or isinstance(v, bool)
             for k, v in schemas.items()):
        errors.append("manifest.schema_versions values must be strings or integers")

    compatibility = manifest.get("compatibility")
    if not isinstance(compatibility, Mapping) or not compatibility:
        errors.append("manifest.compatibility must be a non-empty object")
    elif "simplicio-dev-cli" not in compatibility:
        errors.append("manifest.compatibility must declare simplicio-dev-cli")

    digest = manifest.get("artifact_digest")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        errors.append("manifest.artifact_digest must be sha256:<64 lowercase hex characters>")
    artifacts = manifest.get("artifact_digests")
    if not isinstance(artifacts, Mapping) or not artifacts:
        errors.append("manifest.artifact_digests must be a non-empty object")
    else:
        for name, artifact in artifacts.items():
            if not isinstance(artifact, Mapping):
                errors.append(f"manifest.artifact_digests[{name!r}] must be an object")
                continue
            if not _text(artifact.get("filename")):
                errors.append(f"manifest.artifact_digests[{name!r}].filename is required")
            if not isinstance(artifact.get("digest"), str) or not _SHA256_RE.fullmatch(artifact["digest"]):
                errors.append(f"manifest.artifact_digests[{name!r}].digest is invalid")
        if isinstance(digest, str) and digest not in _digests(artifacts):
            errors.append("manifest.artifact_digest is not present in artifact_digests")

    signing = manifest.get("signing")
    if not isinstance(signing, Mapping):
        errors.append("manifest.signing must be an object")
    elif not _text(signing.get("status")):
        errors.append("manifest.signing.status is required")
    if require_signed and isinstance(signing, Mapping):
        if signing.get("status") != "signed":
            errors.append("manifest.signing.status is not signed")
        if signing.get("algorithm") != "Ed25519":
            errors.append("manifest.signing.algorithm must be Ed25519")
        if not isinstance(signing.get("digest"), str) or not _SHA256_RE.fullmatch(signing["digest"]):
            errors.append("manifest.signing.digest is required for a signed release")
        if not isinstance(signing.get("signature"), str) or not signing["signature"].startswith("base64:"):
            errors.append("manifest.signing.signature is required for a signed release")
        if not isinstance(signing.get("sbom"), str) or not _SHA256_RE.fullmatch(signing["sbom"]):
            errors.append("manifest.signing.sbom is required for a signed release")

    downstream = manifest.get("downstream_events")
    if not isinstance(downstream, Mapping):
        errors.append("manifest.downstream_events must be an object")
    elif downstream.get("deduplication") != "event_id":
        errors.append("manifest.downstream_events.deduplication must be event_id")
    return sorted(set(errors))


def _event_identity(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "component": event.get("component"),
        "version": event.get("version"),
        "commit_sha": event.get("commit_sha"),
        "artifact_digest": event.get("release_manifest_digest"),
    }


def validate_release_event(event: Any) -> list[str]:
    """Validate a Mapper release event and its canonical event identity."""
    if not isinstance(event, Mapping):
        return ["event must be an object"]
    required = (
        "schema", "event_type", "event_id", "dedupe_key", "component", "version",
        "commit_sha", "release_manifest_schema", "release_manifest_digest",
        "artifact_digests", "schema_versions", "capabilities", "compatibility",
        "attestation", "delivery", "consumers", "rollback",
    )
    errors = [f"missing required event field: {name}" for name in required if name not in event]
    errors.extend([f"event.schema must be {EVENT_SCHEMA!r}"] if event.get("schema") != EVENT_SCHEMA else [])
    errors.extend(
        [f"event.event_type must be {EVENT_TYPE!r}"]
        if event.get("event_type") != EVENT_TYPE
        else []
    )
    errors.extend(
        [f"event.component must be {MAPPER_COMPONENT!r}"]
        if event.get("component") != MAPPER_COMPONENT
        else []
    )
    for name in ("event_id", "dedupe_key", "release_manifest_digest"):
        value = event.get(name)
        if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
            errors.append(f"event.{name} must be sha256:<64 lowercase hex characters>")
    if not isinstance(event.get("commit_sha"), str) or not _COMMIT_RE.fullmatch(event["commit_sha"]):
        errors.append("event.commit_sha must be a 40-character lowercase commit SHA")
    if event.get("release_manifest_schema") != MANIFEST_SCHEMA:
        errors.append(f"event.release_manifest_schema must be {MANIFEST_SCHEMA!r}")
    if event.get("event_id") != event.get("dedupe_key"):
        errors.append("event.event_id and event.dedupe_key must match")
    if (
        isinstance(event.get("event_id"), str)
        and event["event_id"] != canonical_digest(_event_identity(event))
    ):
        errors.append("event.event_id does not match its immutable release identity")

    for name in ("artifact_digests", "schema_versions", "compatibility", "delivery", "rollback"):
        if not isinstance(event.get(name), Mapping):
            errors.append(f"event.{name} must be an object")
    errors.extend(_strings(event.get("capabilities"), "event.capabilities"))
    if not isinstance(event.get("consumers"), list) or not event["consumers"]:
        errors.append("event.consumers must be a non-empty list")
    if not _text(event.get("attestation")):
        errors.append("event.attestation must be a non-empty string")
    artifacts = event.get("artifact_digests")
    if isinstance(artifacts, Mapping):
        if not artifacts:
            errors.append("event.artifact_digests must not be empty")
        for name, artifact in artifacts.items():
            if not isinstance(artifact, Mapping) or not _text(artifact.get("filename")):
                errors.append(f"event.artifact_digests[{name!r}] must contain filename")
            elif not isinstance(artifact.get("digest"), str) or not _SHA256_RE.fullmatch(artifact["digest"]):
                errors.append(f"event.artifact_digests[{name!r}].digest is invalid")
        if event.get("release_manifest_digest") not in _digests(artifacts):
            errors.append("event.release_manifest_digest is not present in artifact_digests")
    version = event.get("version")
    if not _text(version):
        errors.append("event.version must be a non-empty string")
    else:
        try:
            from .component_manifest import parse_version

            parse_version(version)
        except (TypeError, ValueError) as error:
            errors.append(f"event.version is not comparable: {error}")
    return sorted(set(errors))


def build_release_event(manifest: Mapping[str, Any], *, channel: str = "canary") -> dict[str, Any]:
    """Build the producer-compatible event without making a network request."""
    errors = validate_mapper_manifest(manifest, require_signed=channel == "stable")
    if errors:
        raise ReleaseTrainError("; ".join(errors))
    event_id = canonical_digest(_manifest_identity(manifest))
    return {
        "schema": EVENT_SCHEMA,
        "event_type": EVENT_TYPE,
        "event_id": event_id,
        "dedupe_key": event_id,
        "component": MAPPER_COMPONENT,
        "version": manifest["version"],
        "commit_sha": manifest["commit_sha"],
        "release_manifest_schema": MANIFEST_SCHEMA,
        "release_manifest_digest": manifest["artifact_digest"],
        "artifact_digests": copy.deepcopy(dict(manifest["artifact_digests"])),
        "schema_versions": copy.deepcopy(dict(manifest["schema_versions"])),
        "capabilities": list(manifest["capabilities"]),
        "compatibility": copy.deepcopy(dict(manifest["compatibility"])),
        "attestation": (
            "ed25519-signed"
            if manifest.get("signing", {}).get("status") == "signed"
            else "transport-authenticated-only"
        ),
        "delivery": {
            "transport": "github.repository_dispatch",
            "authentication": "github-token",
            "secret_name": "RELEASE_TRAIN_DISPATCH_TOKEN",
            "retry_safe": True,
            "channel": channel,
        },
        "consumers": [
            {"repository": "wesleysimplicio/simplicio-dev-cli", "action": "prepare-bump"},
            {"repository": LOOP_REPOSITORY, "action": "dispatch-after-pypi-publish"},
        ],
        "rollback": {
            "supported": True,
            "strategy": "revoke-current-and-restore-previous-pin",
            "immutable_artifacts_retained": True,
        },
    }


def _green(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.lower() in _GREEN)


def _conformance_errors(event: Mapping[str, Any], evidence: Any) -> list[str]:
    if not isinstance(evidence, Mapping):
        return ["conformance evidence is required"]
    errors = []
    if not _green(evidence.get("status")):
        errors.append("conformance.status must be green/passed")
    if evidence.get("version") != event.get("version"):
        errors.append("conformance.version does not match the candidate")
    if evidence.get("commit_sha") != event.get("commit_sha"):
        errors.append("conformance.commit_sha does not match the candidate")
    if evidence.get("entrypoint_owner", evidence.get("entrypoint")) != MAPPER_COMPONENT:
        errors.append("conformance.entrypoint_owner must be simplicio-mapper")
    lock = evidence.get("lockfile")
    lock_version = lock.get("version") if isinstance(lock, Mapping) else evidence.get("lock_version")
    if lock_version != event.get("version"):
        errors.append("conformance.lock_version must match the candidate")
    for name, aliases in (
        ("n", ("n", "n_conformance")),
        ("n_minus_1", ("n_minus_1", "n-1", "n_minus_1_conformance")),
    ):
        value = next((evidence.get(alias) for alias in aliases if alias in evidence), None)
        if not _green(value):
            errors.append(f"conformance.{name} must be green/passed")
    if _digests(evidence.get("artifact_digests")) != _digests(event.get("artifact_digests")):
        errors.append("conformance.artifact_digests must exactly match the candidate")
    if not set(event.get("capabilities", [])).issubset(set(evidence.get("capabilities", []))):
        errors.append("conformance.capabilities do not cover the candidate")
    expected = event.get("schema_versions", {})
    actual = evidence.get("schema_versions")
    if not isinstance(actual, Mapping) or any(actual.get(k) != v for k, v in expected.items()):
        errors.append("conformance.schema_versions do not match the candidate")
    return sorted(set(errors))


def build_bump_plan(
    event: Mapping[str, Any], *, declared_range: str | None, tested_against: str | None
) -> dict[str, Any]:
    """Emit the bounded dependency-bump contract consumed by an adapter."""
    return {
        "schema": PLAN_SCHEMA,
        "status": "ready_for_dependency_bump",
        "dependency": {
            "name": MAPPER_COMPONENT,
            "version": event["version"],
            "commit_sha": event["commit_sha"],
            "artifact_digest": event["release_manifest_digest"],
            "artifact_digests": copy.deepcopy(dict(event["artifact_digests"])),
            "source_event_id": event["event_id"],
        },
        "declared_range": declared_range,
        "previous_tested_against": tested_against,
        "lock": {
            "required": True,
            "version": event["version"],
            "artifact_digests": copy.deepcopy(dict(event["artifact_digests"])),
        },
        "conformance": {
            "required": ["n", "n_minus_1", "clean_installed_entrypoint"],
            "preserve_receipts_and_cache": True,
        },
        "next_action": "open_or_update_bump_pr",
        "downstream": {
            "status": "pending_dev_cli_publish",
            "repository": LOOP_REPOSITORY,
            "event_type": EVENT_SCHEMA,
            "dispatch_after": "pypi_publish",
            "deduplication": "event_id",
        },
        "rollback": copy.deepcopy(dict(event.get("rollback", {}))),
        "automation_boundary": {
            "dev_cli": "prepare_and_verify_contract",
            "github": "authenticated_pr_adapter",
            "loop": "authenticated_downstream_reconciler",
        },
    }


@dataclass(frozen=True)
class ReleaseTrainDecision:
    status: str
    reason_code: str
    reason: str
    event_id: str | None
    version: str | None
    plan: dict[str, Any] | None
    state: dict[str, Any] = field(default_factory=dict)
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PLAN_SCHEMA,
            "status": self.status,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "event_id": self.event_id,
            "version": self.version,
            "plan": copy.deepcopy(self.plan),
            "state": copy.deepcopy(self.state),
            "errors": list(self.errors),
        }


def _blocked(
    code: str,
    reason: str,
    event_id: str | None,
    version: str | None,
    state: Mapping[str, Any],
    errors: Iterable[str] = (),
) -> ReleaseTrainDecision:
    return ReleaseTrainDecision("blocked", code, reason, event_id, version, None, dict(state), tuple(errors))


def evaluate_release_event(
    event: Any,
    *,
    declared_range: str | None,
    tested_against: str | None = None,
    conformance: Any = None,
    active_task: bool = False,
    processed_event_ids: Iterable[str] = (),
    last_processed_version: str | None = None,
) -> ReleaseTrainDecision:
    """Evaluate one event without changing files, locks, or task state."""
    processed = set(processed_event_ids)
    state = {"processed_event_ids": sorted(processed), "last_processed_version": last_processed_version}
    errors = validate_release_event(event)
    event_id = event.get("event_id") if isinstance(event, Mapping) else None
    version = event.get("version") if isinstance(event, Mapping) else None
    if errors:
        return _blocked(
            "invalid_event", "release event failed validation", event_id, version, state, errors
        )

    event_id = str(event["event_id"])
    version = str(event["version"])
    if event_id in processed:
        return ReleaseTrainDecision(
            "duplicate", "duplicate_event", "event was already processed", event_id, version, None, state
        )
    if last_processed_version is not None:
        try:
            if compare_versions(version, last_processed_version) <= 0:
                return _blocked(
                    "out_of_order_event",
                    f"candidate {version} is not newer than processed {last_processed_version}",
                    event_id, version, state,
                )
        except ValueError as error:
            return _blocked("unparseable_version", str(error), event_id, version, state, (str(error),))

    release_status = str(event.get("status", event.get("release_status", ""))).lower()
    if event.get("revoked") is True or release_status in {"revoked", "recalled"}:
        return _blocked(
            "revoked_release",
            "revoked Mapper releases are never accepted",
            event_id, version, state,
        )
    if event.get("yanked") is True or release_status in {"yanked", "withdrawn"}:
        return _blocked(
            "yanked_release",
            "yanked Mapper releases are never accepted",
            event_id, version, state,
        )
    delivery = event.get("delivery")
    if isinstance(delivery, Mapping) and delivery.get("authenticated") is False:
        return _blocked(
            "unauthenticated_delivery",
            "release event delivery is not authenticated",
            event_id, version, state,
        )

    compatibility = check_version_against_range(version, declared_range, name=MAPPER_COMPONENT)
    if compatibility.status != COMPATIBLE:
        return _blocked("incompatible_candidate", compatibility.reason, event_id, version, state)
    if event.get("attestation") != "ed25519-signed":
        return _blocked(
            "attestation_missing",
            "stable acceptance requires an Ed25519-signed Mapper manifest",
            event_id, version, state,
        )
    if active_task:
        return ReleaseTrainDecision(
            "deferred", "active_task", "an update is deferred while a task is active",
            event_id, version, None, state,
        )
    errors = _conformance_errors(event, conformance)
    if errors:
        return _blocked(
            "conformance_not_proven",
            "candidate lacks complete installed N/N-1 evidence",
            event_id, version, state, errors,
        )

    next_state = {"processed_event_ids": sorted(processed | {event_id}), "last_processed_version": version}
    return ReleaseTrainDecision(
        "accepted",
        "compatible_and_verified",
        "candidate is compatible and has immutable install/conformance evidence",
        event_id,
        version,
        build_bump_plan(event, declared_range=declared_range, tested_against=tested_against),
        next_state,
    )


def reconcile_release_events(
    events: Sequence[Any],
    *,
    declared_range: str | None,
    tested_against: str | None = None,
    conformance: Any = None,
    active_task: bool = False,
    state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile a batch while retaining duplicate and blocked receipts."""
    current = dict(state or {})
    processed = set(current.get("processed_event_ids", []))
    last = current.get("last_processed_version")
    results = []
    for event in events:
        decision = evaluate_release_event(
            event, declared_range=declared_range, tested_against=tested_against,
            conformance=conformance, active_task=active_task,
            processed_event_ids=processed, last_processed_version=last,
        )
        results.append(decision.to_dict())
        if decision.status == "accepted":
            processed = set(decision.state["processed_event_ids"])
            last = decision.state["last_processed_version"]
    return {
        "schema": PLAN_SCHEMA,
        "status": "accepted" if any(item["status"] == "accepted" for item in results) else "unchanged",
        "results": results,
        "state": {"processed_event_ids": sorted(processed), "last_processed_version": last},
        "accepted": sum(item["status"] == "accepted" for item in results),
        "duplicates": sum(item["status"] == "duplicate" for item in results),
        "blocked": sum(item["status"] == "blocked" for item in results),
        "deferred": sum(item["status"] == "deferred" for item in results),
    }


def release_train_doctor(root: str | None = None) -> dict[str, Any]:
    """Report readiness without network or task-state writes."""
    declared = declared_dependency_range(MAPPER_COMPONENT, root)
    tested, tested_reason = tested_dependency_version(MAPPER_COMPONENT, root)
    configured = declared is not None
    return {
        "schema": DOCTOR_SCHEMA,
        "component": MAPPER_COMPONENT,
        "status": "UNVERIFIED" if configured else "BLOCKED",
        "reason_code": "verified_event_and_conformance_required" if configured else "dependency_not_declared",
        "declared_range": declared,
        "tested_against": tested,
        "tested_against_reason": tested_reason,
        "required_evidence": [
            "immutable commit_sha and artifact_digests",
            "Ed25519 signature and SBOM digest",
            "clean installed entrypoint ownership",
            "lockfile resolution for the candidate",
            "N and N-1 conformance",
        ],
        "automation": {
            "event_receiver": "authenticated external adapter",
            "bump_pr": "authenticated external adapter",
            "loop_dispatch": "after PyPI publication",
        },
        "adapter_contracts": {
            "schema": "simplicio.release-train-adapter/v1",
            "github_bump": "request-only-until-external-receipt",
            "loop_dispatch": "request-only-after-pypi-receipt",
        },
        "next_action": (
            "provide a verified component-release-event/v1 and conformance evidence"
            if configured else "declare a compatible simplicio-mapper dependency"
        ),
    }


__all__ = [
    "DOCTOR_SCHEMA",
    "EVENT_SCHEMA",
    "EVENT_TYPE",
    "LOOP_REPOSITORY",
    "MANIFEST_SCHEMA",
    "MAPPER_COMPONENT",
    "PLAN_SCHEMA",
    "ReleaseTrainDecision",
    "ReleaseTrainError",
    "build_bump_plan",
    "build_release_event",
    "canonical_digest",
    "canonical_json",
    "evaluate_release_event",
    "manifest_digest",
    "reconcile_release_events",
    "release_train_doctor",
    "validate_mapper_manifest",
    "validate_release_event",
]
