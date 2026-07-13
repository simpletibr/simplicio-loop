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

`GoalEnvelope` and `PlanDAG` both carry optional `producer_id`/`consumer_id`
fields (default `""`, so existing callers are unaffected — additive per the
compatibility contract above). When a `PlanDAG.consumer_id` is set,
`validate()` rejects it unless it appears in
`PLAN_COMPILER_COMPATIBILITY["consumers"]`, so a plan can't silently target a
runtime this contract doesn't know about.

## Validation

`PlanDAG.validate()` always rejects duplicate node ids, orphan `depends_on`
references, and dependency cycles. Pass `effects=` to also reject an
`EffectPlan` with a blank `authority_required`, or an irreversible effect
(`kind` in `write`/`delete`/`commit`/`irreversible`) on a node that doesn't
set `requires_gate`/`checkpoint_required`. Pass `verifications=` (even an
empty list) to also reject any node whose `acceptance_criteria_refs` aren't
covered by at least one `VerificationPlan`. Pass `budget=` to reject a node
set whose summed `estimated_cost` exceeds it — or leave it `None` (the
default) to fall back to `PlanDAG.budget` itself, so a plan compiled with a
budget already enforces it on every later `validate()` call without the
caller having to re-pass the same number. All failures raise
`PlanValidationError` with one diagnostic string per problem found.

`PlanDAG` carries an optional `budget: float | None = None` field (default
`None`, additive per the compatibility contract above) that round-trips
through `to_dict()`/`from_dict()` exactly like `producer_id`/`consumer_id` —
a caller-supplied cost ceiling survives compile, serialize and reload
unchanged, the same way `goal_id`/`plan_id`/`revision` already do.

`PlanDAG` also carries an optional `trace_id: str | None = None` field
(default `None`, additive per the compatibility contract above) that
round-trips through `to_dict()`/`from_dict()` the same way — a caller-supplied
tracing correlation id survives compile, serialize and reload unchanged, the
same way `goal_id`/`plan_id`/`revision`/`budget` already do.

## Tracing an acceptance criterion to its verifier and evidence

`VerificationPlan` already carries everything needed to answer "what proves
AC X passed": `verifier`, `command_or_capability`, `timeout_s` and
`expected_evidence` (plus `acceptance_criteria_refs`, the field `validate()`
uses to reject an uncovered AC). `PlanDAG.verifications_for_acceptance_criterion()`
is the lookup that makes this traceable per-AC instead of only "coverage
exists":

```python
matches = plan.verifications_for_acceptance_criterion("AC1", verifications)
matches[0].verifier                 # e.g. "pytest"
matches[0].command_or_capability     # e.g. "pytest -q tests/test_ac1.py"
matches[0].expected_evidence          # e.g. ["pytest-junit.xml"]
```

It takes the same `verifications` bundle passed to `validate()` and returns
every `VerificationPlan` whose `acceptance_criteria_refs` includes the given
AC id — `[]` for an AC with no coverage (a state `validate()` rejects when
`verifications=` is passed to it, so this mainly surfaces on a bundle that
hasn't been validated yet, or during debugging of *why* validation failed).

## Compiling a TaskSpec

`compile_task_spec_to_plan()` deterministically compiles an existing
`simplicio.task_spec.TaskSpec` into a validated `(PlanDAG, list[EffectPlan],
list[VerificationPlan])` bundle — no model call, no embedded execution:

```python
from simplicio.plan_compiler import compile_task_spec_to_plan

plan, effects, verifications = compile_task_spec_to_plan(
    task_spec,
    goal_id="goal-1",
    context_snapshot_id="snap-1",
    revision="1",
    budget=100.0,  # optional; defaults to None
    trace_id="trace-1",  # optional; defaults to None
)
```

It builds two nodes — `edit` (`edit.apply`, a `write` effect requiring a
gate) and `verify` (`test.run`, depending on `edit`, one `VerificationPlan`
per `task_spec.verification_commands`) — and maps every
`task_spec.acceptance_criteria` id onto both, so the compiled bundle always
passes `PlanDAG.validate(effects=..., verifications=...)`. It raises
`PlanCompilationError` (`NEEDS_CLARIFICATION: ...`) instead of guessing when
the TaskSpec has no acceptance criteria or no verification commands. Same
TaskSpec + same ids/revision always yields the same
`plan.canonical_hash()`. `goal_id`, `plan_id` (derived as
`f"plan-{task_spec.task_id}"`), `revision`, the optional `budget` and the
optional `trace_id` all survive the compile unchanged and observable on the
returned `PlanDAG` — see `tests/python/test_plan_compiler_golden_e2e.py` for
the golden E2E that locks this in (issue #166 AC "Golden E2E preserva
trace_id, goal_id, plan_id, revision e budget"), now fully closed: all five
fields are real, typed and round-trip through `to_dict()`/`from_dict()`.

## Scope of this slice

This slice adds the deterministic `TaskSpec -> PlanDAG` front-end; it is
still not wired into `simplicio-py intake`, `pipeline.run_task`, or
`orchestrator.multi_task.TaskBatch` — nothing calls
`compile_task_spec_to_plan()` from the CLI yet, and no execution/commit
happens against the compiled `EffectPlan`s. Wiring this compiler into the
CLI/pipeline entry points, sending `EffectPlan`s to the Runtime for
execution instead of running them locally, and retiring the duplicate
control-plane/retry logic (feature/sprint, global retry, operational
memory) in favor of the `PlanDAG` are tracked as later slices of issue
#166.
