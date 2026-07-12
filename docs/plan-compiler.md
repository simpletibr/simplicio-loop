# Plan compiler contracts

`simplicio.plan_compiler` defines the typed interchange contract for issue #166:
Goal + ContextSnapshot in, `PlanDAG` + `EffectPlan` + `VerificationPlan` out,
with no embedded execution. These schemas do not exist as an importable
package anywhere else in the simplicio ecosystem today, so this module is the
**reference implementation** — versioned exactly like `simplicio.task-spec/v2`
(`simplicio.task_spec`) — that `simplicio-runtime`/`simplicio-loop` can adopt
as a consumer contract without this package importing their code.

```python
from simplicio.plan_compiler import EffectPlan, PlanDAG, PlanNode, VerificationPlan

plan = PlanDAG(
    plan_id="plan-1",
    goal_id="goal-1",
    context_snapshot_id="snap-1",
    revision="1",
    nodes=[
        PlanNode(node_id="n1", capability="edit.apply", acceptance_criteria_refs=["AC1"]),
        PlanNode(node_id="n2", capability="test.run", depends_on=["n1"]),
    ],
)
plan.validate(
    verifications=[
        VerificationPlan(
            verification_id="v1",
            plan_node_id="n1",
            verifier="pytest",
            command_or_capability="pytest -q",
            timeout_s=60.0,
            acceptance_criteria_refs=["AC1"],
        )
    ]
)
plan.canonical_hash()  # same canonical entry -> same hash, always
```

## Schemas

| Type | Schema id |
|---|---|
| `ContextSnapshot` | `simplicio.context-snapshot/v1` |
| `GoalEnvelope` | `simplicio.goal-envelope/v1` |
| `PlanDAG` | `simplicio.plan-dag/v1` |
| `EffectPlan` | `simplicio.effect-plan/v1` |
| `VerificationPlan` | `simplicio.verification-plan/v1` |

`PLAN_COMPILER_COMPATIBILITY` declares `major=1`, `minimum_consumer_major=1`,
and `contract="additive-fields-within-major"` — new fields may be added within
a major version; consumers should reject a `schema` string whose major
doesn't match what they expect via `SchemaMismatchError`, raised by every
`from_dict()` when the `schema` field mismatches.

## Validation

`PlanDAG.validate()` always rejects duplicate node ids, orphan `depends_on`
references, and dependency cycles. Pass `effects=` to also reject an
`EffectPlan` with a blank `authority_required`, or an irreversible effect
(`kind` in `write`/`delete`/`commit`/`irreversible`) on a node that doesn't
set `requires_gate`/`checkpoint_required`. Pass `verifications=` (even an
empty list) to also reject any node whose `acceptance_criteria_refs` aren't
covered by at least one `VerificationPlan`. Pass `budget=` to reject a node
set whose summed `estimated_cost` exceeds it. All failures raise
`PlanValidationError` with one diagnostic string per problem found.

## Scope of this slice

This module only defines and validates the contracts — it is not yet wired
into `simplicio-py intake`, `pipeline.run_task`, or
`orchestrator.multi_task.TaskBatch`. Compiling a `TaskSpec`/`TaskBatch` into a
`PlanDAG`, generating `EffectPlan`s without executing them, and retiring the
duplicate control-plane/retry logic are tracked as later slices of issue #166.
