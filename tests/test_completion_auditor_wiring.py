from contextlib import ExitStack
from unittest.mock import patch

import simplicio_loop.completion_auditor as ca
from simplicio_loop.work_gap_ledger import (
    WorkGap, WorkGapLedger, sha256_evidence, validate_work_gap_snapshot,
)


def _valid_snapshot():
    ledger = WorkGapLedger()
    gap = WorkGap(
        "REQ-785", "AC-1",
        expected_evidence=("implementation", "verification", "integration", "delivery"),
        delivery_target="main", expected_revision="commit-abc",
    )
    ledger.register(gap)
    ledger.assign_owner(
        gap.key, owner_project="simplicio-loop", owner_agent="agent-1",
        actor_id="coverage-1",
    )
    ledger.transition(gap.key, "PLANNED", actor_id="planner-1", seat="planner")
    ledger.transition(
        gap.key, "IMPLEMENTED", actor_id="executor-1", seat="executor",
        executor_id="executor-1", expected_revision="commit-abc",
        evidence=(sha256_evidence("implementation", "commit:abc", b"patch", "executor-1"),),
    )
    ledger.transition(
        gap.key, "VERIFIED", actor_id="verifier-1", seat="verifier",
        verifier_id="verifier-1",
        evidence=(sha256_evidence("verification", "test:1", b"ok", "verifier-1"),),
    )
    ledger.transition(
        gap.key, "INTEGRATED", actor_id="integrator-1", seat="integration",
        evidence=(sha256_evidence("integration", "wheel:1", b"wheel", "integrator-1"),),
    )
    ledger.transition(
        gap.key, "DELIVERED", actor_id="auditor-1", seat="completion",
        completion_auditor_id="auditor-1",
        evidence=(sha256_evidence("delivery", "github:merged", b"merged", "auditor-1"),),
        installed_artifact={
            "expected_commit": "commit-abc", "installed_commit": "commit-abc",
            "sha256": "a" * 64, "match": True,
        },
        source_requery={"commit": "commit-abc", "state": "merged"},
    )
    return ledger.snapshot()


def test_invalid_or_unresolved_snapshot_is_not_ready():
    assert validate_work_gap_snapshot({})["ok"] is False
    unresolved = _valid_snapshot()
    unresolved["gaps"][0]["state"] = "VERIFIED"
    assert validate_work_gap_snapshot(unresolved)["ok"] is False


def test_audit_blocks_terminal_verdict_when_ledger_is_invalid():
    with ExitStack() as stack:
        stack.enter_context(patch.object(ca.sa, "validate_graph", return_value=(True, [])))
        stack.enter_context(patch.object(ca, "validate_stage_lineage", return_value={"stage": {"verdict": "ok", "evidence_refs": []}}))
        stack.enter_context(patch.object(ca, "validate_auditor_isolation", return_value=(True, [])))
        stack.enter_context(patch.object(ca, "build_ac_coverage_matrix", return_value={"contradictory": [], "missing": [], "unverified": [], "rows": []}))
        stack.enter_context(patch.object(ca, "revalidate_watcher", return_value={"ok": True, "reason_code": "ok", "detail": {}}))
        stack.enter_context(patch.object(ca, "revalidate_delivery", return_value={"ok": True, "reason_code": "ok", "detail": {}}))
        stack.enter_context(patch.object(ca, "detect_regression", return_value={"regressed": False}))
        result = ca.audit(
            graph={}, instances=[], receipts=[], run_identity={"run_id": "run-1"},
            auditor_instance_id="auditor-1", ac_items=[], criteria_results=[],
            work_gap_snapshot={},
        )
    assert result["verdict"] == ca.VERDICT_BLOCKED
    assert result["reason_code"] == "work_gap_ledger_invalid"


def test_completion_receipt_hash_includes_work_gap_check():
    base = {
        "verdict": ca.VERDICT_COMPLETE,
        "reason_code": ca.REASON_OK,
        "run_identity": {"run_id": "run-1", "task_id": "task-1"},
        "work_gap_check": validate_work_gap_snapshot(_valid_snapshot()),
    }
    changed = {
        **base,
        "work_gap_check": {"ok": False, "reason_code": "tampered", "detail": {}},
    }
    first = ca.build_completion_receipt(base, created_at="2026-07-27T00:00:00Z")
    second = ca.build_completion_receipt(changed, created_at="2026-07-27T00:00:00Z")
    assert first["evidence_set_hash"] != second["evidence_set_hash"]
    assert first["receipt_id"] != second["receipt_id"]
