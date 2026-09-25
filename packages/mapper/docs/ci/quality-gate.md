# CI Quality Gate (issue #222)

`.github/workflows/quality-gate.yml` runs one job, **`Quality Gate`**, on
every pull request into `main`/`develop` and on push to `main`. It exists to
block merges that regress mapper precision, contract compatibility, golden
output, or performance — the four things a mapper consumer silently breaks
on without this gate.

## What it checks

| Acceptance criterion (issue #222) | Enforced by |
| --- | --- |
| Unexpected golden-file change fails the PR | `scripts/toon_contract_runner.py` (round-trips every `fixtures/toon-golden/valid/*` case and requires the fresh `encode()` output to match the committed `expected.toon` byte-for-byte) + a `git status --porcelain` check on `fixtures/toon-golden/` and `contracts/` so any local `--update` run left uncommitted is caught |
| Incompatible schema fails the PR | `scripts/regen_contract_fixtures.py check` (mapper-artifacts contract, issue #157) and `simplicio-mapper doctor --contracts` (cross-repo ecosystem contracts, issue #164) |
| Regression above the documented limit is flagged | `scripts/critical_coverage_gate.py` (coverage floors) and `scripts/perf_regression_gate.py` (precision/latency/size/throughput floors), both below |
| Reports/diffs attached to the workflow | `actions/upload-artifact@v4` step uploads every report + `fixture-diff.patch` as `quality-gate-reports`, `if: always()` so it uploads on failure too |
| Main branch requires all checks green | See [Branch protection](#branch-protection-manual-step) below |

## Coverage gate

`scripts/critical_coverage_gate.py` reads `coverage.json` (from
`pytest --cov-report=json:coverage.json`) and fails if:

- **global** line coverage is below **85%**, or
- the average line coverage across the critical-path module set below is
  below **90%**:

  `simplicio_mapper/{toon,contract,ecosystem_contract,retrieval_index,query,drift,context_cache,incremental}.py`

  (chosen because these back TOON round-tripping, contract validation,
  retrieval ranking, drift/query correctness, and incremental caching — the
  modules a silent bug in would show up as a precision or contract
  regression, not a crash).

Adjust the module list or floors with `--global-min` / `--critical-min` if
the acceptance bar changes; don't silently lower them without updating this
doc.

## Precision / performance regression gate

`scripts/perf_regression_gate.py` re-runs the existing measurement
harnesses fresh and diffs the result against the **committed baselines**:

- `docs/evidence/behavioral-scorecard.json` (from
  `scripts/evaluation_scorecard.py`) — precision/recall/task-success metrics
  (0..1 scale), latency, and artifact/context-pack/token size.
- `docs/evidence/runtime-scale-benchmark.json` (from
  `scripts/runtime_scale_benchmark.py`) — indexed-vs-legacy retrieval
  throughput on a synthetic ~5000-file tree.

Documented tolerances (the single source of truth — change here, not just
in code, if the acceptable regression margin changes):

| Metric class | Tolerance | Rationale |
| --- | --- | --- |
| precision/recall/success (0..1) | fail if it drops more than **0.02** (2 points) below baseline | these are expected to sit at/near 1.0 on the deterministic corpus; any drop is a real behavior change |
| latency (ms) | fail if it increases more than **25%** vs baseline | absolute wall-clock varies by machine; a relative jump this large indicates an algorithmic regression, not noise |
| artifact/context-pack/token size (bytes) | fail if it increases more than **20%** vs baseline | guards against silent output bloat that would blow context budgets downstream |
| indexed-vs-legacy speedup ratio | fail if it drops more than **20%** vs baseline | measured on relative throughput, not absolute ms, specifically because absolute timing is not comparable across CI runners with different hardware |

To re-baseline after an intentional, reviewed change:

```bash
python scripts/evaluation_scorecard.py --write-json
python scripts/runtime_scale_benchmark.py --write-json
git add docs/evidence/behavioral-scorecard.json docs/evidence/runtime-scale-benchmark.json
```

and call that out explicitly in the PR description — a re-baseline commit
should never be silent.

## Workflow self-check

`python scripts/check_workflow_references.py` runs in CI before tests. It
fails closed when the workflow or either coverage gate file is missing, or
when the workflow no longer references the declared 85% global and 90%
critical thresholds.

## Workflow self-check

`python scripts/check_workflow_references.py` runs in CI before tests. It
fails closed when the workflow or either coverage gate file is missing, or
when the workflow no longer references the declared 85% global and 90%
critical thresholds.

## Branch protection (manual step)

This repo's branch protection for `main` currently has no required status
checks configured (verified via
`gh api repos/wesleysimplicio/simplicio-mapper/branches/main/protection`).
Modifying branch protection is an access-control change this automation
deliberately does not make on its own; a repo admin should add, under
**Settings → Branches → Branch protection rules → main → Require status
checks to pass before merging**:

- `Quality Gate` (this workflow)
- the existing `pytest (Python ...)` / `cargo test (PyO3 crate)` checks from
  `python-ci.yml`, if not already required

so `main` cannot receive a merge with a red Quality Gate.
