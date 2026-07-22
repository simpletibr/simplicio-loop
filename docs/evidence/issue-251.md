# Issue #251 — CI coverage gate evidence

Date: 2026-07-22 (UTC)  
Base commit: `bf2e2937b3f2c511a703bfef49d78ac893b9ee15`  
Branch: `work`  
Environment: Python 3.12.13, pytest 9.0.3, ruff 0.15.12, mypy 1.20.2

## Acceptance-criteria trace

- The blocking workflow is `.github/workflows/ci.yml`. It runs on pushes and
  pull requests to `main`, produces `coverage.json`, invokes the real
  `scripts/coverage_gate.py`, and has no non-blocking override.
- The workflow name and documentation state 85% global / 90% critical. The
  enforced values come from `pyproject.toml`; the repository self-check reads
  that configuration and compares it to `docs/ci-quality-gate.md`.
- The self-check now audits active root documentation, operational docs, tests,
  and both bootstrap implementations. Historical evidence and changelog entries
  remain immutable descriptions of earlier repository states rather than active
  workflow references.
- Stale active references to `dod.yml` and fictional deployment workflows were
  removed or replaced with the existing `ci.yml` path.

## Executed evidence

### Focused unit, integration, system, and regression checks

```text
$ bash -n bootstrap.sh
exit 0

$ pytest -q tests/python/test_local_quality_gate.py
6 passed in 0.15s

$ python3 scripts/coverage_gate.py --self-test
SELF-TEST OK: coverage_gate.py correctly accepts/rejects synthetic reports

$ python3 scripts/coverage_gate.py --report /tmp/issue-251/missing.json
::error::coverage report not found ...
exit 1 (expected failure; the missing required artifact cannot become success)
```

The focused pytest module exercises the workflow trigger and command contract
(system), configured-to-documented threshold contract (integration), rejecting
threshold-boundary fixtures (unit/failure), active-reference audit (regression),
and cross-platform hook contract. `bash -n` exercises the modified POSIX
bootstrap as a real shell parser. PowerShell syntax execution is not available
because `pwsh` is absent from the checkout image; its path is still covered by
the reference-audit test.

### Performance

One hundred fresh-process executions of the synthetic gate self-check:

```text
runs=100 mean_ms=155.124 median_ms=151.130 max_ms=195.736
```

This change is documentation/test scanning rather than a runtime hot path; the
measurement is recorded as a reproducible smoke benchmark, not a release claim.

### Full regression and coverage

```text
$ pytest --cov=simplicio --cov-report=term-missing --cov-report=json:coverage.json
26 failed, 1899 passed, 17 skipped in 498.17s
TOTAL 14738 statements, 1671 missed, 85.95%
```

The issue-specific tests passed within that run. The checkout has unrelated
pre-existing failures in CLI snapshots, component-version expectations,
provider behavior, and other modules. The generated report clears the 85%
global floor, but the real critical-module gate correctly remains red:

```text
pipeline.py 86.99%; mechanical_edit.py 71.17%;
execution_contract.py 87.99%; doctor.py 72.36%
Coverage gate FAILED (required critical modules >= 90%).
```

This is concrete proof that failure does not become success. It also means the
restored workflow will block until the existing critical coverage debt is
fixed; no threshold or module list was weakened in this change.

### Static gates

Focused checks are green:

```text
$ ruff check tests/python/test_local_quality_gate.py
All checks passed!
$ ruff format --check tests/python/test_local_quality_gate.py
1 file already formatted
$ git diff --check
exit 0
```

Repository-wide `ruff check .`, `ruff format --check .`, and `mypy simplicio`
remain red on pre-existing files outside this patch (23 lint errors, 28 files
requiring formatting, and 6 type errors in 5 product files). These failures are
preserved rather than hidden by unrelated edits.

## Receipts, security, rollback, and limitations

SHA-256 receipts before commit:

```text
733af035636bdfeb04d46cec27628058440199c5bcd07a048918d9ed60d594e7  .github/workflows/ci.yml
50cf5f832f12c8be937e4a2c9c6dbc5b608e40b932ce09f704cec5692269275b  tests/python/test_local_quality_gate.py
f01033bb3455cf73588f794e0c16c8e575f186cd3c68b76da3742e9f94687200  bootstrap.sh
dcd3289c9340a6f012f16b960fbfa8b784eed34fd5aa068fd58e8bd50a0172c1  bootstrap.ps1
```

No credentials, PII, provider payloads, or private data are present. Retry,
timeout, cancellation, worktree mutation, snapshot/export, and transactional
rollback are not states supported by this static CI-reference audit. Rollback
is `git revert` of the resulting commit; it restores only documentation,
bootstrap allowlists, and the repository self-check.

Publication to `simplicio-loop#582` is externally blocked in this environment:
the `gh` executable is absent, no Git remote is configured, and no GitHub token
is exposed. This evidence file is therefore the portable report to attach to
that audit; the issue must not be closed before merge.
