"""Unit tests for the #426 `implementation_agent` concrete stage-agent role.

Covers the invariants from the issue: mutation-capability validity, path
allowlist fail-closed, base/plan/fence drift, self-reported-green rejection,
no-change proof, surface expansion, routing/driver receipt, retry budget,
forbidden receipt schemas, and the composed typed receipt/gate.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from simplicio_loop.implementation_agent import (
    IMPLEMENTATION_AGENT_ROLE_ID,
    IMPLEMENTATION_STAGE_RECEIPT_SCHEMA,
    VERDICT_BLOCKED,
    VERDICT_FAILED,
    VERDICT_PASS,
    DriftError,
    ForbiddenReceiptError,
    ImplementationAgentError,
    MutationCapabilityError,
    PathBoundaryError,
    assert_acs_unchanged,
    assert_mutation_capability,
    assert_no_drift,
    assert_path_allowlist_ok,
    assert_receipt_schema_allowed,
    build_assignment,
    build_implementation_stage_receipt,
    cancel,
    check_path_allowlist,
    classify_failure,
    content_hash,
    detect_drift,
    heartbeat,
    is_capability_valid,
    is_path_allowed,
    next_attempt,
    no_change_ok,
    reconcile_worktree,
    receipt_is_passed,
    requires_impact_reaudit,
    surface_expanded,
    all_tests_verified,
    to_stage_receipt,
    validate_no_change_proof,
    validate_test_run,
)


def _assignment(**overrides):
    base = dict(
        task_id="T-426", plan_revision=1, acs=["AC1", "AC2"],
        allowed_paths=["simplicio_loop/foo.py", "tests/"],
        expected_tests=["pytest tests/test_foo.py"],
        base_sha="base-sha-1", lease_id="lease-1", fence="fence-1",
    )
    base.update(overrides)
    return build_assignment(**base)


def _capability(*, ttl=60.0, revoked=False, token="tok-1"):
    return {"token": token, "expires_at": time.time() + ttl, "revoked": revoked,
            "lease_id": "lease-1", "fence": "fence-1"}


def _passing_test_run():
    return {"command": "pytest tests/test_foo.py", "exit_code": 0, "log_ref": "artifact://log1"}


# --------------------------------------------------------------------------- #
# Assignment schema
# --------------------------------------------------------------------------- #
def test_build_assignment_ok():
    a = _assignment()
    assert a["task_id"] == "T-426"
    assert a["acs"] == ["AC1", "AC2"]
    assert a["assignment_hash"]


def test_build_assignment_requires_acs():
    with pytest.raises(ImplementationAgentError):
        build_assignment(task_id="T1", plan_revision=1, acs=[], allowed_paths=["a.py"],
                          expected_tests=[], base_sha="s1", lease_id="l1", fence="f1")


def test_build_assignment_requires_allowed_paths():
    with pytest.raises(ImplementationAgentError):
        build_assignment(task_id="T1", plan_revision=1, acs=["AC1"], allowed_paths=[],
                          expected_tests=[], base_sha="s1", lease_id="l1", fence="f1")


def test_build_assignment_requires_lease_and_fence():
    with pytest.raises(ImplementationAgentError):
        build_assignment(task_id="T1", plan_revision=1, acs=["AC1"], allowed_paths=["a.py"],
                          expected_tests=[], base_sha="s1", lease_id="", fence="f1")


# --------------------------------------------------------------------------- #
# Mutation capability -- valid / invalid / stale (invariant 2)
# --------------------------------------------------------------------------- #
def test_capability_valid():
    assert is_capability_valid(_capability())


def test_capability_missing_is_invalid():
    assert not is_capability_valid(None)
    assert not is_capability_valid({})


def test_capability_revoked_is_invalid():
    assert not is_capability_valid(_capability(revoked=True))


def test_capability_stale_is_invalid():
    cap = _capability(ttl=-5.0)
    assert not is_capability_valid(cap)


def test_assert_mutation_capability_raises_on_invalid():
    with pytest.raises(MutationCapabilityError):
        assert_mutation_capability(None)
    with pytest.raises(MutationCapabilityError):
        assert_mutation_capability(_capability(revoked=True))


def test_assert_mutation_capability_ok():
    assert_mutation_capability(_capability())  # does not raise


# --------------------------------------------------------------------------- #
# Path allowlist (invariant 3)
# --------------------------------------------------------------------------- #
def test_is_path_allowed_prefix_and_exact():
    allowed = ["simplicio_loop/foo.py", "tests/"]
    assert is_path_allowed("simplicio_loop/foo.py", allowed_paths=allowed)
    assert is_path_allowed("tests/test_x.py", allowed_paths=allowed)
    assert not is_path_allowed("simplicio_loop/bar.py", allowed_paths=allowed)


def test_check_path_allowlist_reports_violations():
    allowed = ["simplicio_loop/foo.py"]
    violations = check_path_allowlist(["simplicio_loop/foo.py", "scripts/evil.py"], allowed_paths=allowed)
    assert violations == ["scripts/evil.py"]


def test_assert_path_allowlist_ok_raises_and_invalidates():
    allowed = ["simplicio_loop/foo.py"]
    with pytest.raises(PathBoundaryError):
        assert_path_allowlist_ok(["scripts/evil.py"], allowed_paths=allowed)


def test_assert_path_allowlist_ok_passes():
    allowed = ["simplicio_loop/foo.py"]
    assert_path_allowlist_ok(["simplicio_loop/foo.py"], allowed_paths=allowed)  # no raise


# --------------------------------------------------------------------------- #
# Base/plan/fence drift (invariant 4)
# --------------------------------------------------------------------------- #
def test_detect_drift_none():
    a = _assignment()
    reasons = detect_drift(a, current_base_sha="base-sha-1", current_plan_revision=1, current_fence="fence-1")
    assert reasons == []


def test_detect_drift_base_sha():
    a = _assignment()
    reasons = detect_drift(a, current_base_sha="other-sha", current_plan_revision=1, current_fence="fence-1")
    assert any("base_sha drift" in r for r in reasons)


def test_detect_drift_plan_revision():
    a = _assignment()
    reasons = detect_drift(a, current_base_sha="base-sha-1", current_plan_revision=2, current_fence="fence-1")
    assert any("plan_revision drift" in r for r in reasons)


def test_detect_drift_fence():
    a = _assignment()
    reasons = detect_drift(a, current_base_sha="base-sha-1", current_plan_revision=1, current_fence="other-fence")
    assert any("fence drift" in r for r in reasons)


def test_assert_no_drift_raises():
    a = _assignment()
    with pytest.raises(DriftError):
        assert_no_drift(a, current_base_sha="stale", current_plan_revision=1, current_fence="fence-1")


def test_assert_no_drift_ok():
    a = _assignment()
    assert_no_drift(a, current_base_sha="base-sha-1", current_plan_revision=1, current_fence="fence-1")


# --------------------------------------------------------------------------- #
# Self-reported green test with no log/exit code rejected (invariant 5)
# --------------------------------------------------------------------------- #
def test_validate_test_run_missing_log_rejected():
    errors = validate_test_run({"command": "pytest", "exit_code": 0})
    assert any("log_ref and log_hash" in e for e in errors)


def test_validate_test_run_missing_exit_code_rejected():
    errors = validate_test_run({"command": "pytest", "log_ref": "artifact://1"})
    assert any("exit_code" in e for e in errors)


def test_validate_test_run_ok():
    assert validate_test_run(_passing_test_run()) == []


def test_all_tests_verified_passing():
    result = all_tests_verified([_passing_test_run()])
    assert result["ok"] is True
    assert result["passing"] is True


def test_all_tests_verified_unverifiable_never_passing():
    result = all_tests_verified([{"command": "pytest", "exit_code": 0}])
    assert result["ok"] is False
    assert result["passing"] is False


def test_all_tests_verified_failing_exit_code():
    run = dict(_passing_test_run(), exit_code=1)
    result = all_tests_verified([run])
    assert result["ok"] is True
    assert result["passing"] is False


# --------------------------------------------------------------------------- #
# No-change proof (invariant 8)
# --------------------------------------------------------------------------- #
def test_validate_no_change_proof_missing():
    errors = validate_no_change_proof(None)
    assert errors


def test_validate_no_change_proof_bare_assertion_rejected():
    errors = validate_no_change_proof({"ac_satisfied_because": {"AC1": "trust me"}})
    assert any("evidence_refs" in e for e in errors)


def test_validate_no_change_proof_with_evidence_ok():
    proof = {"ac_satisfied_because": {"AC1": "already implemented in prior PR"},
              "evidence_refs": ["artifact://web-verify-1"]}
    assert validate_no_change_proof(proof) == []


def test_no_change_ok_requires_all_acs_covered():
    proof = {"ac_satisfied_because": {"AC1": "already ok"}, "evidence_refs": ["ref1"]}
    assert not no_change_ok(acs=["AC1", "AC2"], proof=proof)
    proof2 = {"ac_satisfied_because": {"AC1": "ok", "AC2": "ok"}, "evidence_refs": ["ref1"]}
    assert no_change_ok(acs=["AC1", "AC2"], proof=proof2)


# --------------------------------------------------------------------------- #
# Surface expansion / impact reaudit (invariant 9)
# --------------------------------------------------------------------------- #
def test_surface_expanded_none():
    assert surface_expanded(allowed_paths=["a/"], changed_paths=["a/x.py"]) == []


def test_surface_expanded_detects_extra():
    result = surface_expanded(allowed_paths=["a/"], changed_paths=["a/x.py", "b/y.py"])
    assert result == ["b/y.py"]


def test_requires_impact_reaudit_on_expansion():
    assert requires_impact_reaudit(allowed_paths=["a/"], changed_paths=["a/x.py", "b/y.py"])


def test_requires_impact_reaudit_on_dependency_delta_issues():
    assert requires_impact_reaudit(
        allowed_paths=["a/"], changed_paths=["a/x.py"],
        dependency_delta={"issues": [{"severity": "high"}]},
    )


def test_requires_impact_reaudit_false_when_clean():
    assert not requires_impact_reaudit(allowed_paths=["a/"], changed_paths=["a/x.py"])


# --------------------------------------------------------------------------- #
# Failure classification (plan step 9)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("code,expected", [
    ("code", "code"), ("test", "test"), ("toolchain", "toolchain"),
    ("dependency", "dependency"), ("capability", "capability"),
    ("lease", "lease"), ("scope", "scope"),
    ("timeout", "toolchain"), ("not_passed", "test"), ("stale_lease", "lease"),
    ("revoked", "capability"), ("out_of_scope", "scope"), ("something_weird", "code"),
])
def test_classify_failure(code, expected):
    assert classify_failure(reason_code=code) == expected


# --------------------------------------------------------------------------- #
# Retry budget + reconciliation (invariant 7, plan step 10)
# --------------------------------------------------------------------------- #
def test_next_attempt_allowed_within_budget():
    a = _assignment()
    result = next_attempt(assignment=a, prior_attempts=1, reason_code="test")
    assert result["retry_allowed"] is True
    assert result["attempt_number"] == 2


def test_next_attempt_exhausted_budget():
    a = _assignment(retry_budget=1)
    result = next_attempt(assignment=a, prior_attempts=1, reason_code="test")
    assert result["retry_allowed"] is False
    assert result["attempt_number"] == 1


def test_reconcile_worktree_records_prior_state():
    result = reconcile_worktree(
        prior_worktree={"worktree_id": "wt-1", "attempt_id": "att-1", "head_sha": "h1"},
        new_attempt_id="att-2",
    )
    assert result["prior_worktree_id"] == "wt-1"
    assert result["new_attempt_id"] == "att-2"
    assert result["reconciled"] is True


def test_heartbeat_alive_and_dead():
    assert heartbeat(capability=_capability())["alive"] is True
    assert heartbeat(capability=None)["alive"] is False


def test_cancel_returns_reason():
    result = cancel(reason="user_requested")
    assert result["cancelled"] is True
    assert result["reason"] == "user_requested"


# --------------------------------------------------------------------------- #
# Boundary: never write reviewer/safety/delivery receipts (invariant 6); never
# alter plan/ACs (invariant 1)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("schema", [
    "simplicio.review-receipt/v1", "simplicio.safety-receipt/v1",
    "simplicio.delivery-receipt/v1", "simplicio.completion-receipt/v1",
])
def test_assert_receipt_schema_allowed_rejects_forbidden(schema):
    with pytest.raises(ForbiddenReceiptError):
        assert_receipt_schema_allowed(schema)


def test_assert_receipt_schema_allowed_ok_for_own_schema():
    assert_receipt_schema_allowed(IMPLEMENTATION_STAGE_RECEIPT_SCHEMA)  # no raise


def test_assert_acs_unchanged_rejects_new_ac():
    with pytest.raises(ImplementationAgentError):
        assert_acs_unchanged(assigned_acs=["AC1"], reported_acs=["AC1", "AC2"])


def test_assert_acs_unchanged_ok_subset():
    assert_acs_unchanged(assigned_acs=["AC1", "AC2"], reported_acs=["AC1"])  # no raise


# --------------------------------------------------------------------------- #
# The composed #426 receipt
# --------------------------------------------------------------------------- #
def _receipt_kwargs(**overrides):
    a = _assignment()
    base = dict(
        run_id="run-1", attempt=1, assignment=a,
        current_base_sha="base-sha-1", current_plan_revision=1, current_fence="fence-1",
        capability=_capability(), touched_paths=["simplicio_loop/foo.py"],
        changed_paths=["simplicio_loop/foo.py"],
        ac_coverage={"AC1": "satisfied", "AC2": "satisfied"},
        test_runs=[_passing_test_run()], diff_ref="artifact://diff-1", head_sha="head-sha-1",
        operator_receipt={"applied": True, "tool": "simplicio-dev-cli"},
    )
    base.update(overrides)
    return base


def test_build_receipt_passes_when_all_invariants_hold():
    receipt = build_implementation_stage_receipt(**_receipt_kwargs())
    assert receipt["verdict"] == VERDICT_PASS
    assert receipt_is_passed(receipt)
    assert receipt["role_id"] == IMPLEMENTATION_AGENT_ROLE_ID
    assert receipt["schema"] == IMPLEMENTATION_STAGE_RECEIPT_SCHEMA
    assert receipt["complete"] is False
    assert receipt["next_stage_hint"] == "safety_gate"
    assert receipt["receipt_hash"]


def test_build_receipt_wires_forbidden_schema_guard(monkeypatch):
    # Invariant 6 exercised through the real entrypoint, not just the
    # isolated assert_receipt_schema_allowed() unit tests above: if this
    # role's own receipt schema ever collided with a forbidden
    # reviewer/safety/delivery schema, the receipt builder must refuse to
    # build it rather than silently succeed.
    import simplicio_loop.implementation_agent as ia_mod

    monkeypatch.setattr(
        ia_mod, "FORBIDDEN_RECEIPT_SCHEMAS",
        frozenset(ia_mod.FORBIDDEN_RECEIPT_SCHEMAS | {IMPLEMENTATION_STAGE_RECEIPT_SCHEMA}),
    )
    with pytest.raises(ForbiddenReceiptError):
        build_implementation_stage_receipt(**_receipt_kwargs())


def test_build_receipt_raises_on_invalid_capability():
    with pytest.raises(MutationCapabilityError):
        build_implementation_stage_receipt(**_receipt_kwargs(capability=None))


def test_build_receipt_raises_on_out_of_scope_path():
    with pytest.raises(PathBoundaryError):
        build_implementation_stage_receipt(**_receipt_kwargs(touched_paths=["scripts/evil.py"]))


def test_build_receipt_raises_on_drift():
    with pytest.raises(DriftError):
        build_implementation_stage_receipt(**_receipt_kwargs(current_base_sha="stale-sha"))


def test_build_receipt_blocked_on_unverifiable_test_run():
    kwargs = _receipt_kwargs(test_runs=[{"command": "pytest", "exit_code": 0}])
    receipt = build_implementation_stage_receipt(**kwargs)
    assert receipt["verdict"] == VERDICT_BLOCKED
    assert "test_evidence_verifiable" in receipt["failing_checks"]


def test_build_receipt_blocked_on_pending_ac():
    kwargs = _receipt_kwargs(ac_coverage={"AC1": "satisfied", "AC2": "pending"})
    receipt = build_implementation_stage_receipt(**kwargs)
    assert receipt["verdict"] == VERDICT_BLOCKED
    assert receipt["acs_pending"] == ["AC2"]


def test_build_receipt_blocked_on_surface_expansion():
    kwargs = _receipt_kwargs(changed_paths=["simplicio_loop/foo.py", "scripts/unexpected.py"])
    receipt = build_implementation_stage_receipt(**kwargs)
    assert receipt["verdict"] == VERDICT_BLOCKED
    assert receipt["requires_impact_reaudit"] is True
    assert receipt["surface_expansion_paths"] == ["scripts/unexpected.py"]


def test_build_receipt_failed_when_failure_reason_code_present():
    kwargs = _receipt_kwargs(failure_reason_code="timeout")
    receipt = build_implementation_stage_receipt(**kwargs)
    assert receipt["verdict"] == VERDICT_FAILED
    assert receipt["failure_class"] == "toolchain"


def test_build_receipt_no_changes_needed_requires_proof():
    kwargs = _receipt_kwargs(no_changes_needed=True, no_change_proof=None,
                              ac_coverage={"AC1": "pending", "AC2": "pending"})
    receipt = build_implementation_stage_receipt(**kwargs)
    assert receipt["verdict"] == VERDICT_BLOCKED
    assert receipt["no_change_proof_errors"]


def test_build_receipt_no_changes_needed_passes_with_proof():
    proof = {
        "ac_satisfied_because": {"AC1": "already satisfied", "AC2": "already satisfied"},
        "evidence_refs": ["artifact://web-verify-1"],
    }
    kwargs = _receipt_kwargs(no_changes_needed=True, no_change_proof=proof,
                              ac_coverage={"AC1": "pending", "AC2": "pending"},
                              touched_paths=[], changed_paths=[])
    receipt = build_implementation_stage_receipt(**kwargs)
    assert receipt["verdict"] == VERDICT_PASS
    assert receipt["acs_pending"] == []


def test_build_receipt_never_alters_plan_acs():
    with pytest.raises(ImplementationAgentError):
        build_implementation_stage_receipt(**_receipt_kwargs(
            ac_coverage={"AC1": "satisfied", "AC2": "satisfied", "AC3": "satisfied"},
        ))


def test_build_receipt_never_promotes_delivery_or_completion():
    receipt = build_implementation_stage_receipt(**_receipt_kwargs())
    assert receipt["complete"] is False
    assert receipt["next_stage_hint"] not in ("delivered", "complete", "completion_auditor", "delivery_agent")


def test_content_hash_deterministic():
    a = {"x": 1, "y": [1, 2]}
    assert content_hash(a) == content_hash({"y": [1, 2], "x": 1})


# --------------------------------------------------------------------------- #
# Stage-agent binding
# --------------------------------------------------------------------------- #
def test_to_stage_receipt_projection():
    receipt = build_implementation_stage_receipt(**_receipt_kwargs())
    stage_receipt = to_stage_receipt(
        receipt, receipt_id="rec-1", agent_instance_id="inst-1",
        task_id="T-426", attempt_id="att-1", fence="fence-1",
    )
    assert stage_receipt["schema"] == "simplicio.stage-receipt/v1"
    assert stage_receipt["role_id"] == IMPLEMENTATION_AGENT_ROLE_ID
    assert stage_receipt["stage_id"] == "executing"
    assert stage_receipt["verdict"] == "pass"


def test_to_stage_receipt_passes_the_real_canonical_validator():
    # Regression for issue #458: earlier versions of to_stage_receipt() were
    # missing ~15 fields the canonical stage-receipt/v1 schema requires
    # (attempt_ordinal, observed_at, ttl_seconds, integrity_hash, ...), so
    # every real coordinator-driven implementation_agent receipt was silently
    # rejected by stage_agents.validate_receipt() despite this module's own
    # shallow tests passing.
    from simplicio_loop import stage_agents as sa

    receipt = build_implementation_stage_receipt(**_receipt_kwargs())
    context_hash, manifest_hash = "a" * 64, "b" * 64
    stage_receipt = to_stage_receipt(
        receipt, receipt_id="rec-full", agent_instance_id="inst-full",
        task_id="T-426", attempt_id="att-full", fence="fence-1",
        attempt_ordinal=1, context_hash=context_hash, manifest_hash=manifest_hash,
    )
    instance = {
        "run_id": stage_receipt["run_id"], "task_id": "T-426", "attempt_id": "att-full",
        "attempt_ordinal": 1, "fence": "fence-1", "plan_revision": stage_receipt["plan_revision"],
        "agent_instance_id": "inst-full", "role_id": IMPLEMENTATION_AGENT_ROLE_ID,
        "stage_id": "executing", "context_hash": context_hash, "manifest_hash": manifest_hash,
        "negotiated_capabilities": ["receipts"], "terminal_status": "completed",
    }
    ok, errors = sa.validate_receipt(stage_receipt, instance)
    assert ok, errors


def test_to_stage_receipt_blocked_maps_to_blocked():
    kwargs = _receipt_kwargs(ac_coverage={"AC1": "satisfied", "AC2": "pending"})
    receipt = build_implementation_stage_receipt(**kwargs)
    stage_receipt = to_stage_receipt(
        receipt, receipt_id="rec-2", agent_instance_id="inst-2",
        task_id="T-426", attempt_id="att-2", fence="fence-1",
    )
    assert stage_receipt["verdict"] == "blocked"


def test_stage_agents_graph_already_registers_role():
    from simplicio_loop import stage_agents as sa

    graph = sa.load_graph()
    role_ids = {r["role_id"] for r in graph["roles"]}
    assert IMPLEMENTATION_AGENT_ROLE_ID in role_ids
    stage_ids = {(s["stage_id"], s["role_id"]) for s in graph["stages"]}
    assert ("executing", IMPLEMENTATION_AGENT_ROLE_ID) in stage_ids


def test_cli_stage_receipt_subcommand_is_a_real_live_path(tmp_path, capsys):
    # Regression for issue #458 adversarial review: to_stage_receipt() was only
    # ever called from this test file, never from any production entrypoint.
    # scripts/implementation_agent.py's `stage-receipt` subcommand is that
    # entrypoint -- exercise it via its real main(), not just the library call.
    import importlib.util

    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(_receipt_kwargs()), encoding="utf-8")

    repo_root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "scripts.implementation_agent_cli", repo_root / "scripts" / "implementation_agent.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    exit_code = mod.main([
        "stage-receipt", "--input", str(input_path), "--receipt-id", "rec-cli",
        "--agent-instance-id", "inst-cli", "--task-id", "T-426", "--attempt-id", "att-cli",
        "--fence", "fence-1", "--context-hash", "a" * 64, "--manifest-hash", "b" * 64,
    ])
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert out["schema"] == "simplicio.stage-receipt/v1"
    assert out["receipt_id"] == "rec-cli"
    assert out["verdict"] == "pass"
