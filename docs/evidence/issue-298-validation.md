# Issue #298 validation evidence

## Local contract slice

Dev CLI now publishes ownership metadata for `simplicio.plan-dag/v1`, validates
node conflicts, and produces `simplicio.plan-projection/v1` views bound to the
canonical source digest. Projections fail closed for unknown consumers,
identity loss, payload adulterado, transformação não registrada, plano fonte
inválido e unsupported schema major. O payload tem digest próprio e precisa
coincidir com a transformação determinística registrada para o consumidor.

The integrated Runtime boundary now carries the canonical `PlanDAG` payload and
`plan_digest` alongside each `EffectTransaction`. The digest is part of the
transaction idempotency key, and a mismatched or structurally invalid plan is
rejected before transport. This is an additive Dev CLI boundary proof; it does
not claim that the currently deployed Loop/Runtime consumes or echoes these
fields.

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

Issue closure still requires Loop and Runtime to consume this schema and pass
the same fixtures using installed packages. This repository cannot claim that
cross-repository E2E until linked changes land and raw traces identify all
three versions and digests.

## Rollback

Revert the implementation commit. Existing PlanDAG fields and transactions
without a dispatch plan remain compatible; consumers that do not use
projections keep their prior behavior.
