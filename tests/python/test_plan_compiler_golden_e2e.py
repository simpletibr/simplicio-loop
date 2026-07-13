"""Golden E2E for the plan compiler (issue #166 slice N).

Turns the unchecked issue #166 acceptance criterion "Golden E2E preserva
trace_id, goal_id, plan_id, revision e budget" into an executable guarantee
for the four of those five identifiers/fields that already exist as real
domain concepts reachable from ``compile_task_spec_to_plan()``:

- ``goal_id`` -- caller-supplied, carried unchanged onto ``PlanDAG.goal_id``.
- ``plan_id`` -- derived deterministically as ``f"plan-{task_spec.task_id}"``
  and carried onto ``PlanDAG.plan_id``.
- ``revision`` -- caller-supplied, carried unchanged onto ``PlanDAG.revision``.
- ``budget`` -- caller-supplied cost ceiling. Before this slice, ``budget``
  only existed as an ephemeral ``PlanDAG.validate(budget=...)`` argument: it
  was never stored on the compiled ``PlanDAG``, so it did not round-trip
  through ``to_dict()``/``from_dict()`` and a consumer reading the compiled
  plan back could not observe what budget it was compiled against. This test
  locks in the fix: ``compile_task_spec_to_plan(..., budget=...)`` now stores
  it on ``PlanDAG.budget`` and it survives the full round trip.

``trace_id`` is intentionally NOT asserted here: it is not a real field or
concept anywhere in ``GoalEnvelope``/``ContextSnapshot``/``TaskSpec``/
``PlanDAG`` today (only generic architecture-doc prose in
``.specs/architecture/PATTERNS.md``/``DESIGN.md`` mentions a "trace_id" for
unrelated HTTP middleware, not this compiler's contracts). Inventing a
trace_id field here with no upstream producer would be exactly the kind of
fictional concept the #166 scoping note warns against -- see
"Scope of this slice" in docs/plan-compiler.md and the PR that introduces
this test for the explicit gap this leaves against the AC.
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


def test_golden_e2e_preserves_goal_plan_revision_and_budget() -> None:
    """A full compile must carry goal_id/plan_id/revision/budget through unchanged."""
    task_spec = _golden_task_spec()

    plan, effects, verifications = compile_task_spec_to_plan(task_spec, **GOLDEN_KWARGS)
    plan.validate(effects=effects, verifications=verifications)

    assert plan.goal_id == "goal-abc"
    assert plan.plan_id == "plan-T-golden"
    assert plan.revision == "42"
    assert plan.budget == 100.0

    payload = plan.to_dict()
    assert payload["goal_id"] == "goal-abc"
    assert payload["plan_id"] == "plan-T-golden"
    assert payload["revision"] == "42"
    assert payload["budget"] == 100.0

    restored = PlanDAG.from_dict(payload)
    assert restored.goal_id == "goal-abc"
    assert restored.plan_id == "plan-T-golden"
    assert restored.revision == "42"
    assert restored.budget == 100.0
    assert restored == plan
    assert restored.canonical_hash() == plan.canonical_hash()


def test_golden_e2e_budget_defaults_to_none_when_not_supplied() -> None:
    """Existing callers that never pass budget= keep getting an unset budget."""
    kwargs = dict(GOLDEN_KWARGS)
    del kwargs["budget"]

    plan, effects, verifications = compile_task_spec_to_plan(_golden_task_spec(), **kwargs)
    plan.validate(effects=effects, verifications=verifications)

    assert plan.budget is None
    assert plan.to_dict()["budget"] is None
    assert PlanDAG.from_dict(plan.to_dict()).budget is None


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
