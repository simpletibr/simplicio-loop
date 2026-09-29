"""Unit tests for the #430 `feedback_recovery_agent` concrete stage-agent role.

Covers: failure taxonomy classification, receipt-invalidation closure,
routing rules 1-10 from the issue, retry-budget enforcement, stall/repeated-
fingerprint escalation (via `scripts/loop_journal.py`), quarantine, external
reconciliation, and the forbidden-receipt-schema invariant -- all exercised
through the real composed entrypoint `build_feedback_recovery_receipt`, not
merely in isolation (the bug class AGENTS.md flags).
"""
from __future__ import annotations

import importlib.util
import json
import os

import pytest

from simplicio_loop.feedback_recovery_agent import (
    FAILURE_CLASSES,
    FEEDBACK_RECOVERY_RECEIPT_SCHEMA,
    FEEDBACK_RECOVERY_ROLE_ID,
    FORBIDDEN_RECEIPT_SCHEMAS,
    VERDICT_ESCALATED,
    VERDICT_QUARANTINED,
    VERDICT_RECONCILE_PENDING,
    VERDICT_ROUTED,
    FeedbackRecoveryAgentError,
    ForbiddenReceiptError,
    assert_receipt_schema_allowed,
    assert_route_target_valid,
    build_feedback_recovery_receipt,
    check_retry_budget,
    classify_failure,
    content_hash,
    invalidate_receipts,
    invalidation_closure,
    quarantine_item,
    receipt_is_routed,
    reconcile_external_effect,
    repeated_fingerprint_escalates,
    route_decision,
    signal_fingerprint,
    stall_verdict,
    to_stage_receipt,
)


# --------------------------------------------------------------------------- #
# Taxonomy classification
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("code,expected", [
    ("test_failure", "test_failure"),
    ("test_failed", "test_failure"),
    ("compile_error", "code_failure"),
    ("runner_timeout", "ci_infra_failure"),
    ("changes_requested", "review_change_requested"),
    ("base_moved", "base_drift"),
    ("conflict", "merge_conflict"),
    ("delivery_timeout", "delivery_unknown"),
    ("regression", "source_regression"),
    ("receipt_expired", "stale_receipt"),
    ("lease_lost", "lease_or_fence_loss"),
    ("worker_stuck", "agent_timeout"),
    ("missing_capability", "capability_missing"),
    ("secret_detected", "security_block"),
    ("repeated_fingerprint_stall", "repeated_fingerprint_stall"),
])
def test_classify_failure_taxonomy(code, expected):
    assert classify_failure(reason_code=code) == expected


def test_classify_failure_defaults_to_code_failure_conservatively():
    assert classify_failure(reason_code="totally-unknown-signal") == "code_failure"


def test_all_taxonomy_classes_have_a_route():
    for cls in FAILURE_CLASSES:
        decision = route_decision(failure_class=cls)
        assert_route_target_valid(decision["target_stage"])


def test_signal_fingerprint_stable_and_distinct():
    a = signal_fingerprint("FAILED test_login at app/auth.py:42 (0x7ffd) 1.3s")
    b = signal_fingerprint("FAILED test_login at app/auth.py:99 (0x1abc) 0.4s")
    c = signal_fingerprint("AssertionError: expected 3 got 4 in test_math")
    assert a == b and a != ""
    assert c != a


# --------------------------------------------------------------------------- #
# Receipt invalidation graph / closure
# --------------------------------------------------------------------------- #
def test_invalidation_closure_code_change_reaches_delivery_transitively():
    closure = invalidation_closure(["code_change"])
    assert "review" in closure
    assert "safety" in closure
    assert "delivery" in closure


def test_invalidation_closure_new_head_covers_evidence_review_checks():
    closure = invalidation_closure(["new_head"])
    for kind in ("evidence", "review", "checks", "delivery"):
        assert kind in closure


def test_invalidate_receipts_marks_stale_and_preserves_others():
    receipts = [
        {"kind": "review", "id": "r1"},
        {"kind": "planning", "id": "p1"},
        {"kind": "unrelated", "id": "u1"},
    ]
    stale = invalidate_receipts(receipts, dimensions=["code_change"])
    stale_ids = {r["id"] for r in stale}
    assert stale_ids == {"r1"}
    assert stale[0]["invalidated"] is True
    # original list untouched
    assert "invalidated" not in receipts[0]


# --------------------------------------------------------------------------- #
# Routing rules 1-10
# --------------------------------------------------------------------------- #
def test_rule2_code_change_routes_to_implementation_and_invalidates_review():
    decision = route_decision(failure_class="code_failure")
    assert decision["target_stage"] == "executing"
    assert "code_change" in decision["invalidation_dimensions"]


def test_rule3_scope_change_routes_to_planner():
    decision = route_decision(failure_class="code_failure", scope_changed=True)
    assert decision["target_stage"] == "planning"
    assert "scope_change" in decision["invalidation_dimensions"]
    assert decision["retryable"] is False


def test_rule4_risk_action_change_routes_to_safety():
    decision = route_decision(failure_class="test_failure", risk_action_changed=True)
    assert decision["target_stage"] == "safety_gate"
    assert "risk_action_change" in decision["invalidation_dimensions"]
    assert decision["retryable"] is False


def test_rule4_takes_priority_over_rule3_when_both_fire():
    decision = route_decision(failure_class="code_failure", scope_changed=True, risk_action_changed=True)
    assert decision["target_stage"] == "safety_gate"
    assert "scope_change" in decision["invalidation_dimensions"]
    assert "risk_action_change" in decision["invalidation_dimensions"]


def test_rule5_new_head_invalidates_dependent_evidence():
    decision = route_decision(failure_class="ci_infra_failure", new_head=True)
    assert "new_head" in decision["invalidation_dimensions"]


def test_rule6_flaky_infra_retries_without_code_change():
    decision = route_decision(failure_class="ci_infra_failure", is_flaky_infra=True)
    assert decision["retryable"] is True
    assert "code_change" not in decision["invalidation_dimensions"]


def test_rule7_uncertain_external_effect_requires_reconcile():
    decision = route_decision(failure_class="delivery_unknown")
    assert decision["requires_reconcile"] is True
    # class-level retryable baseline stays True; the reconcile gate is what
    # actually blocks the retry until reconciled (checked at the receipt level).
    assert decision["retryable"] is True


def test_rule8_repeated_fingerprint_escalates_via_journal_stall_detector():
    base = {"iteration": 0, "action": "retry", "hypothesis": "h", "note": "", "ts": "2026-01-01T00:00:00Z"}
    rows = [dict(base, iteration=i, gate="fail", fingerprint="deadbeef0001") for i in range(1, 5)]
    assert repeated_fingerprint_escalates(rows) is True
    verdict = stall_verdict(rows)
    assert verdict["verdict"] == "STALLED"


def test_rule8_progress_when_fingerprints_differ():
    base = {"iteration": 0, "action": "a", "hypothesis": "h", "note": "", "ts": "2026-01-01T00:00:00Z"}
    rows = [dict(base, iteration=1, gate="fail", fingerprint="aaa1"),
            dict(base, iteration=2, gate="fail", fingerprint="bbb2")]
    assert repeated_fingerprint_escalates(rows) is False


def test_rule9_quarantine_never_blocks_drain():
    q = quarantine_item(task_id="T-1", failure_class="ci_infra_failure", fingerprint="fp1", reason="budget exhausted")
    assert q["blocks_drain"] is False
    assert q["task_id"] == "T-1"


def test_rule10_post_complete_regression_reopens_stage_graph():
    decision = route_decision(failure_class="source_regression", post_complete=True)
    assert decision["reopen_stage_graph"] is True
    assert decision["target_stage"] == "planning"


def test_rule10_reopen_false_when_not_post_complete():
    decision = route_decision(failure_class="source_regression")
    assert decision["reopen_stage_graph"] is False


def test_route_decision_unknown_class_raises():
    with pytest.raises(FeedbackRecoveryAgentError):
        route_decision(failure_class="not-a-real-class")


# --------------------------------------------------------------------------- #
# Retry budget
# --------------------------------------------------------------------------- #
def test_retry_budget_allows_within_budget():
    r = check_retry_budget(prior_attempts=1, budget=3)
    assert r["retry_allowed"] is True
    assert r["attempt_number"] == 2


def test_retry_budget_exhausted():
    r = check_retry_budget(prior_attempts=3, budget=3)
    assert r["retry_allowed"] is False
    assert r["attempt_number"] == 3


# --------------------------------------------------------------------------- #
# External reconciliation
# --------------------------------------------------------------------------- #
def test_reconcile_unknown_stays_unreconciled():
    r = reconcile_external_effect(observed_state=None, expected_intent={"intent_id": "i1"})
    assert r["reconciled"] is False
    assert r["outcome"] == "unknown"


def test_reconcile_mismatched_intent():
    r = reconcile_external_effect(observed_state={"intent_id": "other", "succeeded": True},
                                   expected_intent={"intent_id": "i1"})
    assert r["reconciled"] is False
    assert r["outcome"] == "mismatch"


def test_reconcile_matched_succeeded():
    r = reconcile_external_effect(observed_state={"intent_id": "i1", "succeeded": True},
                                   expected_intent={"intent_id": "i1"})
    assert r["reconciled"] is True
    assert r["outcome"] == "succeeded"


# --------------------------------------------------------------------------- #
# Forbidden receipt schemas
# --------------------------------------------------------------------------- #
def test_assert_receipt_schema_allowed_rejects_forbidden():
    for schema in FORBIDDEN_RECEIPT_SCHEMAS:
        with pytest.raises(ForbiddenReceiptError):
            assert_receipt_schema_allowed(schema)


def test_own_schema_is_never_forbidden():
    assert FEEDBACK_RECOVERY_RECEIPT_SCHEMA not in FORBIDDEN_RECEIPT_SCHEMAS
    assert_receipt_schema_allowed(FEEDBACK_RECOVERY_RECEIPT_SCHEMA)  # does not raise


# --------------------------------------------------------------------------- #
# The composed receipt -- the REAL entrypoint every invariant must be wired
# into (not just unit-tested standalone).
# --------------------------------------------------------------------------- #
def test_build_receipt_routes_simple_test_failure():
    r = build_feedback_recovery_receipt(
        run_id="run1", task_id="T-1", attempt=1, reason_code="test_failed",
        prior_attempts=0, retry_budget=3,
    )
    assert r["schema"] == FEEDBACK_RECOVERY_RECEIPT_SCHEMA
    assert r["role_id"] == FEEDBACK_RECOVERY_ROLE_ID
    assert r["verdict"] == VERDICT_ROUTED
    assert r["target_stage"] == "executing"
    assert r["complete"] is False
    assert receipt_is_routed(r)
    assert r["receipt_hash"] == content_hash({k: v for k, v in r.items() if k != "receipt_hash"})


def test_build_receipt_delivery_unknown_blocks_on_reconcile():
    r = build_feedback_recovery_receipt(
        run_id="run1", task_id="T-2", attempt=1, reason_code="delivery_unknown",
        prior_attempts=0, retry_budget=3, external_observed_state=None,
    )
    assert r["verdict"] == VERDICT_RECONCILE_PENDING
    assert r["retry_allowed"] is False
    assert r["reconciliation"]["reconciled"] is False


def test_build_receipt_delivery_unknown_unblocks_after_reconciliation():
    r = build_feedback_recovery_receipt(
        run_id="run1", task_id="T-2", attempt=1, reason_code="delivery_unknown",
        prior_attempts=0, retry_budget=3,
        external_observed_state={"intent_id": "i1", "succeeded": True},
        delivery_intent={"intent_id": "i1"},
    )
    assert r["reconciliation"]["reconciled"] is True
    assert r["retry_allowed"] is True


def test_build_receipt_repeated_fingerprint_escalates():
    base = {"iteration": 0, "action": "retry", "hypothesis": "h", "note": "", "ts": "2026-01-01T00:00:00Z"}
    rows = [dict(base, iteration=i, gate="fail", fingerprint="deadbeef0001") for i in range(1, 5)]
    r = build_feedback_recovery_receipt(
        run_id="run1", task_id="T-3", attempt=4, reason_code="ci_infra_failure",
        prior_attempts=3, retry_budget=5, journal_rows=rows,
    )
    assert r["verdict"] == VERDICT_ESCALATED
    assert r["retry_allowed"] is False
    assert r["next_action"] == "escalate_to_human"


def test_build_receipt_quarantines_on_exhausted_budget():
    r = build_feedback_recovery_receipt(
        run_id="run1", task_id="T-4", attempt=4, reason_code="ci_infra_failure",
        prior_attempts=3, retry_budget=3,
    )
    assert r["verdict"] == VERDICT_QUARANTINED
    assert r["quarantine"] is not None
    assert r["quarantine"]["blocks_drain"] is False


def test_build_receipt_code_change_invalidates_review_and_delivery():
    prior_receipts = [{"kind": "review", "id": "rv1"}, {"kind": "delivery", "id": "dv1"}]
    r = build_feedback_recovery_receipt(
        run_id="run1", task_id="T-5", attempt=1, reason_code="code_failure",
        prior_attempts=0, retry_budget=3, prior_receipts=prior_receipts,
    )
    invalidated_ids = {rec["id"] for rec in r["invalidated_receipts"]}
    assert invalidated_ids == {"rv1", "dv1"}


def test_build_receipt_post_complete_regression_reopens_graph():
    r = build_feedback_recovery_receipt(
        run_id="run1", task_id="T-6", attempt=1, reason_code="source_regression",
        prior_attempts=0, retry_budget=3, post_complete=True,
    )
    assert r["reopen_stage_graph"] is True
    assert r["target_stage"] == "planning"


def test_to_stage_receipt_projects_target_stage():
    r = build_feedback_recovery_receipt(
        run_id="run1", task_id="T-7", attempt=1, reason_code="test_failed",
        prior_attempts=0, retry_budget=3,
    )
    stage_receipt = to_stage_receipt(
        r, receipt_id="rec-1", agent_instance_id="inst-1", task_id="T-7",
        attempt_id="att-1", fence="fence-1",
    )
    assert stage_receipt["schema"] == "simplicio.stage-receipt/v1"
    assert stage_receipt["stage_id"] == "executing"
    assert stage_receipt["verdict"] == "pass"


def test_to_stage_receipt_passes_the_real_canonical_validator():
    # Regression for issue #458: to_stage_receipt() was missing ~15 fields
    # the canonical stage-receipt/v1 schema requires, so every real
    # coordinator-driven feedback_recovery_agent receipt was silently
    # rejected by stage_agents.validate_receipt() despite this module's own
    # shallow tests passing.
    from simplicio_loop import stage_agents as sa

    r = build_feedback_recovery_receipt(
        run_id="run1", task_id="T-7", attempt=1, reason_code="test_failed",
        prior_attempts=0, retry_budget=3,
    )
    context_hash, manifest_hash = "a" * 64, "b" * 64
    stage_receipt = to_stage_receipt(
        r, receipt_id="rec-full", agent_instance_id="inst-full", task_id="T-7",
        attempt_id="att-full", fence="fence-1",
        attempt_ordinal=1, context_hash=context_hash, manifest_hash=manifest_hash,
    )
    instance = {
        "run_id": "run1", "task_id": "T-7", "attempt_id": "att-full", "attempt_ordinal": 1,
        "fence": "fence-1", "plan_revision": 0, "agent_instance_id": "inst-full",
        "role_id": stage_receipt["role_id"], "stage_id": stage_receipt["stage_id"],
        "context_hash": context_hash, "manifest_hash": manifest_hash,
        "negotiated_capabilities": ["receipts"], "terminal_status": "completed",
    }
    ok, errors = sa.validate_receipt(stage_receipt, instance)
    assert ok, errors


def test_receipt_never_declares_completion():
    r = build_feedback_recovery_receipt(
        run_id="run1", task_id="T-8", attempt=1, reason_code="test_failed",
        prior_attempts=0, retry_budget=3,
    )
    assert r["complete"] is False


def test_cli_stage_receipt_subcommand_is_a_real_live_path(tmp_path, capsys):
    # Regression for issue #458 adversarial review: to_stage_receipt() was only
    # ever called from this test file, never from any production entrypoint.
    # scripts/feedback_recovery_agent.py's `stage-receipt` subcommand is that
    # entrypoint -- exercise it via its real main(), not just the library call.
    payload = dict(run_id="run1", task_id="T-7", attempt=1, reason_code="test_failed",
                   prior_attempts=0, retry_budget=3)
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(
        "scripts.feedback_recovery_agent_cli", os.path.join(repo_root, "scripts", "feedback_recovery_agent.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    exit_code = mod.main([
        "stage-receipt", "--input", str(input_path), "--receipt-id", "rec-cli",
        "--agent-instance-id", "inst-cli", "--task-id", "T-7", "--attempt-id", "att-cli",
        "--fence", "fence-1", "--context-hash", "a" * 64, "--manifest-hash", "b" * 64,
    ])
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert out["schema"] == "simplicio.stage-receipt/v1"
    assert out["role_id"] == "feedback_recovery_agent"
