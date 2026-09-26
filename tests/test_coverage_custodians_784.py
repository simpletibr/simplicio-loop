"""Contract and reducer tests for issue #784."""
from __future__ import annotations

import copy

import pytest

from simplicio_loop import coverage_custodians as cc


BASE = "sha256:" + "a" * 64


def gap(kind="cache_integrity", subject="cache:main"):
    item = {"base_atlas_digest": BASE, "kind": kind, "subject": subject}
    return {
        "gap_id": cc.digest(item),
        "kind": kind,
        "subject": subject,
        "acceptance_criteria": "rescan proves the gap absent",
        "evidence_refs": ["mapper://atlas/main"],
    }


def delta(*gaps):
    body = {
        "schema": cc.COVERAGE_DELTA_SCHEMA,
        "source": "simplicio-mapper@0.20",
        "base_atlas_digest": BASE,
        "gaps": list(gaps),
    }
    normalized = cc.validate_coverage_delta(body)
    return normalized


def address(capability="cache_integrity", generation=1):
    body = {
        "schema": cc.CUSTODIAN_ADDRESS_SCHEMA,
        "capability": capability,
        "target": "fast://custodian/" + capability,
        "generation": generation,
    }
    body["address_id"] = cc.digest(body)
    return body


def dispatch_fixture():
    item = gap()
    source = delta(item)
    decision = cc.decide(source, [address()], {"dispatch_budget": 1})[0]
    envelope = cc.build_envelope(
        item,
        decision,
        {"run_id": "run-1", "fence": "fence-9", "plan_revision": "3"},
        {"cpu_ms": 100, "max_attempts": 1},
    )
    receipt = {
        "schema": cc.CUSTODIAN_RECEIPT_SCHEMA,
        "verdict_schema": cc.WORKER_VERDICT_SCHEMA,
        "gap_id": item["gap_id"],
        "envelope_digest": envelope["envelope_digest"],
        "idempotency_key": envelope["idempotency_key"],
        "fence": envelope["fence"],
        "agent_instance_id": "fast-worker-1",
        "verdict": "FIXED",
        "evidence_refs": ["hbp://receipt/1"],
    }
    receipt["receipt_digest"] = cc.digest(receipt)
    return item, source, decision, envelope, receipt


def test_delta_is_order_independent_and_content_addressed():
    left, right = gap(subject="cache:a"), gap(subject="cache:b")
    assert delta(left, right) == delta(right, left)


def test_tampered_gap_id_is_rejected():
    item = gap()
    item["subject"] = "cache:tampered"
    with pytest.raises(cc.ContractError, match="content-addressed"):
        delta(item)


def test_clean_delta_has_no_decisions_or_workers():
    clean = delta()
    assert cc.decide(clean, [address()], {"dispatch_budget": 10}) == []


def test_loop_policy_is_the_only_dispatch_authority():
    item = gap()
    source = delta(item)
    assert cc.decide(source, [address()], {"dispatch_budget": 0})[0]["action"] == cc.ACTION_DEFER
    assert cc.decide(source, [address()], {
        "dispatch_budget": 10, "deferred_gap_ids": [item["gap_id"]]
    })[0]["action"] == cc.ACTION_DEFER
    assert cc.decide(source, [address()], {
        "dispatch_budget": 10, "not_applicable_gap_ids": [item["gap_id"]]
    })[0]["action"] == cc.ACTION_NOT_APPLICABLE


def test_non_fast_gap_never_dispatches_to_fast():
    item = gap(kind="missing_consumer", subject="contract:receipt-v1")
    decision = cc.decide(delta(item), [address()], {"dispatch_budget": 1})[0]
    assert decision == {
        "gap_id": item["gap_id"],
        "action": cc.ACTION_DEFER,
        "reason": "non_fast_owner_required",
        "custodian_address_id": None,
    }


def test_highest_generation_address_is_selected_without_worker_materialization():
    item = gap()
    old, current = address(generation=1), address(generation=9)
    decision = cc.decide(delta(item), [old, current], {"dispatch_budget": 1})[0]
    assert decision["custodian_address_id"] == current["address_id"]
    assert "worker" not in decision


def test_dispatch_budget_applies_deterministically():
    one, two = gap(subject="cache:one"), gap(subject="cache:two")
    decisions = cc.decide(delta(two, one), [address()], {"dispatch_budget": 1})
    assert [d["action"] for d in decisions].count(cc.ACTION_DISPATCH) == 1
    assert decisions[0]["gap_id"] < decisions[1]["gap_id"]


def test_envelope_requires_explicit_dispatch():
    item = gap()
    with pytest.raises(cc.ContractError, match="DISPATCH"):
        cc.build_envelope(
            item,
            {"gap_id": item["gap_id"], "action": cc.ACTION_DEFER},
            {"run_id": "r", "fence": "f", "plan_revision": "1"},
            {},
        )


def test_duplicate_dispatch_has_same_idempotency_key():
    item, source, decision, first, _ = dispatch_fixture()
    second = cc.build_envelope(
        item,
        decision,
        {"run_id": "run-1", "fence": "fence-9", "plan_revision": "3"},
        {"cpu_ms": 100, "max_attempts": 1},
    )
    assert first == second


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("gap_id", "gap_mismatch"),
        ("envelope_digest", "envelope_mismatch"),
        ("idempotency_key", "idempotency_mismatch"),
        ("fence", "fence_mismatch"),
    ],
)
def test_receipt_must_be_bound_to_authorization(field, reason):
    _, _, _, envelope, receipt = dispatch_fixture()
    receipt[field] = "tampered"
    receipt["receipt_digest"] = cc.digest({
        key: value for key, value in receipt.items() if key != "receipt_digest"
    })
    assert cc.validate_receipt(receipt, envelope) == (False, reason)


def test_fast_fixed_cannot_mark_delivered_or_verified():
    item, source, decision, envelope, receipt = dispatch_fixture()
    ledger = cc.reduce_ledger(
        None, source, [decision], [envelope], [receipt]
    )
    entry = ledger["entries"][item["gap_id"]]
    assert entry["state"] == cc.STATE_REPORTED_FIXED
    assert not cc.terminal(ledger)


def test_mapper_rescan_alone_cannot_verify():
    item, source, decision, envelope, receipt = dispatch_fixture()
    ledger = cc.reduce_ledger(
        None, source, [decision], [envelope], [receipt],
        verification_delta=delta(),
    )
    assert ledger["entries"][item["gap_id"]]["state"] == cc.STATE_BLOCKED
    assert ledger["entries"][item["gap_id"]]["reason"] == "independent_verification_missing"


def test_independent_verifier_and_clean_rescan_verify():
    item, source, decision, envelope, receipt = dispatch_fixture()
    verifier = {
        "schema": "simplicio.independent-verification/v1",
        "gap_id": item["gap_id"],
        "verdict": "PASS",
        "agent_instance_id": "reviewer-2",
        "evidence_refs": ["test://rescan/1"],
    }
    ledger = cc.reduce_ledger(
        None, source, [decision], [envelope], [receipt],
        verification_delta=delta(), verifier=verifier,
    )
    assert ledger["entries"][item["gap_id"]]["state"] == cc.STATE_VERIFIED
    assert cc.terminal(ledger)


def test_same_worker_cannot_be_independent_verifier():
    item, source, decision, envelope, receipt = dispatch_fixture()
    verifier = {
        "schema": "simplicio.independent-verification/v1",
        "gap_id": item["gap_id"],
        "verdict": "PASS",
        "agent_instance_id": "fast-worker-1",
        "evidence_refs": ["self://claim"],
    }
    ledger = cc.reduce_ledger(
        None, source, [decision], [envelope], [receipt],
        verification_delta=delta(), verifier=verifier,
    )
    assert ledger["entries"][item["gap_id"]]["state"] == cc.STATE_BLOCKED


def test_rescan_that_still_contains_gap_reopens_it():
    item, source, decision, envelope, receipt = dispatch_fixture()
    ledger = cc.reduce_ledger(
        None, source, [decision], [envelope], [receipt],
        verification_delta=source,
        verifier={
            "schema": "simplicio.independent-verification/v1",
            "gap_id": item["gap_id"],
            "verdict": "PASS",
            "agent_instance_id": "reviewer-2",
            "evidence_refs": ["test://claim"],
        },
    )
    assert ledger["entries"][item["gap_id"]]["state"] == cc.STATE_OPEN
    assert ledger["entries"][item["gap_id"]]["reason"] == "mapper_rescan_gap_still_open"


def test_tampered_receipt_fails_closed():
    item, source, decision, envelope, receipt = dispatch_fixture()
    receipt["verdict"] = "FIXED "
    ledger = cc.reduce_ledger(None, source, [decision], [envelope], [receipt])
    assert ledger["entries"][item["gap_id"]]["state"] == cc.STATE_BLOCKED


def test_ledger_digest_is_replay_stable():
    item, source, decision, envelope, receipt = dispatch_fixture()
    first = cc.reduce_ledger(None, source, [decision], [envelope], [receipt])
    second = cc.reduce_ledger(None, source, [decision], [envelope], [receipt])
    assert first == second
