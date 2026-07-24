# Issue 257 execution-mode evidence

Base SHA: `f0f9231`. Branch: `feat/257-integrated-entrypoint`. Environment: Python 3.12.13,
Linux x86_64.

The implemented negotiation matrix covers Runtime present, absent, and incompatible; canonical Mapper
context present, absent, and incompatible; Agent and non-Agent coordinators; fallback allowed and
denied; shadow, canary, kill switch, and explicit standalone. Integrated requests block before planning
when any production contract is unavailable. The test-only `RecordingEffectSink` is never eligible.

Validation results:

- focused unit/integration/system/regression suite: 73 passed;
- execution-mode branch coverage: 97.53% (98% statement display);
- negotiation benchmark: 10,000 calls in 0.638335 seconds, 63.83 microseconds/call;
- package dependency document check: passed;
- wheel and sdist build plus Twine checks: passed (existing setuptools license deprecation warnings);
- clean-venv wheel install and `runtime capabilities --mode integrated --json`: passed and returned
  `INCOMPATIBLE_RUNTIME` with clean JSON;
- focused Ruff lint/format and diff credential-pattern scan: passed.

Repository-wide validation remains non-green at this base independently of the issue diff: `mypy
simplicio` reports two errors in `simplicio/plan_compiler/models.py`; the interrupted full pytest run
reached 1,399 passes, 6 skips, and 21 failures, including stale help fixtures and provider/local-inference
expectations introduced before this branch. Issue-focused suites are green.

Historical note: the first evidence pass predated issue #256. The current tree now contains the production
`RuntimeEffectSink`; installed requests still fail closed unless an actual compatible Runtime endpoint and
coordinator-owned context are supplied, and this local run does not claim a live cross-repository receipt.

## Canonical-context regression follow-up (2026-07-22)

Review against the live issue found that negotiation used the retired
`simplicio.mapper.context-snapshot/v1` spelling and trusted the schema field alone, while Mapper's pinned
contract is `simplicio.context-snapshot/v1`. The integrated path could therefore accept a fabricated object
yet reject every real Mapper snapshot. Negotiation and dispatch now both call Mapper's contract adapter;
the profile reports the canonical-payload SHA-256 and stable Mapper rejection code.

Replay evidence against current `main` at `b6e6c29`:

- focused unit/integration/system/regression: 25 passed; 94% branch-aware coverage across
  `execution_mode.py` and `pipeline_integrated.py`;
- system command `simplicio-py runtime capabilities --mode integrated --json` emitted one clean JSON object
  and failed closed as `INCOMPATIBLE_RUNTIME` without a Runtime deployment;
- negotiation benchmark assertion passed at fewer than 100 microseconds per validated-boundary call;
- focused Ruff lint and format checks passed;
- `git diff --check` passed, and generated dependency documentation matched;
- repository-wide Ruff and mypy remain red on pre-existing baseline debt outside the replayed files
  (23 lint errors and five mypy errors). Focused Ruff lint/format passed; focused mypy reached four
  transitive baseline errors in unchanged modules.

## Installed-entrypoint completion follow-up (2026-07-23)

Base SHA: `affce3f`. Branch: `agent/issue-257`. Environment: Python 3.12.13,
Linux x86_64.

Adversarial review of the merged implementation found that `--mode integrated`
was selectable but not executable from the installed `task` entrypoint:
snapshot, attempt, lease, fence, and context handle existed only as Python
arguments. Negotiation also used the reserved runtime-binary probe rather than
the exact HTTP capability response used by `RuntimeEffectSink`.

The follow-up adds:

- CLI/API/environment parity for canonical snapshot and coordinator-owned
  attempt identity;
- one `RuntimeEffectSink.capability_handshake()` reused for selection and
  effect admission;
- strict production-sink type admission instead of class-name inference;
- zero Mapper/Runtime probe for explicit standalone execution;
- complete blocked execution profiles for malformed or partial inputs;
- 16 MiB snapshot input bound and stable errors without local path disclosure;
- updated help fixtures, installed-wheel documentation, and changelog.

Local evidence:

- focused unit/integration/system/regression: 121 passed;
- issue-focused branch coverage: 88.74% total; `execution_mode.py` 95% and
  `runtime_effect_sink.py` 94%;
- repository run: 1,912 passed, 20 skipped, 43 failed at the first pass; the
  two issue-owned task/run help fixture failures were corrected and replayed
  green, while the remaining failures are existing cross-project, removed
  workflow, provider, optional-tool, and baseline-contract debt;
- repository global coverage from that run: 85.92%; the critical-module gate
  remains red in unchanged modules (`mechanical_edit`, `execution_contract`,
  `doctor`) and the pre-existing `pipeline.py` baseline;
- focused Ruff lint/format: passed; repository Ruff remains red with 34
  pre-existing findings outside this diff;
- mypy no longer reports an issue-owned error; five pre-existing errors remain
  in `models.py`, `multi_task.py`, `observability.py`, and `task_operator.py`;
- generated dependency documentation: passed;
- wheel/sdist build and Twine checks: passed, with pre-existing setuptools
  license deprecation warnings;
- clean wheel install: passed; installed `task --help` exposes all coordinator
  fields and an invalid snapshot returns one clean JSON object with
  `INCOMPATIBLE_CONTEXT`;
- negotiation benchmark: 10,000 calls in 0.150458 seconds
  (15.05 microseconds/call).

No live Runtime endpoint was available. Therefore this follow-up does **not**
claim a cross-repository EffectTransaction receipt, E2E/DEFAULT/GATED promotion
receipt, live rollback, or Runtime version/digest. Those values remain
unobserved rather than estimated, and issue #257 must remain open until the
external Runtime evidence exists.

## Integrated feature/sprint routing follow-up (2026-07-24)

The CLI now carries a canonical `ContextPack` path/config/env input alongside
`ContextSnapshot`. When negotiation selects `integrated` for `feature` or
`sprint`, the planner remains read-only and every planned task is dispatched
through `pipeline.run_task(mode="integrated")` with the production sink,
snapshot, pack, runtime handshake, and coordinator attempt. The legacy
codegen/local task runner is not selected on this route. Missing or malformed
snapshot/pack, incompatible Runtime, or incomplete attempt identity still
blocks before planning/effect.

Focused regression validation: 91 passed. Two unrelated repository effect-
boundary baseline assertions remain red (`expected 05dd1f6...`, current
inventory `4dfd242...`); this diff adds no mutation primitive. The passing
tests prove routing and input propagation with test doubles; they do not claim
a live Runtime receipt or close the cross-repository E2E requirement above.
