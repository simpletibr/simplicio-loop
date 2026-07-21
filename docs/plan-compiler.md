# Plan compiler contracts

`simplicio.plan_compiler` defines the typed interchange contract for issue #166:
Goal + Mapper context in, `PlanDAG` + `EffectPlan` + `VerificationPlan` out,
with no embedded execution. Goal/plan/effect/verification schemas remain local
to this package. `simplicio.context-snapshot/v1` is owned exclusively by
`simplicio-mapper`: the public `load_mapper_context()` boundary reads its
packaged conformance manifest, pins it to Mapper commit
`05ea96390762d4bba309abcbf4783d0637a4e53f` and digest
`db8cf791fe6442585f03b3fac220c0987ca5e4271a4955df02b1df77018c52b0`, then
delegates validation and canonical serialization to Mapper. Dev CLI neither
copies nor reshapes that schema; it retains immutable canonical bytes and
exposes a derived planning view. The former Dev CLI shape is rejected if it
claims Mapper's schema id.
Standalone fallback, when later wired, must use
`simplicio.dev-cli.context-fallback/v1`, never Mapper's id.

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
| Mapper context view | `simplicio.context-snapshot/v1` (owned by `simplicio-mapper`; consumed through `load_mapper_context`) |
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

## N-1 compatibility adapter (issue #167 slice 11/23)

`simplicio.plan_compiler.compat_adapter` is a narrow, one-hop compatibility
edge between the current field set ("N") that `GoalEnvelope`/`PlanDAG` carry
and the field set a caller stuck one generation behind still expects
("N-1"). It builds directly on the `producer_id`/`consumer_id` versioning
added to both types in #171 and the `budget` field added to `PlanDAG` after
that: the `schema` string (`simplicio.plan-dag/v1` etc.) never bumps its
major version for these additions — per
`PLAN_COMPILER_COMPATIBILITY["contract"] == "additive-fields-within-major"`
— so this module tracks the field-level generation separately, with its own
small integer versions:

- `GOAL_ENVELOPE_VERSION = 1` (current): has `producer_id`/`consumer_id`.
  N-1 (`version 0`) predates both fields.
- `PLAN_DAG_VERSION = 2` (current): has `producer_id`/`consumer_id` and
  `budget`. N-1 (`version 1`) has the ids (#171) but not `budget`.

```python
from simplicio.plan_compiler.compat_adapter import (
    PLAN_DAG_VERSION,
    adapt_inbound,
    adapt_outbound,
)

# Outbound: a current PlanDAG, translated for an N-1-only consumer.
n_minus_1_payload = adapt_outbound(plan, PLAN_DAG_VERSION - 1)  # no "budget" key

# Inbound: an N-1-shaped payload, upgraded into a current PlanDAG.
plan = adapt_inbound(n_minus_1_payload, PLAN_DAG_VERSION - 1)  # plan.budget is None
```

`adapt_goal_envelope_outbound`/`adapt_goal_envelope_inbound` are the
`GoalEnvelope` equivalents. Every function rejects anything other than the
immediate N-1 boundary with `UnsupportedCompatVersionError` — this is
deliberately not a general schema-migration framework; only one hop of
rollback/rollforward is supported.

**Fixtures**: `tests/fixtures/plan_compiler/n_minus_1/` holds genuine
N-1-shaped payloads (`goal_envelope_n_minus_1.json`,
`plan_dag_n_minus_1_simple.json`, `plan_dag_n_minus_1_no_ids.json`), used by
`tests/python/test_plan_compiler_n_minus_1_adapter.py` for round-trip and
rollback-scenario coverage.

**Expiry**: this compat surface is explicitly not permanent (issue #167
invariant 6, "Compatibilidade Hermes fica em uma borda registrada"; plan
step 26, "Retirar alias só pela policy #193"). `GOAL_ENVELOPE_ADAPTER_EXPIRES_AT_VERSION`
and `PLAN_DAG_ADAPTER_EXPIRES_AT_VERSION` are set to "current version + 2" —
once `GOAL_ENVELOPE_VERSION`/`PLAN_DAG_VERSION` reaches that threshold (i.e.
two more additive-field generations have shipped), every adapter call for
that type raises `CompatAdapterExpiredError` instead of silently
translating forever. Retiring the adapter at that point, and introducing a
fresh N/N-1 pair if still needed, follows the alias-retirement policy in
#193.

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

## Control-plane ownership inventory (retry / feature-sprint scheduling)

Issue #166's step 0 ("Caracterizar o pipeline atual") and step 5 ("Remover
control plane duplicado") ask for an explicit map of every retry loop and
feature/sprint scheduling call site before any of it can be migrated to the
Runtime/Loop policy layer. This section is that map, current as of this
slice. It is deliberately scoped to *retry and scheduling ownership* — the
"zero-write outside the Effect API" half of step 5 is a separate, larger
effort tracked against the Runtime's own Effect API (#3134/#3135) and is
**not** covered here.

### Retry-loop call sites

| Owner | File:line | Attempts | Overridable today? | Notes |
|---|---|---|---|---|
| `pipeline.run_task` | `simplicio/pipeline.py:51,345-346` | `MAX_ATTEMPTS = 5` | **No** (before this slice) — now `SIMPLICIO_MAX_ATTEMPTS` (see below) | Innermost, most-invoked retry loop: generate → apply → test → static-fixer → retry, feeding back a validation diff each attempt. |
| `orchestrator.feature.run_feature` | `simplicio/orchestrator/feature.py:76,104-182` | `max_iter = 3` (constructor default) replans, each replan re-running the *entire remaining task list* through `run_plan_task` | Yes — `max_iter` is a function parameter (CLI-controlled) | This is feature/sprint scheduling, not the AC's `run_task` loop, but it fully wraps `run_task` — see multiplication risk below. |
| `scratch.planner.generate_plan` | `simplicio/scratch/planner.py:23,148-165` | `PLANNER_MAX_RETRIES = 3` (+1 first attempt) | Yes — `SIMPLICIO_PLANNER_MAX_RETRIES` env var already exists | Already follows the pattern this slice adds to `pipeline.run_task`; used as the precedent for the fix below. |
| `orchestrator.multi_task.TaskBatch.drain` | `simplicio/orchestrator/multi_task.py:326-434` | **None** — `_executor_outcome` only accepts `{"passed", "blocked"}`, both terminal (`TERMINAL = {"passed", "blocked"}`); a blocked card is never automatically re-attempted by the batch itself | N/A | Confirms the batch scheduler is *already* single-atomic-attempt per card at its own layer — the duplication risk lives one layer down, inside whatever `executor` callback it is given (typically `run_task`/`run_feature`), not in `TaskBatch` itself. |

### Feature/sprint scheduling call sites

| File:line | Role |
|---|---|
| `simplicio/orchestrator/feature.py:71-196` (`run_feature`) | Owns feature-scope planning: generates a task plan, orders it, runs each task, and replans the *whole remaining plan* (not just the failed task) on failure, up to `max_iter` times. This is scheduling logic living in Dev CLI, matching the issue's "feature/sprint... se sobrepõem ao Loop e ao Runtime" complaint. Not migrated to `PlanDAG` in this slice — that migration is the literal AC #166 step 5.1 and is a large, separate effort (planning + replanning semantics need a `PlanDAG`-shaped replacement, not just a call-site swap). |
| `simplicio/orchestrator/multi_task.py` (`TaskBatch`) | Owns cross-task DAG state (dependencies, resumability, parallel drain), but — per the table above — does **not** itself retry; it hands each ready card to an injected `executor` exactly once per round and treats the result as terminal. |
| `simplicio/scratch/executor.py` (`execute_plan`, `_execute_one_task`) | Owns scratch/scaffold-mode task iteration (topological order, codegen-vs-LLM fallback); calls `run_task` at most once per task, no internal retry of its own. |

### Double-retry risk: is it real, and where

The concrete multiplication risk is **`pipeline.run_task`'s internal
`MAX_ATTEMPTS` loop being invoked from inside an already-retrying caller**:

- `simplicio-py task` (`simplicio/commands/task.py`) invokes `run_task` directly as
  the CLI's single "atomic command" surface a host loop (e.g. simplicio-loop)
  is expected to call once per its own retry/replan iteration. Before this
  slice, every such invocation always ran up to 5 internal attempts with no
  way to opt out, so an external loop that retries N times on failure would
  produce `N × 5` total generate/apply/test attempts for what the external
  loop believes is `N` attempts — a real duplication, not a hypothetical one.
- `orchestrator.feature.run_feature` compounds this further for feature
  scope: each of its `max_iter` replans re-runs every remaining task through
  `run_task`, so a single `simplicio-py run --feature` invocation with default
  settings could already trigger up to `3 × 5 = 15` generate attempts per
  task before any external loop layer even gets involved.
- `scratch.planner.generate_plan`, by contrast, already exposes
  `SIMPLICIO_PLANNER_MAX_RETRIES` — an external caller that wants a single
  planner attempt can already ask for it. `pipeline.run_task` had no
  equivalent lever, which was the concrete, fixable gap.

### What this slice changes (and what it deliberately does not)

`pipeline.run_task` now reads an optional `SIMPLICIO_MAX_ATTEMPTS` env var
(`simplicio/pipeline.py:_resolve_max_attempts`) and uses it instead of the
hardcoded `MAX_ATTEMPTS` module constant when present. Setting
`SIMPLICIO_MAX_ATTEMPTS=1` makes a single `run_task` invocation perform at
most one atomic generate/apply/test attempt and return its classified
observation — the exact behavior AC #166 step 5.3 asks for — for any caller
(host loop, CI, `simplicio-py task`) that already owns its own retry policy
and wants to opt out of Dev CLI's internal one. When the env var is unset,
behavior is byte-for-byte unchanged (`MAX_ATTEMPTS = 5`, same as before).

This is intentionally narrow. It does **not**:

- Migrate `orchestrator.feature.run_feature`'s replan loop or
  `orchestrator.multi_task.TaskBatch` scheduling to `PlanDAG` (AC #166 step
  5.1) — that requires the compiled `PlanDAG`/`EffectPlan` to actually be the
  thing an execution loop walks, which depends on the wiring work described
  in "Scope of this slice" above (not yet done) and on the Runtime side of
  #3134/#3135.
- Change the default behavior for standalone use in any way.
- Attempt to make Dev CLI "return a classified observation without starting
  a new strategy" (AC #166 step 5.4) for `run_feature`'s replan loop — that
  loop's replanning *is* a new strategy by design and removing it is exactly
  the larger migration this slice does not attempt.

Net: this slice closes the "no lever to prevent multiplication" gap for the
single most duplicated retry loop (`pipeline.run_task`) and leaves the
feature/sprint scheduler migration — the larger and riskier half of AC
#166's "Retry global, feature/sprint scheduler e operational memory deixam
de ter dois owners ativos" — open and explicitly documented as such.

## Integrated mode: the effect-sink boundary (issues #166, #167)

Both #166 ("No modo integrado, zero escrita/commit fora da Effect API do
Runtime") and #167 ("Modo integrado não executa writes diretamente") name
the same unchecked acceptance criterion. Before this slice there was no
"modo integrado" concept anywhere in the Dev CLI — `pipeline.run_task`
always applied the generated patch directly (`git apply` against the
worktree, then ran `SIMPLICIO_TEST_CMD`), which is exactly the "standalone"
adapter issue #166 step 4.5 says must remain, explicit and deprecable, as
the default. There was no alternative path to test the "zero write in
integrated mode" invariant against, which is why both boxes stayed
unchecked.

This slice adds that alternative path as an explicit, opt-in mode:

```python
from simplicio import pipeline
from simplicio.plan_compiler import RecordingEffectSink

sink = RecordingEffectSink()  # reference stub; see below
result = pipeline.run_task(
    root, stack, goal, target, criteria, constraints,
    mode="integrated",
    effect_sink=sink,
)
```

`run_task(..., mode="integrated", effect_sink=...)` delegates to
`simplicio.pipeline_integrated.run_integrated`, which:

1. builds a minimal `simplicio.task_spec.TaskSpec` from the raw
   `goal`/`criteria`/`constraints` strings `run_task` already takes (each
   non-blank `criteria` line becomes one acceptance criterion);
2. compiles it with `compile_task_spec_to_plan()` into a validated
   `(PlanDAG, list[EffectPlan], list[VerificationPlan])` bundle — the same
   compiler documented earlier in this file, now finally wired into the
   pipeline it was written for (see "Scope of this slice" above, which
   flagged this exact gap);
3. hands every compiled `EffectPlan` to the caller-supplied `effect_sink`
   — a `Callable[[EffectPlan], EffectApplyResult]` defined in
   `simplicio/plan_compiler/effect_sink.py` — and returns a result dict
   carrying the compiled `plan`, `effects`, `verifications` and each sink's
   `effect_sink_results`, with `applied` always `False` (nothing was
   applied; a `status` of `"integrated_planned"` distinguishes this outcome
   from standalone's `"applied"`/`"failed"`).

At no point does `run_integrated` call `git apply`, `_apply_and_test`, or
write to `root`. This is not merely a code-review claim:
`tests/python/test_pipeline_integrated_mode.py` snapshots every file under
the test worktree (excluding `.simplicio/`, which every mode legitimately
writes as observability evidence per `emit_event`'s contract) before and
after a `mode="integrated"` call and asserts the snapshot is byte-for-byte
unchanged, alongside a matching standalone-mode test proving the same
worktree *is* mutated by `git apply` in the unchanged default path.

`effect_sink` is mandatory in integrated mode: passing `mode="integrated"`
without one raises `IntegratedModeRequiresSinkError` instead of silently
falling back to a direct write. This is deliberate — the alternative (an
implicit standalone fallback) would silently reintroduce the exact
violation both issues flag.

### The sink is a local stub, not the Runtime

`effect_sink` is not, and is not meant to be, `simplicio-runtime`'s Effect
API — that API does not exist as importable code anywhere in this
ecosystem yet (see `simplicio-dev-cli` issue #166's parent, Runtime
#3134/#3135). `simplicio.plan_compiler.effect_sink` defines the local,
typed boundary this Dev CLI calls into instead:

- `EffectSink` — a `Protocol` any concrete sink must satisfy:
  `__call__(self, effect: EffectPlan) -> EffectApplyResult`.
- `EffectApplyResult` — what a sink reports back; `accepted=True` only
  means the sink took custody of the effect (e.g. queued it for the
  Runtime to authorize), never that it was applied to any worktree.
- `RecordingEffectSink` — the reference no-op implementation this
  repository's own tests use: it appends every `EffectPlan` it receives to
  `self.received` and applies none of them. This is what lets the
  integrated-mode contract be proven today, without needing the real
  Runtime to exist.

A production integration is expected to swap `RecordingEffectSink` for a
sink that actually forwards to `simplicio-runtime`'s Effect API once it
ships — that swap is the intended extension point, and this slice's job
was to build the boundary the swap plugs into, not the Runtime side of it.

### What this closes, and what it does not

This closes the Dev-CLI-side half of both unchecked ACs: integrated mode,
once opted into, never applies an effect itself and always routes through
the sink. It does **not**:

- Implement the real Runtime Effect API — that is Runtime #3134/#3135,
  external to this repository.
- Wire integrated mode into `cli.py`'s `simplicio-py task` command or any
  other CLI entry point — `mode`/`effect_sink` are `pipeline.run_task`
  parameters only in this slice, with no `--integrated` flag yet. A caller
  (e.g. a future Runtime-aware wrapper) constructs a real sink and calls
  `run_task(..., mode="integrated", effect_sink=...)` directly.
- Change `mode="standalone"` (the default) in any way — every existing
  `run_task`/`run` call site and test is unaffected.
