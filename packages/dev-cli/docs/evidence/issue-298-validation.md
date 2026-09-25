# Issue #298 validation evidence

## Local contract slice

Dev CLI now publishes ownership metadata for `simplicio.plan-dag/v1`, validates
node conflicts, and produces `simplicio.plan-projection/v1` views bound to the
canonical source digest. Projections fail closed for unknown consumers,
identity loss, payload adulterado, transformação não registrada, plano fonte
inválido e unsupported schema major. O payload tem digest próprio e precisa
coincidir com a transformação determinística registrada para o consumidor.

The integrated Runtime boundary carries the canonical `PlanDAG` payload and
`plan_digest` alongside each `EffectTransaction`. The Loop consumer forwards
the causal envelope into transactions and receipts, while Runtime validates
the envelope before effect handlers run. Legacy transactions without the
optional canonical envelope remain compatible.

## Reproduction

```text
python -m pytest -q tests/python/test_plan_contract_conformance.py \
  tests/python/test_plan_contract_benchmark.py \
  tests/python/test_plan_compiler.py \
  tests/python/test_plan_compiler_determinism.py \
  tests/python/test_plan_compiler_n_minus_1_adapter.py
```

Focused tests cover unit, integration, system-level round-trip, regression,
tampering (inclusive com digest de fonte válido), unknown consumer, major
mismatch, source PlanDAG inválido, conflito simétrico, golden digest v1 e
measured benchmark output.

Focused result on Python 3.12.13 após revisão adversarial: `56 passed`.
Coverage for the new conformance
module: `99%` branch-aware. Ruff check and format check pass for every touched
Python file.

```text
python bench/plan_contract_benchmark.py --iterations 1000
# Plan contract benchmark

- iterations: 1000
- nodes: 20
- mean_ms: 0.288002
- p95_ms: 0.313495
- operations_per_second: 3472.202884
```

Measured on the current Linux/Python 3.12.13 worker. Values exclude network,
Loop and Runtime latency and are not an ecosystem performance claim.

## Repository baseline

Full `pytest -q` completed with `1915 passed`, `20 skipped`, and `41 failed`.
No new or changed test failed. Existing failures include stale CLI help and
dependency fixtures, references to deleted GitHub workflows, provider/local
inference expectations, missing optional TypeScript tooling, environment proxy
support and installed-entrypoint PATH assumptions.

Focused mypy found no error in the changed contract code; collection still
reports the existing `simplicio/observability.py:98` dynamic handler attribute
error.

## Cross-repository gate

The consumer implementation is now merged:

- Loop: `d148ed447b5f6b8b287da4835c4e3a6b47eab063` (PR #725), validating the
  installed Dev CLI PlanDAG and carrying plan identity into effect transactions
  and receipts.
- Runtime: `93350743d319175c3461d32764ffc1c9b2475568` (PR #3572), validating
  canonical plan metadata at the effect firewall before handlers run.

Installed-package probe executed in a clean wheel-only venv:

- `simplicio-cli==0.16.2`, `simplicio-loop==3.38.1`, and
  `simplicio-mapper==0.24.2` were installed as packages, not editable
  checkouts.
- The real trace `Goal -> PlanDAG -> Loop admission -> EffectTransaction ->
  Receipt` passed with plan digest
  `b77b56026603ea604272568490e61bfdb5271ed443a87d97fc16abc666a1069d`.
- Replay preserved the digest; unknown major, digest mismatch, dependency
  cycle, and N-1 downgrade/upgrade all failed or round-tripped as expected.
- The exact merged Runtime firewall source was compiled in an isolated Rust
  harness with that same digest: `7 passed`.

The full Runtime binary E2E remains unverified because the private compiled
`simplicio` executable is not installed or published to this worker. The
Runtime source-level firewall gate is verified; this distinction is kept
explicit instead of being reported as a binary PASS.

## Rollback

Revert the implementation commit. Existing PlanDAG fields and transactions
without a dispatch plan remain compatible; consumers that do not use
projections keep their prior behavior.
