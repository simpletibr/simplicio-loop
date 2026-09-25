# Issue #98 — default-branch migration validation

Date: 2026-07-22 (UTC)

## Result

The executable verifier was strengthened to reject a migration when the
retained compatibility branch has diverged from `main`. The live check remains
**blocked**, not complete: GitHub reports `default_branch=master`, and the
public branch tips have diverged. The exact machine-readable observation is in
`issue-98-default-branch-receipt.json`.

The checkout exposes no Git remote, `gh` is not installed, and no GitHub token
is present in the environment. Consequently this session cannot change the
repository setting, synchronize the remote compatibility branch, push this
commit, or create the required PR. No issue-close operation was attempted.

## Acceptance evidence

| Check | Evidence |
|---|---|
| Desired default | `main` |
| Live observed default | `master` |
| Live `main` tip | `bf2e2937b3f2c511a703bfef49d78ac893b9ee15` |
| Live `master` tip | `89df79f310661db55b7c3234338789d760ce1a76` |
| Remote comparison | `diverged`; `main` is 7 commits ahead and 4 behind `master` |
| Compatibility invariant | Failed: branch tips differ |
| Publication capability | Blocked: no remote, `gh`, or credential |

## Executed checks

- Unit/integration/regression: `python -m pytest tests/python/test_verify_default_branch.py -q`
  — 11 passed.
- System and error path: `python scripts/verify_default_branch.py`
  — exit 1, correctly fail-closed with the live receipt.
- Focused coverage: `python -m pytest tests/python/test_verify_default_branch.py
  --cov=scripts.verify_default_branch --cov-branch --cov-report=term-missing
  --cov-report=json:docs/evidence/issue-98-coverage.json` — 11 passed,
  97.06% branch-aware coverage.
- Performance: seven samples of 10,000 in-memory verifications; best observed
  5.007 microseconds per verification. Raw samples are in
  `issue-98-benchmark.txt`.
- Focused lint/format: Ruff passed for the implementation and test.
- Generated dependency documentation: check passed.
- Full repository gates are not green on this checkout: `ruff check .` reports
  23 pre-existing findings, `ruff format --check .` reports 27 pre-existing
  files, `mypy simplicio` reports 6 pre-existing errors, and `pytest -q` stops
  during collection with 119 errors because the declared `simplicio_mapper`
  package is not installed.

## Required external actions

1. Reconcile `main` and compatibility `master` without adding independent
   commits to `master`.
2. Change GitHub **Settings → Branches → Default branch** to `main` using an
   authenticated administrative surface.
3. Run `python3 scripts/verify_default_branch.py`; require exit 0 and archive
   its receipt.
4. Verify a fresh clone selects `main`, and create/merge the implementation PR
   with base `main`.
5. Keep issue #98 open until the merged state is re-queried and verified.
