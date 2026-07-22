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

External blocker: issue #256 is still open, so there is no production `RuntimeEffectSink` to dispatch an
EffectTransaction. This change deliberately does not fabricate one or promote integrated to default.
Installed integrated requests fail closed, while the versioned negotiation, surfaces, rollout controls,
profiles, metrics, and canonical-context requirement are ready for that dependency.
