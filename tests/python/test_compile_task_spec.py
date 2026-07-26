"""Tests for the deterministic TaskSpec -> PlanDAG compiler (issue #166 slice 2)."""

from __future__ import annotations

import pytest

from simplicio.plan_compiler import PlanCompilationError, PlanValidationError
from simplicio.plan_compiler.compile_task_spec import compile_task_spec_to_plan
from simplicio.task_spec import TaskSpec

COMPILE_KWARGS = {
    "goal_id": "goal-1",
    "context_snapshot_id": "snap-1",
    "revision": "1",
}


def _task_spec(**overrides: object) -> TaskSpec:
    defaults: dict[str, object] = {
        "task_id": "T1",
        "source": {"kind": "argument"},
        "source_hash": "deadbeef",
        "language": "pt-BR",
        "acceptance_criteria": [{"id": "AC1"}, {"id": "AC2"}],
        "verification_commands": [{"command": "pytest tests/python/test_foo.py -q"}],
    }
    defaults.update(overrides)
    return TaskSpec(**defaults)  # type: ignore[arg-type]


def test_compile_task_spec_produces_valid_plan() -> None:
    plan, effects, verifications = compile_task_spec_to_plan(_task_spec(), **COMPILE_KWARGS)

    assert plan.plan_id == "plan-T1"
    assert [node.node_id for node in plan.nodes] == ["edit", "verify"]
    assert plan.nodes[1].depends_on == ["edit"]
    assert effects[0].kind == "write"
    assert effects[0].plan_node_id == "edit"
    assert verifications[0].command_or_capability == "pytest tests/python/test_foo.py -q"

    # Raises nothing: the compiled bundle is internally consistent.
    plan.validate(effects=effects, verifications=verifications)


def test_compile_task_spec_is_deterministic() -> None:
    task_spec = _task_spec()
    plan_a, _, _ = compile_task_spec_to_plan(task_spec, **COMPILE_KWARGS)
    plan_b, _, _ = compile_task_spec_to_plan(task_spec, **COMPILE_KWARGS)

    assert plan_a.canonical_hash() == plan_b.canonical_hash()


def test_compile_records_semantic_context_budget_spans_and_expected_hashes() -> None:
    task_spec = _task_spec(
        extra_fields={
            "context_budget_tokens": 100,
            "context_consumed_tokens": 120,
            "selected_span_ids": ["symbol:user.create", "file:src/users.py"],
            "expected_hashes": {"src/users.py": "a" * 64},
        }
    )

    plan, effects, _ = compile_task_spec_to_plan(
        task_spec,
        **COMPILE_KWARGS,
        context_handle="sha256:" + "b" * 64,
    )

    for node in plan.nodes:
        assert node.semantic_inputs == [
            "snapshot:snap-1",
            "context:sha256:" + "b" * 64,
        ]
        assert node.context_budget_tokens == 100
        assert node.context_consumed_tokens == 120
        assert node.context_truncated is True
        assert node.selected_span_ids == ["file:src/users.py", "symbol:user.create"]
    assert "file_sha256:src/users.py:" + "a" * 64 in effects[0].preconditions
    assert "content" not in str(plan.to_dict()).lower()


def test_compile_task_spec_rejects_missing_acceptance_criteria() -> None:
    task_spec = _task_spec(acceptance_criteria=[])

    with pytest.raises(PlanCompilationError, match="NEEDS_CLARIFICATION"):
        compile_task_spec_to_plan(task_spec, **COMPILE_KWARGS)


def test_compile_task_spec_rejects_missing_verification_commands() -> None:
    task_spec = _task_spec(verification_commands=[])

    with pytest.raises(PlanCompilationError, match="NEEDS_CLARIFICATION"):
        compile_task_spec_to_plan(task_spec, **COMPILE_KWARGS)


def test_compile_task_spec_covers_every_acceptance_criterion() -> None:
    plan, effects, verifications = compile_task_spec_to_plan(_task_spec(), **COMPILE_KWARGS)

    covered = {ref for verification in verifications for ref in verification.acceptance_criteria_refs}
    all_refs = {ref for node in plan.nodes for ref in node.acceptance_criteria_refs}
    assert all_refs <= covered

    # A node missing AC coverage would fail validate(); prove the inverse too.
    with pytest.raises(PlanValidationError):
        plan.validate(effects=effects, verifications=[])
