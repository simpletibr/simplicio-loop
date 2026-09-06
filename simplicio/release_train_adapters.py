"""Authenticated release-train adapter boundaries.

These helpers produce requests and validate receipts; they never call GitHub,
PyPI, or simplicio-loop and never claim an external action completed without a
receipt.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .release_train import EVENT_SCHEMA, LOOP_REPOSITORY, PLAN_SCHEMA, ReleaseTrainDecision

ADAPTER_SCHEMA = "simplicio.release-train-adapter/v1"
DEV_CLI_REPOSITORY = "wesleysimplicio/simplicio-dev-cli"
_SHA256_PREFIX = "sha256:"


def _blocked(code: str, reason: str, *, event_id: str | None = None) -> dict[str, Any]:
    return {
        "schema": ADAPTER_SCHEMA,
        "status": "blocked",
        "reason_code": code,
        "reason": reason,
        "event_id": event_id,
        "receipt": None,
        "requires_external_receipt": True,
    }


def _plan_from(
    decision: ReleaseTrainDecision | Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    if isinstance(decision, ReleaseTrainDecision):
        return decision.plan, decision.event_id, decision.version
    if not isinstance(decision, Mapping):
        return None, None, None
    plan = decision.get("plan")
    return (
        plan if isinstance(plan, dict) else None,
        decision.get("event_id"),
        decision.get("version"),
    )


def build_github_bump_request(
    decision: ReleaseTrainDecision | Mapping[str, Any],
    *,
    repository: str = DEV_CLI_REPOSITORY,
    base_branch: str = "main",
) -> dict[str, Any]:
    """Build a deduplicated request for an authenticated GitHub adapter."""
    plan, event_id, version = _plan_from(decision)
    if plan is None or not event_id or not version:
        return _blocked(
            "release_not_accepted",
            "only an accepted release decision can open a bump PR",
            event_id=event_id,
        )
    dependency = plan.get("dependency")
    if not isinstance(dependency, Mapping):
        return _blocked(
            "plan_missing_dependency",
            "accepted plan has no dependency identity",
            event_id=event_id,
        )
    return {
        "schema": ADAPTER_SCHEMA,
        "status": "ready_for_authenticated_dispatch",
        "action": "open_or_update_bump_pr",
        "repository": repository,
        "base_branch": base_branch,
        "dedupe_key": event_id,
        "idempotency_key": f"github-bump:{event_id}",
        "title": f"chore: consume simplicio-mapper {version}",
        "evidence": {
            "plan_schema": PLAN_SCHEMA,
            "event_id": event_id,
            "version": version,
            "commit_sha": dependency.get("commit_sha"),
            "artifact_digest": dependency.get("artifact_digest"),
            "artifact_digests": dependency.get("artifact_digests"),
            "rollback": plan.get("rollback"),
        },
        "authentication": {
            "required": True,
            "transport": "github",
            "credential_source": "configured GitHub App or token",
        },
        "requires_external_receipt": True,
        "receipt": None,
    }


def build_loop_dispatch_request(
    decision: ReleaseTrainDecision | Mapping[str, Any],
    *,
    dev_cli_release: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build a Loop dispatch request only after a published Dev CLI release."""
    plan, event_id, version = _plan_from(decision)
    if plan is None or not event_id or not version:
        return _blocked(
            "release_not_accepted",
            "only an accepted release decision can dispatch to Loop",
            event_id=event_id,
        )
    if not isinstance(dev_cli_release, Mapping) or dev_cli_release.get("status") != "pypi_published":
        return _blocked(
            "pypi_not_published",
            "Loop dispatch waits for a proven PyPI publication",
            event_id=event_id,
        )
    release_id = dev_cli_release.get("release_id")
    artifact_digest = dev_cli_release.get("artifact_digest")
    if (
        not isinstance(release_id, str)
        or not release_id
        or not isinstance(artifact_digest, str)
        or not artifact_digest
    ):
        return _blocked(
            "published_release_evidence_missing",
            "published release evidence must include release_id and artifact_digest",
            event_id=event_id,
        )
    manifest = dev_cli_release.get("manifest")
    if not isinstance(manifest, Mapping):
        return _blocked(
            "published_manifest_missing",
            "Loop propagation requires the published component-release manifest",
            event_id=event_id,
        )
    if (
        manifest.get("schema") != "simplicio.component-release/v1"
        or manifest.get("component") != "simplicio-dev-cli"
        or manifest.get("package") != "simplicio-cli"
        or manifest.get("version") != dev_cli_release.get("version")
    ):
        return _blocked(
            "published_manifest_invalid",
            "published manifest does not identify the Dev CLI release",
            event_id=event_id,
        )
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return _blocked(
            "published_artifacts_missing",
            "published manifest must contain PyPI artifact identities",
            event_id=event_id,
        )
    manifest_digests = {
        item.get("digest")
        for item in artifacts
        if isinstance(item, Mapping) and isinstance(item.get("digest"), str)
    }
    if artifact_digest not in manifest_digests or not artifact_digest.startswith(_SHA256_PREFIX):
        return _blocked(
            "published_artifact_identity_mismatch",
            "published release digest is not present in the signed component manifest",
            event_id=event_id,
        )
    return {
        "schema": ADAPTER_SCHEMA,
        "status": "ready_for_authenticated_dispatch",
        "action": "dispatch_loop_release",
        "repository": LOOP_REPOSITORY,
        "event_type": EVENT_SCHEMA,
        "dedupe_key": event_id,
        "idempotency_key": f"loop-release:{event_id}",
        "payload": {
            "manifests": [dict(manifest)],
            "source_event_id": event_id,
            "mapper_version": version,
            "dev_cli_release_id": release_id,
            "dev_cli_artifact_digest": artifact_digest,
            "dispatch_after": "pypi_publish",
        },
        "authentication": {
            "required": True,
            "transport": "github.repository_dispatch",
            "credential_source": "configured GitHub App or token",
        },
        "requires_external_receipt": True,
        "receipt": None,
    }


def reconcile_adapter_receipt(
    request: Mapping[str, Any],
    receipt: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Accept only a receipt that matches the request's immutable identity."""
    if not isinstance(request, Mapping) or request.get("schema") != ADAPTER_SCHEMA:
        return {
            "schema": ADAPTER_SCHEMA,
            "status": "blocked",
            "reason_code": "invalid_request",
        }
    if request.get("status") != "ready_for_authenticated_dispatch":
        return {
            "schema": ADAPTER_SCHEMA,
            "status": "blocked",
            "reason_code": "request_not_dispatchable",
        }
    dedupe_key = request.get("dedupe_key")
    idempotency_key = request.get("idempotency_key")
    if not isinstance(dedupe_key, str) or not dedupe_key or not isinstance(idempotency_key, str):
        return {
            "schema": ADAPTER_SCHEMA,
            "status": "blocked",
            "reason_code": "request_identity_missing",
        }
    if not isinstance(receipt, Mapping):
        return {
            "schema": ADAPTER_SCHEMA,
            "status": "pending",
            "reason_code": "external_receipt_missing",
            "dedupe_key": dedupe_key,
            "receipt": None,
        }
    if receipt.get("dedupe_key") != dedupe_key:
        return {
            "schema": ADAPTER_SCHEMA,
            "status": "blocked",
            "reason_code": "receipt_identity_mismatch",
        }
    if receipt.get("idempotency_key") not in {None, idempotency_key}:
        return {
            "schema": ADAPTER_SCHEMA,
            "status": "blocked",
            "reason_code": "receipt_idempotency_mismatch",
        }
    if receipt.get("action") not in {None, request.get("action")}:
        return {
            "schema": ADAPTER_SCHEMA,
            "status": "blocked",
            "reason_code": "receipt_action_mismatch",
        }
    evidence = request.get("evidence")
    if isinstance(evidence, Mapping):
        for receipt_field, evidence_field in (
            ("version", "version"),
            ("commit_sha", "commit_sha"),
            ("artifact_digest", "artifact_digest"),
        ):
            if receipt.get(receipt_field) is not None and receipt.get(receipt_field) != evidence.get(
                evidence_field
            ):
                return {
                    "schema": ADAPTER_SCHEMA,
                    "status": "blocked",
                    "reason_code": "receipt_release_identity_mismatch",
                }
    payload = request.get("payload")
    if isinstance(payload, Mapping) and receipt.get("version") is not None:
        manifest_list = payload.get("manifests")
        manifest = manifest_list[0] if isinstance(manifest_list, list) and manifest_list else None
        if isinstance(manifest, Mapping) and receipt.get("version") != manifest.get("version"):
            return {
                "schema": ADAPTER_SCHEMA,
                "status": "blocked",
                "reason_code": "receipt_release_identity_mismatch",
            }
    if receipt.get("status") not in {"accepted", "completed", "merged", "published"}:
        return {
            "schema": ADAPTER_SCHEMA,
            "status": "blocked",
            "reason_code": "external_action_failed",
            "receipt": dict(receipt),
        }
    return {
        "schema": ADAPTER_SCHEMA,
        "status": "completed",
        "dedupe_key": dedupe_key,
        "idempotency_key": idempotency_key,
        "receipt": dict(receipt),
    }


__all__ = [
    "ADAPTER_SCHEMA",
    "build_github_bump_request",
    "build_loop_dispatch_request",
    "reconcile_adapter_receipt",
]
