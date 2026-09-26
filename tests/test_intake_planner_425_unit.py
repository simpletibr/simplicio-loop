"""Unit tests for the #425 `intake_planner` concrete stage-agent role.

Builds on the #284 fixtures (task contract / plan / intake / matrix) already
used by `tests/test_intake_impact_matrix_replan_284_unit.py`, and covers the
#425-specific checklist: the typed `intake-planner-receipt`, boundary
enforcement (no product-code mutation / no commit-PR-merge), the risk
register gate, the dependency DAG explicitness, the impact-gap threshold, and
the single-clarifying-question path.
"""
from __future__ import annotations

import importlib.util
import json
import os

import pytest

from simplicio_loop.intake_contract import build_task_intake
from simplicio_loop.traceability_matrix import build_matrix
from simplicio_loop.intake_planner import (
    INTAKE_PLANNER_RECEIPT_SCHEMA,
    INTAKE_PLANNER_ROLE_ID,
    VERDICT_BLOCKED,
    VERDICT_PASSED,
    IntakePlannerBoundaryError,
    assert_boundary_ok,
    build_dependency_dag,
    build_intake_planner_receipt,
    build_risk_register,
    impact_gap_ok,
    is_path_in_boundary,
    receipt_is_passed,
    to_stage_receipt,
)

CONTRACT = {
    "schema": "simplicio.task-contract-collection/v1",
    "collection_hash": "c1",
    "tasks": [{
        "id": "T1",
        "scenarios": [
            {"id": "SCN1", "title": "Does X", "given": ["something"], "when": ["event"],
             "then": ["result"], "rule_refs": ["RN1"]},
        ],
        "rules": [{"id": "RN1", "text": "rule", "scenario_refs": ["SCN1"]}],
    }],
}

PLAN_COVERED = {
    "schema": "simplicio.plan/v1", "task_contract_hash": "c1",
    "mapper_pack_hash": "mp1", "context_pack_hash": "mp1",
    "repo_state": {"head": "h1", "tree_hash": "t1"},
    "freshness": {"verified": True, "current_state": {"head": "h1", "tree_hash": "t1"}},
    "steps": [{
        "id": "T1", "candidate_targets": ["a.py"], "to_create": ["a.py"], "rule_ids": ["RN1"],
        "steps": [{
            "scenario_id": "SCN1", "rule_ids": ["RN1"],
            "plan": {"read_paths": ["a.py"], "change_paths": ["a.py"],
                     "test_commands": ["pytest tests/test_a.py"]},
        }],
    }],
}

SOURCE = {
    "schema": "simplicio.source-snapshot/v1",
    "source": {"provider": "github", "repo": "acme/repo", "item_id": "425",
               "revision": "r1", "snapshot_hash": "hash-a", "observed_at": "2026-01-01T00:00:00Z"},
}

PLAN_VALIDATION_OK = {"valid": True, "errors": [], "warnings": [], "checked_tasks": 1}

RISK_OK = [{"id": "R1", "text": "risk", "mitigation": "mitigate it"}]
DEPS_OK = [{"id": "D1", "depends_on": [], "state": "resolved"}]


def _intake(delivery_target="implemented"):
    return build_task_intake(run_id="r1", attempt=1, contract=CONTRACT, plan_hash="p1",
                              source_snapshot=SOURCE, delivery_target=delivery_target)


def _matrix():
    return build_matrix(CONTRACT, PLAN_COVERED)


def _base_kwargs(**overrides):
    kwargs = dict(
        run_id="r1", attempt=1, contract=CONTRACT, plan=PLAN_COVERED,
        plan_validation=PLAN_VALIDATION_OK, intake=_intake(), traceability_matrix=_matrix(),
        source_snapshot=SOURCE, risks=RISK_OK, dependencies=DEPS_OK,
        conventions_consulted=True, precedents_consulted=True,
        touched_paths=[],  # explicit "boundary was checked, nothing touched"
    )
    kwargs.update(overrides)
    return kwargs


# --------------------------------------------------------------------------- #
# Happy path: PASSED only when every gate condition holds
# --------------------------------------------------------------------------- #
def test_receipt_passed_when_every_gate_condition_holds():
    receipt = build_intake_planner_receipt(**_base_kwargs())
    assert receipt["schema"] == INTAKE_PLANNER_RECEIPT_SCHEMA
    assert receipt["role_id"] == INTAKE_PLANNER_ROLE_ID
    assert receipt["verdict"] == VERDICT_PASSED
    assert receipt["failing_checks"] == []
    assert receipt_is_passed(receipt)
    assert all(receipt["checklist"].values())
    assert receipt["receipt_hash"]


def test_receipt_blocked_when_source_snapshot_missing():
    receipt = build_intake_planner_receipt(**_base_kwargs(source_snapshot=None))
    assert receipt["verdict"] == VERDICT_BLOCKED
    assert "source_read_and_revision_frozen" in receipt["failing_checks"]


def test_receipt_blocked_when_ac_step_evidence_gap():
    gap_plan = json.loads(json.dumps(PLAN_COVERED))
    gap_plan["steps"][0]["steps"][0]["plan"]["test_commands"] = []
    matrix = build_matrix(CONTRACT, gap_plan)
    receipt = build_intake_planner_receipt(**_base_kwargs(plan=gap_plan, traceability_matrix=matrix))
    assert receipt["verdict"] == VERDICT_BLOCKED
    assert "every_ac_has_step_and_proof" in receipt["failing_checks"]
    assert "every_step_maps_to_ac" in receipt["failing_checks"]


def test_receipt_blocked_when_delivery_target_missing():
    intake = _intake()
    intake["understanding"]["delivery_target"] = ""
    receipt = build_intake_planner_receipt(**_base_kwargs(intake=intake))
    assert receipt["verdict"] == VERDICT_BLOCKED
    assert "delivery_target_defined" in receipt["failing_checks"]


def test_receipt_blocked_when_risk_has_no_mitigation_or_blocker():
    risks = [{"id": "R1", "text": "unmitigated risk"}]
    receipt = build_intake_planner_receipt(**_base_kwargs(risks=risks))
    assert receipt["verdict"] == VERDICT_BLOCKED
    assert "risks_mitigated_or_blocked" in receipt["failing_checks"]
    assert "risk_missing_mitigation_or_blocker:R1" in receipt["risk_register"]["errors"]


def test_risk_with_is_blocker_true_and_no_mitigation_still_passes_gate():
    result = build_risk_register([{"id": "R1", "text": "known blocker", "is_blocker": True}])
    assert result["ok"]
    assert result["errors"] == []


def test_receipt_blocked_when_conventions_not_consulted():
    receipt = build_intake_planner_receipt(**_base_kwargs(conventions_consulted=False))
    assert receipt["verdict"] == VERDICT_BLOCKED
    assert "architecture_conventions_consulted" in receipt["failing_checks"]


def test_receipt_blocked_when_impact_gap_above_threshold():
    impact_map = {"issues": [{"severity": "high", "text": "cross-module blast radius"}]}
    receipt = build_intake_planner_receipt(**_base_kwargs(impact_map=impact_map))
    assert receipt["verdict"] == VERDICT_BLOCKED
    assert "impact_audit_below_threshold" in receipt["failing_checks"]


def test_impact_gap_ok_ignores_low_and_medium_severities_by_default():
    impact_map = {"issues": [{"severity": "medium"}, {"severity": "low"}]}
    assert impact_gap_ok(impact_map) is True


def test_impact_gap_ok_true_when_no_impact_map_supplied():
    assert impact_gap_ok(None) is True


# --------------------------------------------------------------------------- #
# Single clarifying question -- BLOCKED(needs_clarification), not a silent guess
# --------------------------------------------------------------------------- #
def test_needs_clarification_blocks_even_an_otherwise_perfect_plan():
    receipt = build_intake_planner_receipt(
        **_base_kwargs(needs_clarification=True, clarification_question="Which delivery target applies?")
    )
    assert receipt["verdict"] == VERDICT_BLOCKED
    assert receipt["needs_clarification"] is True
    assert receipt["clarification_question"] == "Which delivery target applies?"
    assert "no_clarification_pending" in receipt["failing_checks"]
    # the underlying planning_gate receipt is also AWAITING_DECISION, never COMPLETE
    assert receipt["planning_receipt"]["verdict"] == "AWAITING_DECISION"
    assert receipt["planning_receipt"]["ready_for_mutation"] is False


# --------------------------------------------------------------------------- #
# Dependency DAG explicitness
# --------------------------------------------------------------------------- #
def test_dependency_dag_marks_unresolved_dependency_as_blocked_explicitly():
    deps = [
        {"id": "D1", "depends_on": [], "state": "open"},
        {"id": "D2", "depends_on": ["D1"], "state": "open"},
    ]
    dag = build_dependency_dag(deps)
    assert "D2" in dag["blocked_ids"]
    assert dag["has_blocked"] is True
    assert dag["dag_hash"]


def test_dependency_dag_all_resolved_has_no_blocked_ids():
    deps = [{"id": "D1", "depends_on": [], "state": "resolved"}]
    dag = build_dependency_dag(deps)
    assert dag["blocked_ids"] == []
    assert dag["has_blocked"] is False


# --------------------------------------------------------------------------- #
# Boundary enforcement -- "Não pode alterar código do produto / commit/PR/merge"
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", [
    ".simplicio/orchestrator/loop/PROGRESS.md",
    ".simplicio/context.json",
    "task-intake.json",
    "planning-receipt.json",
    "ac-matrix.json",
    "impact-map.json",
])
def test_allowlisted_artifact_paths_are_in_boundary(path):
    assert is_path_in_boundary(path) is True


@pytest.mark.parametrize("path", [
    "simplicio_loop/runner.py",
    "src/app/main.py",
    "README.md",
    ".git/refs/heads/main",
])
def test_product_code_paths_are_out_of_boundary(path):
    assert is_path_in_boundary(path) is False


def test_assert_boundary_ok_raises_on_product_code_path():
    with pytest.raises(IntakePlannerBoundaryError):
        assert_boundary_ok(["simplicio_loop/runner.py"])


@pytest.mark.parametrize("verb", ["commit", "pr", "push", "merge"])
def test_assert_boundary_ok_rejects_commit_pr_merge_verbs(verb):
    with pytest.raises(IntakePlannerBoundaryError):
        assert_boundary_ok([verb])


def test_assert_boundary_ok_allows_only_allowlisted_paths():
    assert_boundary_ok(["task-intake.json", "planning-receipt.json"])  # no raise


def test_build_intake_planner_receipt_raises_when_touched_paths_out_of_boundary():
    with pytest.raises(IntakePlannerBoundaryError):
        build_intake_planner_receipt(**_base_kwargs(touched_paths=["simplicio_loop/runner.py"]))


def test_build_intake_planner_receipt_ok_when_touched_paths_in_boundary():
    receipt = build_intake_planner_receipt(**_base_kwargs(touched_paths=["task-intake.json"]))
    assert receipt["verdict"] == VERDICT_PASSED


# --------------------------------------------------------------------------- #
# Stage-agent binding: projects into the portable StageReceipt shape
# --------------------------------------------------------------------------- #
def test_to_stage_receipt_projects_passed_verdict_as_pass():
    receipt = build_intake_planner_receipt(**_base_kwargs())
    stage_receipt = to_stage_receipt(
        receipt, receipt_id="rec-1", agent_instance_id="inst-1",
        task_id="task-1", attempt_id="att-1", fence="fence-1",
    )
    assert stage_receipt["schema"] == "simplicio.stage-receipt/v1"
    assert stage_receipt["role_id"] == INTAKE_PLANNER_ROLE_ID
    assert stage_receipt["stage_id"] == "intake"
    assert stage_receipt["verdict"] == "pass"
    assert stage_receipt["output_hash"] == receipt["receipt_hash"]


def test_to_stage_receipt_passes_the_real_canonical_validator():
    # Regression for issue #458: to_stage_receipt() was missing ~15 fields
    # the canonical stage-receipt/v1 schema requires, so every real
    # coordinator-driven intake_planner receipt was silently rejected by
    # stage_agents.validate_receipt() despite this module's own shallow
    # tests passing.
    from simplicio_loop import stage_agents as sa

    receipt = build_intake_planner_receipt(**_base_kwargs())
    context_hash, manifest_hash = "a" * 64, "b" * 64
    stage_receipt = to_stage_receipt(
        receipt, receipt_id="rec-full", agent_instance_id="inst-full",
        task_id="task-1", attempt_id="att-full", fence="fence-1",
        attempt_ordinal=1, context_hash=context_hash, manifest_hash=manifest_hash,
    )
    instance = {
        "run_id": stage_receipt["run_id"], "task_id": "task-1", "attempt_id": "att-full",
        "attempt_ordinal": 1, "fence": "fence-1", "plan_revision": stage_receipt["plan_revision"],
        "agent_instance_id": "inst-full", "role_id": INTAKE_PLANNER_ROLE_ID, "stage_id": "intake",
        "context_hash": context_hash, "manifest_hash": manifest_hash,
        "negotiated_capabilities": ["receipts"], "terminal_status": "completed",
    }
    ok, errors = sa.validate_receipt(stage_receipt, instance)
    assert ok, errors


def test_to_stage_receipt_projects_blocked_verdict():
    receipt = build_intake_planner_receipt(**_base_kwargs(source_snapshot=None))
    stage_receipt = to_stage_receipt(
        receipt, receipt_id="rec-2", agent_instance_id="inst-2",
        task_id="task-1", attempt_id="att-1", fence="fence-1",
    )
    assert stage_receipt["verdict"] == "blocked"


# --------------------------------------------------------------------------- #
# Regression: gate must not vacuously pass when a check never actually ran
# (the #440 adversarial-review findings).
# --------------------------------------------------------------------------- #
def test_omitted_touched_paths_blocks_the_receipt_even_if_everything_else_is_fine():
    kwargs = _base_kwargs()
    del kwargs["touched_paths"]  # never explicitly asserted the boundary was checked
    receipt = build_intake_planner_receipt(**kwargs)
    assert receipt["verdict"] == VERDICT_BLOCKED
    assert "no_mutation_before_mutation_capability" in receipt["failing_checks"]
    assert receipt["boundary_checked"] is False
    assert receipt["touched_paths"] is None


def test_empty_touched_paths_list_passes_the_boundary_check():
    receipt = build_intake_planner_receipt(**_base_kwargs(touched_paths=[]))
    assert receipt["boundary_checked"] is True
    assert "no_mutation_before_mutation_capability" not in receipt["failing_checks"]


def test_blocked_dependency_gates_the_receipt_for_real():
    deps = [
        {"id": "D1", "depends_on": [], "state": "open"},
        {"id": "D2", "depends_on": ["D1"], "state": "open"},
    ]
    receipt = build_intake_planner_receipt(**_base_kwargs(dependencies=deps))
    assert receipt["verdict"] == VERDICT_BLOCKED
    assert "blocked_dependencies_explicit" in receipt["failing_checks"]
    assert receipt["dependency_dag"]["has_blocked"] is True


def test_no_dependencies_supplied_does_not_falsely_block_on_blocked_dependencies():
    receipt = build_intake_planner_receipt(**_base_kwargs(dependencies=None))
    assert "blocked_dependencies_explicit" not in receipt["failing_checks"]


def test_omitted_risks_without_no_risks_identified_flag_blocks_the_receipt():
    receipt = build_intake_planner_receipt(**_base_kwargs(risks=None))
    assert receipt["verdict"] == VERDICT_BLOCKED
    assert "risks_mitigated_or_blocked" in receipt["failing_checks"]
    assert "risk_assessment_missing" in receipt["risk_register"]["errors"]


def test_empty_risks_with_explicit_no_risks_identified_passes_the_gate():
    receipt = build_intake_planner_receipt(
        **_base_kwargs(risks=[], no_risks_identified=True)
    )
    assert "risks_mitigated_or_blocked" not in receipt["failing_checks"]
    assert receipt["risk_register"]["no_risks_identified"] is True


def test_build_risk_register_empty_without_flag_is_not_ok():
    result = build_risk_register(None)
    assert result["ok"] is False
    assert "risk_assessment_missing" in result["errors"]


def test_build_risk_register_empty_with_explicit_flag_is_ok():
    result = build_risk_register([], no_risks_identified=True)
    assert result["ok"] is True
    assert result["no_risks_identified"] is True


# --------------------------------------------------------------------------- #
# The intake_planner role is registered in the manifesto with a boundary
# (regression guard against the manifesto drifting away from this module).
# --------------------------------------------------------------------------- #
def test_manifesto_registers_intake_planner_role_and_intake_stage():
    from simplicio_loop import stage_agents as sa
    graph = sa.load_graph()
    roles = {r["role_id"]: r for r in graph["roles"]}
    stages = {s["stage_id"]: s for s in graph["stages"]}
    assert INTAKE_PLANNER_ROLE_ID in roles
    assert stages["intake"]["role_id"] == INTAKE_PLANNER_ROLE_ID


def test_cli_stage_receipt_subcommand_is_a_real_live_path(tmp_path, capsys):
    # Regression for issue #458 adversarial review: to_stage_receipt() was only
    # ever called from this test file, never from any production entrypoint.
    # scripts/intake_planner.py's `stage-receipt` subcommand is that
    # entrypoint -- exercise it via its real main(), not just the library call.
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(_base_kwargs()), encoding="utf-8")

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(
        "scripts.intake_planner_cli", os.path.join(repo_root, "scripts", "intake_planner.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    exit_code = mod.main([
        "stage-receipt", "--input", str(input_path), "--receipt-id", "rec-cli",
        "--agent-instance-id", "inst-cli", "--task-id", "T-1", "--attempt-id", "att-cli",
        "--fence", "fence-1", "--context-hash", "a" * 64, "--manifest-hash", "b" * 64,
    ])
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert out["schema"] == "simplicio.stage-receipt/v1"
    assert out["role_id"] == INTAKE_PLANNER_ROLE_ID
