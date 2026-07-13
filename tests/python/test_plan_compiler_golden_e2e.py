"""Golden E2E for the plan compiler (issue #166 slice N).

Turns the issue #166 acceptance criterion "Golden E2E preserva trace_id,
goal_id, plan_id, revision e budget" into an executable guarantee for all
five identifiers/fields, each reachable from ``compile_task_spec_to_plan()``:

- ``goal_id`` -- caller-supplied, carried unchanged onto ``PlanDAG.goal_id``.
- ``plan_id`` -- derived deterministically as ``f"plan-{task_spec.task_id}"``
  and carried onto ``PlanDAG.plan_id``.
- ``revision`` -- caller-supplied, carried unchanged onto ``PlanDAG.revision``.
- ``budget`` -- caller-supplied cost ceiling. Before the slice that added it,
  ``budget`` only existed as an ephemeral ``PlanDAG.validate(budget=...)``
  argument: it was never stored on the compiled ``PlanDAG``, so it did not
  round-trip through ``to_dict()``/``from_dict()`` and a consumer reading the
  compiled plan back could not observe what budget it was compiled against.
  That slice fixed it: ``compile_task_spec_to_plan(..., budget=...)`` stores
  it on ``PlanDAG.budget`` and it survives the full round trip.
- ``trace_id`` -- caller-supplied tracing correlation id. Before this slice
  it was completely absent from every typed model
  (``GoalEnvelope``/``ContextSnapshot``/``TaskSpec``/``PlanDAG``), documented
  as an explicit gap against this AC. This slice closes it the same way
  ``budget`` was closed: ``compile_task_spec_to_plan(..., trace_id=...)``
  stores it on ``PlanDAG.trace_id`` (optional, defaults to ``None`` so
  existing callers are unaffected) and it survives the full round trip.
"""

from __future__ import annotations

import pytest

from simplicio.plan_compiler import (
    PlanDAG,
    PlanValidationError,
    compile_task_spec_to_plan,
)
from simplicio.task_spec import TaskSpec

GOLDEN_KWARGS = {
    "goal_id": "goal-abc",
    "context_snapshot_id": "snap-abc",
    "revision": "42",
    "budget": 100.0,
    "trace_id": "trace-abc",
}


def _golden_task_spec() -> TaskSpec:
    return TaskSpec(
        task_id="T-golden",
        source={"kind": "argument"},
        source_hash="deadbeef",
        language="pt-BR",
        acceptance_criteria=[{"id": "AC1"}, {"id": "AC2"}],
        verification_commands=[{"command": "pytest tests/python/test_foo.py -q"}],
    )


def test_golden_e2e_preserves_goal_plan_revision_budget_and_trace_id() -> None:
    """A full compile must carry goal_id/plan_id/revision/budget/trace_id through unchanged."""
    task_spec = _golden_task_spec()

    plan, effects, verifications = compile_task_spec_to_plan(task_spec, **GOLDEN_KWARGS)
    plan.validate(effects=effects, verifications=verifications)

    assert plan.goal_id == "goal-abc"
    assert plan.plan_id == "plan-T-golden"
    assert plan.revision == "42"
    assert plan.budget == 100.0
    assert plan.trace_id == "trace-abc"

    payload = plan.to_dict()
    assert payload["goal_id"] == "goal-abc"
    assert payload["plan_id"] == "plan-T-golden"
    assert payload["revision"] == "42"
    assert payload["budget"] == 100.0
    assert payload["trace_id"] == "trace-abc"

    restored = PlanDAG.from_dict(payload)
    assert restored.goal_id == "goal-abc"
    assert restored.plan_id == "plan-T-golden"
    assert restored.revision == "42"
    assert restored.budget == 100.0
    assert restored.trace_id == "trace-abc"
    assert restored == plan
    assert restored.canonical_hash() == plan.canonical_hash()


def test_golden_e2e_budget_and_trace_id_default_to_none_when_not_supplied() -> None:
    """Existing callers that never pass budget=/trace_id= keep getting them unset."""
    kwargs = dict(GOLDEN_KWARGS)
    del kwargs["budget"]
    del kwargs["trace_id"]

    plan, effects, verifications = compile_task_spec_to_plan(_golden_task_spec(), **kwargs)
    plan.validate(effects=effects, verifications=verifications)

    assert plan.budget is None
    assert plan.trace_id is None
    assert plan.to_dict()["budget"] is None
    assert plan.to_dict()["trace_id"] is None
    assert PlanDAG.from_dict(plan.to_dict()).budget is None
    assert PlanDAG.from_dict(plan.to_dict()).trace_id is None


def test_golden_e2e_validate_enforces_stored_budget_without_explicit_override() -> None:
    """A budget stored on the compiled PlanDAG is enforced by validate() for free.

    ``compile_task_spec_to_plan()`` already calls ``plan.validate()`` once as a
    defense-in-depth check before returning, so an impossible budget (below
    every node's ``estimated_cost``) must fail at compile time already -- the
    same call site that used to ignore ``budget`` entirely before this slice.
    """
    task_spec = _golden_task_spec()
    kwargs = dict(GOLDEN_KWARGS)
    kwargs["budget"] = -1.0  # compiled nodes always have estimated_cost >= 0.0

    with pytest.raises(PlanValidationError, match="exceeds budget"):
        compile_task_spec_to_plan(task_spec, **kwargs)

    # And re-validating an already-compiled plan against its own stored
    # budget, with no explicit override, still enforces it independently.
    kwargs["budget"] = GOLDEN_KWARGS["budget"]
    plan, effects, verifications = compile_task_spec_to_plan(task_spec, **kwargs)
    object.__setattr__(plan, "budget", -1.0)
    with pytest.raises(PlanValidationError, match="exceeds budget"):
        plan.validate(effects=effects, verifications=verifications)
