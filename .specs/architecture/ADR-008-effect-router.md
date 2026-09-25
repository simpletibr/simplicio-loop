# ADR-008: Freeze the `EffectMode` enum and classify-before-spend router

---

## Status

`Aceito`

---

## Data

`2026-09-25`

---

## Autores

- `wesleysimplicio`
- `Claude (simplicio-loop worker, issue #709)`

---

## Contexto

#33 delivered the four LLM-reduction levers and #37 delivered the deterministic
CST codegen executors (`simplicio/scratch/codegen/`). Both are mechanical
generation *for the scratch scaffolding subsystem* (`simplicio/scratch/`) —
neither is the agent's own runtime effect router. Before #709, the agent
loop had no explicit gate stopping it from falling into a full-file LLM
generate for an ordinary code edit: whether an edit was mechanical, codegen,
or LLM-authored was implicit in whatever code path happened to run, not a
frozen, testable decision made *before* tokens are spent.

The write path already existed and is not touched by this ADR:
`simplicio.mechanical_edit.execute_plan` requires a preimage (`expected_sha256`
/ Mapper binding hash), fails closed on a missing or ambiguous anchor, and
never invents text — this is Mode 1 in the issue body, already shipped.

## Decisão

Freeze a three-way `EffectMode` enum (`simplicio/effect_router.py`) —
`MECHANICAL_EDIT | CODEGEN | LLM` — and a pure `classify(task, mapper_hits)`
function that decides between them **before** any LLM call, per the rule:

```
se da para apontar o trecho exato no arquivo   ->  MECHANICAL_EDIT
senao, se a transformacao esta na whitelist    ->  CODEGEN
senao, e so entao                              ->  LLM
depois de qualquer um                          ->  runtime apply + verify
```

Scope:

- **In scope**: the enum, the classifier, the Mode 3 full-file budget guard
  (`reject_full_file_llm_edit` / `validate_llm_edit`), the certify-failure
  escalation state machine (`EscalationState`), and the
  `simplicio.execution-report/v1` receipt builder
  (`build_execution_report`). Wiring the Mode 3 guard into
  `simplicio.commands.edit.run_edit` for any plan explicitly marked
  `effect_mode: "llm"` (additive, opt-in field; every other plan shape is
  untouched).
- **Out of scope** (per the issue body): new CST executors, an empirical
  50-scratch benchmark, productizing codegen as a marketing feature,
  reimplementing the #37 executors — `classify()` only reads the executor
  *names* already registered in `simplicio.scratch.codegen.registry` as its
  whitelist; it never opens a second, generic codegen engine.
- **Owner**: Dev CLI (`simplicio/effect_router.py`), same ownership boundary
  as `simplicio/mechanical_edit.py` and `simplicio/dev_cli_contracts.py`.

How it is applied:

1. The caller (an agent turn, or a future `task`/`run` command) builds a
   `task` mapping (`path`, `old`, `exact_span`, `expected_sha256`,
   `transform`) and a Mapper-survey `mapper_hits` sequence for that path.
2. `classify()` returns a `RouteDecision`: a mode, or a refused decision with
   a `reason_code` (`preimage_miss`, `ambiguous_anchor`) that the caller must
   treat as fail-closed — abort, do not silently promote to a more expensive
   mode on the first failure.
3. Mode 1 dispatches to `mechanical_edit.execute_plan` (unchanged). Mode 2
   dispatches to the already-registered `scratch.codegen` executor by name
   (unchanged, per "não reimplementar"). Mode 3 produces a plan + edits
   (never a whole file); `validate_llm_edit` is the budget gate that keeps it
   honest, wired for real into `commands.edit.run_edit` behind the
   `effect_mode: "llm"` marker.
4. Any apply failure feeds `EscalationState.record_failure()`: same mode
   retried once, escalates on the second consecutive failure, never
   de-escalates.
5. Every apply — regardless of mode — is recorded through
   `build_execution_report()`, schema `simplicio.execution-report/v1`,
   carrying `mode`, `tokens`, `patches`, and `certify`.

## Consequências

### Positivas (+)

- The mode an edit ran in is now a typed, testable value (`EffectMode`)
  instead of an implicit code-path choice — the router has fixtures for
  every branch (edit ok, preimage miss, codegen whitelist hit, LLM
  full-file rejected).
- The Mode 3 budget guard is a single reusable function
  (`reject_full_file_llm_edit`) shared by both a future MCP surface and the
  existing `edit` CLI command, so "reject full-file" is one rule, not one
  per integration point.
- The escalation state machine makes "never de-escalate without evidence"
  a property of a small, unit-tested class rather than a convention agents
  are trusted to remember turn over turn.

### Negativas (-)

- `classify()`'s codegen whitelist match is name-based
  (`task["transform"] in {executor.name for executor in registered_executors()}`);
  it does not (yet) call `TaskExecutor.can_handle()`, because that method
  requires a `scratch.plan_schema.Task`/`Stack` pair scoped to the scaffold
  subsystem, not the generic `task` mapping this router accepts. A caller
  that wants the stricter `can_handle()` check still has to do it itself
  before trusting a `CODEGEN` decision.
- The Mode 3 full-file guard is wired into `commands.edit.run_edit` only
  for plans that opt in via `effect_mode: "llm"`; a caller that skips the
  marker gets no automatic protection from this ADR (though
  `mechanical_edit.execute_plan`'s existing preimage/anchor checks still
  apply regardless).

### Neutras / observações

- This ADR does not add a new top-level CLI command; `effect_router.py` is
  a library module other commands (`edit`, and eventually `task`/`run`)
  import, matching the shape of `simplicio/standalone_migration.py` and
  `simplicio/dev_cli_contracts.py`.

## Alternativas consideradas

### Alternativa A — Fold routing into `mechanical_edit.py`

Add the classification and budget-guard logic directly into the existing
`mechanical_edit.py` module. Rejected: that module is already large and
heavily tested as the Mode 1 *executor*; mixing in Mode 2/Mode 3 routing
concerns would blur "the module that applies edits" with "the module that
decides which mode to use", and any future change to routing policy would
risk destabilizing the preimage/anchor apply path.

### Alternativa B — Reimplement `scratch.codegen` executors against a generic `task` shape

Give the router its own copy of codegen dispatch, decoupled from
`scratch.plan_schema.Task`/`Stack`. Rejected outright by the issue body
("não reimplementar executors de #37; só despachar para eles") and by
CLAUDE.md's "prefer mature, maintained... do not rewrite without an explicit
technical reason" rule — the existing whitelist is reused by name instead.

## Critério de revisão

- When `simplicio.scratch.codegen` executors gain a generic (non-scaffold)
  `Task`/`Stack`-independent entry point, revisit whether `classify()` should
  call `can_handle()` directly instead of matching on `executor.name`.
- When an MCP server ships in this repository, wire
  `effect_router.validate_llm_edit` into its edit tool the same way it is
  wired into `commands.edit.run_edit` here, rather than reinventing the
  check.

## Links

- Issue: https://github.com/simpletibr/simplicio-dev-cli/issues/709
- Related (done, not duplicated): #33, #37
- Implementation: `simplicio/effect_router.py`, `simplicio/commands/edit.py`
- Documentos relacionados: `[DESIGN](./DESIGN.md)`, `[PATTERNS](./PATTERNS.md)`
