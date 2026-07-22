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
