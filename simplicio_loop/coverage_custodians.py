"""Coverage Atlas -> Virtual Custodian authority reducer (issue #784).

This module is deliberately I/O-free. Mapper observations and worker receipts are
untrusted data; only this Loop reducer may authorize dispatch or transition a
gap to VERIFIED. Stable content digests make decisions replayable.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

COVERAGE_DELTA_SCHEMA = "simplicio.coverage-delta/v1"
CUSTODIAN_ADDRESS_SCHEMA = "simplicio.custodian-address/v1"
WORK_ENVELOPE_SCHEMA = "simplicio.custodian-work-envelope/v1"
CUSTODIAN_RECEIPT_SCHEMA = "simplicio.custodian-receipt/v1"
WORKER_VERDICT_SCHEMA = "simplicio.custodian-verdict/v1"
LEDGER_SCHEMA = "simplicio.work-gap-ledger/v1"

ACTION_DISPATCH = "DISPATCH"
ACTION_DEFER = "DEFER"
ACTION_NOT_APPLICABLE = "NOT_APPLICABLE"

STATE_OPEN = "OPEN"
STATE_DISPATCHED = "DISPATCHED"
STATE_REPORTED_FIXED = "REPORTED_FIXED"
STATE_VERIFIED = "VERIFIED"
STATE_BLOCKED = "BLOCKED"

KNOWN_GAP_KINDS = frozenset({
    "missing_owner", "missing_producer", "missing_consumer", "missing_test",
    "missing_integration", "missing_evidence", "cache_integrity",
    "index_generation", "knowledge_federation", "python_rust_parity",
})
FAST_KINDS = frozenset({
    "cache_integrity", "index_generation", "knowledge_federation",
    "python_rust_parity",
})
TERMINAL_STATES = frozenset({STATE_VERIFIED})


class ContractError(ValueError):
    """Input cannot be safely interpreted under the v1 contracts."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _require_text(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ContractError("%s must be a non-empty string" % key)
    return result


def _require_schema(value: Mapping[str, Any], expected: str) -> None:
    if value.get("schema") != expected:
        raise ContractError("schema must be %s" % expected)


def validate_coverage_delta(delta: Mapping[str, Any]) -> Dict[str, Any]:
    _require_schema(delta, COVERAGE_DELTA_SCHEMA)
    source = _require_text(delta, "source")
    base_digest = _require_text(delta, "base_atlas_digest")
    gaps = delta.get("gaps")
    if not isinstance(gaps, list):
        raise ContractError("gaps must be a list")

    normalized: List[Dict[str, Any]] = []
    seen = set()
    for raw in gaps:
        if not isinstance(raw, Mapping):
            raise ContractError("every gap must be an object")
        gap_id = _require_text(raw, "gap_id")
        kind = _require_text(raw, "kind")
        subject = _require_text(raw, "subject")
        if kind not in KNOWN_GAP_KINDS:
            raise ContractError("unknown gap kind: %s" % kind)
        expected_id = digest({
            "base_atlas_digest": base_digest,
            "kind": kind,
            "subject": subject,
        })
        if gap_id != expected_id:
            raise ContractError("gap_id is not content-addressed")
        if gap_id in seen:
            raise ContractError("duplicate gap_id")
        seen.add(gap_id)
        normalized.append({
            "gap_id": gap_id,
            "kind": kind,
            "subject": subject,
            "evidence_refs": sorted(set(raw.get("evidence_refs", []))),
        })
    normalized.sort(key=lambda item: item["gap_id"])
    body = {
        "schema": COVERAGE_DELTA_SCHEMA,
        "source": source,
        "base_atlas_digest": base_digest,
        "gaps": normalized,
    }
    supplied = delta.get("delta_digest")
    computed = digest(body)
    if supplied is not None and supplied != computed:
        raise ContractError("delta_digest mismatch")
    body["delta_digest"] = computed
    return body


def validate_address(address: Mapping[str, Any]) -> Dict[str, Any]:
    _require_schema(address, CUSTODIAN_ADDRESS_SCHEMA)
    address_id = _require_text(address, "address_id")
    capability = _require_text(address, "capability")
    target = _require_text(address, "target")
    if capability not in FAST_KINDS:
        raise ContractError("unsupported custodian capability")
    body = {
        "schema": CUSTODIAN_ADDRESS_SCHEMA,
        "capability": capability,
        "target": target,
        "generation": int(address.get("generation", 0)),
    }
    if body["generation"] < 0:
        raise ContractError("generation must be non-negative")
    if address_id != digest(body):
        raise ContractError("address_id mismatch")
    body["address_id"] = address_id
    return body


def _select_address(
    gap: Mapping[str, Any], addresses: Sequence[Mapping[str, Any]]
) -> Optional[Dict[str, Any]]:
    candidates = [
        validate_address(item) for item in addresses
        if item.get("capability") == gap["kind"]
    ]
    candidates.sort(key=lambda item: (-item["generation"], item["address_id"]))
    return candidates[0] if candidates else None


def decide(
    delta: Mapping[str, Any],
    addresses: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Return Loop-owned decisions; this function never materializes a worker."""
    clean = validate_coverage_delta(delta)
    budget = int(policy.get("dispatch_budget", 0))
    if budget < 0:
        raise ContractError("dispatch_budget must be non-negative")
    deferred = set(policy.get("deferred_gap_ids", []))
    not_applicable = set(policy.get("not_applicable_gap_ids", []))
    decisions: List[Dict[str, Any]] = []

    for gap in clean["gaps"]:
        action = ACTION_DEFER
        reason = "loop_policy_deferred"
        address = None
        if gap["gap_id"] in not_applicable:
            action, reason = ACTION_NOT_APPLICABLE, "loop_policy_not_applicable"
        elif gap["gap_id"] in deferred:
            action, reason = ACTION_DEFER, "loop_policy_deferred"
        elif gap["kind"] not in FAST_KINDS:
            action, reason = ACTION_DEFER, "non_fast_owner_required"
        else:
            address = _select_address(gap, addresses)
            if address is None:
                action, reason = ACTION_DEFER, "custodian_unavailable"
            elif budget <= 0:
                action, reason = ACTION_DEFER, "budget_exhausted"
            else:
                action, reason = ACTION_DISPATCH, "authorized_by_loop"
                budget -= 1
        decisions.append({
            "gap_id": gap["gap_id"],
            "action": action,
            "reason": reason,
            "custodian_address_id": address and address["address_id"],
        })
    return decisions


def build_envelope(
    gap: Mapping[str, Any],
    decision: Mapping[str, Any],
    run: Mapping[str, Any],
    budget: Mapping[str, Any],
) -> Dict[str, Any]:
    if decision.get("action") != ACTION_DISPATCH:
        raise ContractError("only a Loop DISPATCH decision can create an envelope")
    gap_id = _require_text(gap, "gap_id")
    if decision.get("gap_id") != gap_id:
        raise ContractError("decision/gap mismatch")
    body = {
        "schema": WORK_ENVELOPE_SCHEMA,
        "gap_id": gap_id,
        "acceptance_criteria": _require_text(gap, "acceptance_criteria"),
        "custodian_address_id": _require_text(decision, "custodian_address_id"),
        "run_id": _require_text(run, "run_id"),
        "fence": _require_text(run, "fence"),
        "plan_revision": _require_text(run, "plan_revision"),
        "budget": dict(budget),
    }
    body["idempotency_key"] = digest({
        "gap_id": body["gap_id"],
        "run_id": body["run_id"],
        "fence": body["fence"],
        "plan_revision": body["plan_revision"],
    })
    body["envelope_digest"] = digest(body)
    return body


def validate_receipt(
    receipt: Mapping[str, Any], envelope: Mapping[str, Any]
) -> Tuple[bool, str]:
    try:
        _require_schema(receipt, CUSTODIAN_RECEIPT_SCHEMA)
        _require_schema(envelope, WORK_ENVELOPE_SCHEMA)
        if receipt.get("gap_id") != envelope.get("gap_id"):
            return False, "gap_mismatch"
        if receipt.get("envelope_digest") != envelope.get("envelope_digest"):
            return False, "envelope_mismatch"
        if receipt.get("idempotency_key") != envelope.get("idempotency_key"):
            return False, "idempotency_mismatch"
        if receipt.get("fence") != envelope.get("fence"):
            return False, "fence_mismatch"
        if receipt.get("verdict_schema") != WORKER_VERDICT_SCHEMA:
            return False, "invalid_fast_verdict"
        if receipt.get("verdict") not in ("FIXED", "NO_CHANGE", "BLOCKED"):
            return False, "invalid_fast_verdict"
        if not receipt.get("evidence_refs"):
            return False, "missing_evidence"
        unsigned = dict(receipt)
        supplied = unsigned.pop("receipt_digest", None)
        if supplied != digest(unsigned):
            return False, "receipt_digest_mismatch"
    except (ContractError, TypeError, ValueError):
        return False, "malformed_receipt"
    return True, "ok"


def reduce_ledger(
    ledger: Optional[Mapping[str, Any]],
    delta: Mapping[str, Any],
    decisions: Sequence[Mapping[str, Any]],
    envelopes: Sequence[Mapping[str, Any]] = (),
    receipts: Sequence[Mapping[str, Any]] = (),
    verification_delta: Optional[Mapping[str, Any]] = None,
    verifier: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Replay inputs into the authoritative Work Gap Ledger.

    Worker FIXED means REPORTED_FIXED only. VERIFIED requires a subsequent Mapper
    delta where the gap disappeared and an independent verifier receipt.
    """
    clean = validate_coverage_delta(delta)
    previous = dict((ledger or {}).get("entries", {}))
    entries: Dict[str, Dict[str, Any]] = {}

    decision_by_gap = {item["gap_id"]: dict(item) for item in decisions}
    envelope_by_gap = {item["gap_id"]: dict(item) for item in envelopes}
    receipt_by_gap = {item["gap_id"]: dict(item) for item in receipts}
    verification_open = None
    if verification_delta is not None:
        verification_open = {
            item["gap_id"] for item in validate_coverage_delta(verification_delta)["gaps"]
        }

    for gap in clean["gaps"]:
        gap_id = gap["gap_id"]
        decision = decision_by_gap.get(gap_id, {
            "action": ACTION_DEFER, "reason": "missing_loop_decision"
        })
        entry = {
            "gap_id": gap_id,
            "kind": gap["kind"],
            "subject": gap["subject"],
            "state": STATE_OPEN,
            "decision": decision.get("action"),
            "reason": decision.get("reason"),
            "envelope_digest": None,
            "receipt_digest": None,
            "verification_digest": None,
        }
        envelope = envelope_by_gap.get(gap_id)
        receipt = receipt_by_gap.get(gap_id)
        if decision.get("action") == ACTION_DISPATCH:
            if envelope is None:
                entry.update(state=STATE_BLOCKED, reason="authorized_without_envelope")
            else:
                entry.update(
                    state=STATE_DISPATCHED,
                    envelope_digest=envelope.get("envelope_digest"),
                )
                if receipt is not None:
                    valid, reason = validate_receipt(receipt, envelope)
                    if not valid:
                        entry.update(state=STATE_BLOCKED, reason=reason)
                    else:
                        entry["receipt_digest"] = receipt["receipt_digest"]
                        if receipt["verdict"] == "FIXED":
                            entry.update(state=STATE_REPORTED_FIXED, reason="awaiting_mapper_rescan")
                        elif receipt["verdict"] == "BLOCKED":
                            entry.update(state=STATE_BLOCKED, reason="fast_reported_blocked")
                        else:
                            entry.update(state=STATE_OPEN, reason="fast_reported_no_change")
        if entry["state"] == STATE_REPORTED_FIXED and verification_open is not None:
            independent = (
                isinstance(verifier, Mapping)
                and verifier.get("schema") == "simplicio.independent-verification/v1"
                and verifier.get("gap_id") == gap_id
                and verifier.get("verdict") == "PASS"
                and verifier.get("agent_instance_id") != receipt.get("agent_instance_id")
                and bool(verifier.get("evidence_refs"))
            )
            if gap_id not in verification_open and independent:
                entry.update(
                    state=STATE_VERIFIED,
                    reason="mapper_rescan_and_independent_verifier_passed",
                    verification_digest=digest(verifier),
                )
            elif gap_id in verification_open:
                entry.update(state=STATE_OPEN, reason="mapper_rescan_gap_still_open")
            else:
                entry.update(state=STATE_BLOCKED, reason="independent_verification_missing")
        old = previous.get(gap_id)
        if old and old.get("state") == STATE_VERIFIED and entry["state"] != STATE_VERIFIED:
            entry.update(state=STATE_BLOCKED, reason="verified_gap_regressed")
        entries[gap_id] = entry

    body = {
        "schema": LEDGER_SCHEMA,
        "source_delta_digest": clean["delta_digest"],
        "entries": {key: entries[key] for key in sorted(entries)},
    }
    body["ledger_digest"] = digest(body)
    return body


def terminal(ledger: Mapping[str, Any]) -> bool:
    """Only Loop may use this result as completion input."""
    _require_schema(ledger, LEDGER_SCHEMA)
    entries = ledger.get("entries")
    return bool(entries) and all(
        item.get("state") in TERMINAL_STATES for item in entries.values()
    )
