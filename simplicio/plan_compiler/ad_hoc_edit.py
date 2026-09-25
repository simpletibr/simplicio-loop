"""Deterministic contractless edit derivation (issue #685).

This module only derives a bounded proposal. It never reads or writes files,
starts a process, or authorizes an effect. The Runtime remains the authority
that binds the derived proposal to a snapshot, lease, fence, policy and
transaction before execution.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from simplicio.mapper_binding import (
    MapperBindingError,
    canonical_mapper_binding,
    mapper_binding_digest,
    validate_mapper_binding,
)
from simplicio.plan_compiler.canonical_hash import canonical_hash
from simplicio.plan_compiler.models import (
    EffectPlan,
    PlanDAG,
    PlanNode,
    VerificationPlan,
)

AD_HOC_EDIT_SCHEMA = "simplicio.ad-hoc-edit-intent/v1"
DERIVED_EDIT_PROPOSAL_SCHEMA = "simplicio.derived-edit-proposal/v1"
DERIVED_EDIT_RECEIPT_SCHEMA = "simplicio.derived-edit-receipt/v1"

EDIT_BOUNDED_AC = "edit-bounded"
MAX_OPERATIONS = 64
MAX_INTENT_LENGTH = 1024
_SAFE_HASH = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_REASON_DERIVED = "CONTRACT_ORIGIN_DERIVED"


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _blocked(reason_codes: list[str], diagnostics: list[str]) -> dict[str, Any]:
    return {
        "schema": DERIVED_EDIT_PROPOSAL_SCHEMA,
        "status": "blocked",
        "contract_origin": "derived",
        "reason_codes": _unique(reason_codes),
        "diagnostics": diagnostics,
        "receipt": {
            "schema": DERIVED_EDIT_RECEIPT_SCHEMA,
            "status": "blocked",
            "contract_origin": "derived",
            "reason_codes": _unique(reason_codes),
        },
    }


def _safe_target(raw: Any) -> tuple[str | None, str | None]:
    if not isinstance(raw, str):
        return None, "target must be a string"
    target = raw.replace("\\", "/").strip()
    if (
        not target
        or target in {".", ".."}
        or target.startswith(("/", "//"))
        or _WINDOWS_DRIVE.match(target)
        or any(part in {"", ".", ".."} for part in target.split("/"))
        or any(ord(char) < 32 for char in target)
        or any(char in target for char in "*?[]")
    ):
        return None, f"unsafe or ambiguous target: {raw!r}"
    return target, None


def _string_field(
    operation: Mapping[str, Any], name: str, *, required: bool
) -> tuple[str | None, str | None]:
    value = operation.get(name)
    if value is None and not required:
        return None, None
    if not isinstance(value, str):
        return None, f"{name} must be a string"
    return value, None


def _expected_hash(operation: Mapping[str, Any], *, old: str | None) -> tuple[str | None, str | None]:
    provided = operation.get("expected_content_hash")
    if provided is not None:
        if not isinstance(provided, str) or not _SAFE_HASH.fullmatch(provided):
            return None, "expected_content_hash must be a lowercase SHA-256 hex digest"
        return provided, None
    if old is not None:
        return hashlib.sha256(old.encode("utf-8")).hexdigest(), None
    return None, "an old value or expected_content_hash is required"


def _mapper_binding_from_payload(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Read a Mapper binding without deriving any Mapper semantics."""
    raw = payload.get("mapper_binding")
    direct_fields = {"repository_id", "generation", "source_tree_id", "source_hashes"}
    if raw is None and not any(field in payload for field in direct_fields):
        return None, []
    if raw is None:
        raw = {field: payload.get(field) for field in direct_fields}
        raw["schema"] = payload.get("mapper_binding_schema", "simplicio.mapper-binding/v1")
    if not isinstance(raw, Mapping):
        return None, ["mapper_binding must be an object"]
    errors = validate_mapper_binding(raw)
    if errors:
        return None, errors
    try:
        return canonical_mapper_binding(raw), []
    except MapperBindingError as exc:
        return None, [str(exc)]


def _normalise_operations(
    payload: Mapping[str, Any],
) -> tuple[list[dict[str, Any]] | None, list[str], list[str]]:
    raw_operations = payload.get("operations")
    if raw_operations is None and "target" in payload:
        raw_operations = [
            {
                "kind": payload.get("kind", "replace"),
                "target": payload.get("target"),
                "old": payload.get("old"),
                "new": payload.get("new"),
                "anchor": payload.get("anchor"),
                "expected_content_hash": payload.get("expected_content_hash"),
            }
        ]
    if not isinstance(raw_operations, list) or not raw_operations:
        return None, ["NEEDS_CONTEXT"], ["at least one bounded edit operation is required"]
    if len(raw_operations) > MAX_OPERATIONS:
        return None, ["UNSUPPORTED_EDIT"], [f"at most {MAX_OPERATIONS} operations are supported"]

    declared_targets = payload.get("targets", [])
    if isinstance(declared_targets, str):
        declared_targets = [declared_targets]
    if not isinstance(declared_targets, list):
        return None, ["AMBIGUOUS_TARGET"], ["targets must be a list of relative paths"]

    normalised_declared: list[str] = []
    for raw_target in declared_targets:
        target, error = _safe_target(raw_target)
        if error:
            return None, ["AMBIGUOUS_TARGET"], [error]
        assert target is not None
        normalised_declared.append(target)
    if len(normalised_declared) != len(set(normalised_declared)):
        return None, ["AMBIGUOUS_TARGET"], ["targets contains duplicates"]

    normalised: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for index, raw_operation in enumerate(raw_operations):
        if not isinstance(raw_operation, Mapping):
            return None, ["UNSUPPORTED_EDIT"], [f"operation {index} must be an object"]
        kind = raw_operation.get("kind", "replace")
        if kind not in {"replace", "insert", "delete", "create"}:
            return None, ["UNSUPPORTED_EDIT"], [f"operation {index} has unsupported kind {kind!r}"]

        raw_target = raw_operation.get("target")
        if raw_target is None:
            if len(normalised_declared) == 1:
                raw_target = normalised_declared[0]
            else:
                return None, ["AMBIGUOUS_TARGET"], [f"operation {index} has no unique target"]
        target, error = _safe_target(raw_target)
        if error:
            return None, ["AMBIGUOUS_TARGET"], [error]
        assert target is not None
        if target in seen_targets:
            return None, ["AMBIGUOUS_TARGET"], [f"target {target!r} has multiple operations"]
        seen_targets.add(target)

        old, error = _string_field(raw_operation, "old", required=False)
        if error:
            return None, ["UNSUPPORTED_EDIT"], [f"operation {index}: {error}"]
        new, error = _string_field(
            raw_operation,
            "new",
            required=kind in {"replace", "insert", "create"},
        )
        if error:
            return None, ["UNSUPPORTED_EDIT"], [f"operation {index}: {error}"]
        anchor, error = _string_field(raw_operation, "anchor", required=kind == "insert")
        if error:
            return None, ["UNSUPPORTED_EDIT"], [f"operation {index}: {error}"]

        expected_hash: str | None = None
        if kind in {"replace", "delete"}:
            expected_hash, error = _expected_hash(raw_operation, old=old)
            if error:
                return None, ["PRECONDITION_REQUIRED"], [f"operation {index}: {error}"]
        elif kind == "insert":
            if anchor is None:
                return None, ["AMBIGUOUS_TARGET"], [f"operation {index}: insert requires an anchor"]
            expected_hash, error = _expected_hash(raw_operation, old=anchor)
            if error:
                return None, ["PRECONDITION_REQUIRED"], [f"operation {index}: {error}"]
        elif old is not None or raw_operation.get("expected_content_hash") is not None:
            return None, ["UNSUPPORTED_EDIT"], [f"operation {index}: create cannot carry old content"]

        if kind == "replace" and old == new:
            return None, ["UNSUPPORTED_EDIT"], [f"operation {index}: replacement is a no-op"]

        item: dict[str, Any] = {"kind": kind, "target": target}
        if old is not None:
            item["old"] = old
        if anchor is not None:
            item["anchor"] = anchor
        if new is not None:
            item["new"] = new
        if expected_hash is not None:
            item["expected_content_hash"] = expected_hash
        normalised.append(item)

    if normalised_declared and set(normalised_declared) != seen_targets:
        return None, ["AMBIGUOUS_TARGET"], ["declared targets must equal the operation write set"]

    normalised.sort(
        key=lambda item: (item["target"], item["kind"], item.get("old", ""), item.get("anchor", ""))
    )
    return normalised, [], []


def derive_ad_hoc_edit(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deterministic proposal or a structured, non-executing block."""

    if not isinstance(payload, Mapping):
        return _blocked(["UNSUPPORTED_EDIT"], ["edit intent must be an object"])

    intent = payload.get("intent")
    if not isinstance(intent, str) or not intent.strip():
        return _blocked(["NEEDS_CONTEXT"], ["intent is required"])
    if len(intent) > MAX_INTENT_LENGTH:
        return _blocked(["UNSUPPORTED_EDIT"], [f"intent exceeds {MAX_INTENT_LENGTH} characters"])

    operations, reason_codes, diagnostics = _normalise_operations(payload)
    if operations is None:
        return _blocked(reason_codes, diagnostics)

    context_snapshot_id = payload.get("context_snapshot_id", "")
    context_handle = payload.get("context_handle", "")
    if not isinstance(context_snapshot_id, str) or not isinstance(context_handle, str):
        return _blocked(["UNSUPPORTED_EDIT"], ["context_snapshot_id and context_handle must be strings"])

    mapper_binding, mapper_binding_errors = _mapper_binding_from_payload(payload)
    if mapper_binding_errors:
        return _blocked(["MAPPER_BINDING_INVALID"], mapper_binding_errors)
    if payload.get("require_mapper_binding") and mapper_binding is None:
        return _blocked(["MAPPER_BINDING_REQUIRED"], ["a canonical Mapper binding is required"])

    input_payload: dict[str, Any] = {
        "schema": AD_HOC_EDIT_SCHEMA,
        "intent": intent.strip(),
        "operations": operations,
        "context_snapshot_id": context_snapshot_id,
        "context_handle": context_handle,
    }
    if mapper_binding is not None:
        input_payload["mapper_binding"] = mapper_binding
    input_digest = canonical_hash(input_payload)
    plan_id = f"plan-edit-{input_digest[:16]}"
    effect_id = f"effect-edit-{input_digest[:16]}"
    verification_id = f"verification-edit-{input_digest[:16]}"
    idempotency_key = f"edit-{input_digest[:24]}"

    write_set = [item["target"] for item in operations]
    preconditions = [
        (
            f"path_absent:{item['target']}"
            if item["kind"] == "create"
            else f"content_sha256:{item['target']}:{item['expected_content_hash']}"
        )
        for item in operations
    ]
    if mapper_binding is not None:
        preconditions.append(f"mapper_binding:{mapper_binding_digest(mapper_binding)}")
    edit_node = PlanNode(
        node_id="edit",
        capability="edit.apply",
        outputs=write_set,
        read_set=write_set,
        write_set=write_set,
        risk="medium",
        reason_codes=[_REASON_DERIVED, "WRITE_SET_BOUNDED", "PRECONDITION_REQUIRED"],
        acceptance_criteria_refs=[EDIT_BOUNDED_AC],
        requires_gate=True,
        checkpoint_required=True,
        rollback_strategy="runtime-receipt",
        semantic_inputs=[f"intent:{input_digest}"],
    )
    verify_node = PlanNode(
        node_id="verify",
        capability="edit.verify",
        depends_on=["edit"],
        inputs=write_set,
        reason_codes=["POSTCONDITION_REQUIRED"],
    )
    plan = PlanDAG(
        plan_id=plan_id,
        goal_id=f"goal-edit-{input_digest[:16]}",
        context_snapshot_id=context_snapshot_id,
        revision=str(payload.get("revision", "contractless-v1")),
        nodes=[edit_node, verify_node],
        producer_id="simplicio-dev-cli",
        consumer_id="simplicio-runtime",
        trace_id=payload.get("trace_id") if isinstance(payload.get("trace_id"), str) else None,
        context_handle=context_handle,
        mapper_binding=mapper_binding,
    )
    effect = EffectPlan(
        effect_id=effect_id,
        plan_node_id="edit",
        kind="write",
        authority_required="runtime.effect.edit",
        idempotency_key=idempotency_key,
        preconditions=preconditions,
        patch_ref=f"simplicio-ad-hoc:{input_digest}",
        context_handle=context_handle,
    )
    raw_timeout = payload.get("verification_timeout_s", 60.0)
    try:
        timeout_s = float(raw_timeout)
    except (TypeError, ValueError):
        return _blocked(["UNSUPPORTED_EDIT"], ["verification_timeout_s must be numeric"])
    if not 1.0 <= timeout_s <= 3600.0:
        return _blocked(["UNSUPPORTED_EDIT"], ["verification_timeout_s must be between 1 and 3600 seconds"])

    verification = VerificationPlan(
        verification_id=verification_id,
        plan_node_id="verify",
        verifier="simplicio-runtime",
        command_or_capability="simplicio.edit.verify",
        timeout_s=timeout_s,
        environment={"input_digest": input_digest},
        acceptance_criteria_refs=[EDIT_BOUNDED_AC],
        expected_evidence=["write_set", "precondition_results", "postcondition", "receipt"],
        stop_criteria=["precondition_failed", "postcondition_failed"],
        abstention_criteria=["context_snapshot_unavailable", "runtime_authority_unavailable"],
        replan_criteria=["target_changed", "content_hash_mismatch"],
    )
    try:
        plan.validate(effects=[effect], verifications=[verification])
    except Exception as exc:  # noqa: BLE001 - contract validation is reported as a block
        return _blocked(["UNSUPPORTED_EDIT"], [f"derived contract validation failed: {exc}"])

    plan_dict = plan.to_dict()
    effect_dict = effect.to_dict()
    verification_dict = verification.to_dict()
    proposal = {
        "schema": DERIVED_EDIT_PROPOSAL_SCHEMA,
        "contract_origin": "derived",
        "intent": intent.strip(),
        "input_digest": input_digest,
        "write_set": write_set,
        "operations": operations,
        "preconditions": preconditions,
        "effect": effect_dict,
        "runtime_binding_required": [
            "context_snapshot_id",
            "lease",
            "fence",
            "policy_revision",
            "authorization",
            "mapper_binding",
        ],
        "plan_digest": plan.canonical_hash(),
    }
    if mapper_binding is not None:
        proposal["mapper_binding"] = mapper_binding
        proposal["mapper_binding_digest"] = mapper_binding_digest(mapper_binding)
    proposal_digest = canonical_hash(
        {
            "proposal": proposal,
            "verification_plan": verification_dict,
            "plan_dag": plan_dict,
        }
    )
    receipt: dict[str, Any] = {
        "schema": DERIVED_EDIT_RECEIPT_SCHEMA,
        "status": "derived",
        "contract_origin": "derived",
        "proposal_digest": proposal_digest,
        "write_set": write_set,
        "reason_codes": [
            _REASON_DERIVED,
            "WRITE_SET_BOUNDED",
            "PRECONDITION_REQUIRED",
            "RUNTIME_ENVELOPE_REQUIRED",
        ],
    }
    if mapper_binding is not None:
        receipt["mapper_binding"] = mapper_binding
        receipt["mapper_binding_digest"] = mapper_binding_digest(mapper_binding)
    return {
        "schema": DERIVED_EDIT_PROPOSAL_SCHEMA,
        "status": "derived",
        "contract_origin": "derived",
        "proposal": {**proposal, "proposal_digest": proposal_digest},
        "verification_plan": verification_dict,
        "plan_dag": plan_dict,
        "receipt": receipt,
    }
