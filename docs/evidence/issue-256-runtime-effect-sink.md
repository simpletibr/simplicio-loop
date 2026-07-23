# Issue #256 — RuntimeEffectSink causal receipt evidence

Date: 2026-07-23 (America/Sao_Paulo)
Checkout baseline: `affce3f` on branch `agent/issue-256`
Issue: `wesleysimplicio/simplicio-dev-cli#256` (open when inspected)

## Scope of this patch

The existing RuntimeEffectSink already mapped requests and verified complete
causal receipt identity. This follow-up closes the remaining post-admission
state gap: malformed, forged, or sensitive receipts previously raised before
persisting a typed outcome. They now fail closed as durable `effect_unknown`
without persisting the untrusted receipt. Capability transport failures before
admission are distinguished as `not_started`; the atomic executor no longer
reports that state as a submitted effect.

## Evidence matrix

| Pillar | Command / scenario | Result |
|---|---|---|
| Unit + contract | `/tmp/wt257-venv/bin/python -m pytest -q tests/python/test_runtime_effect_sink.py tests/python/test_atomic_execution.py tests/python/test_pipeline_integrated_mode.py --cov=simplicio.plan_compiler.runtime_effect_sink --cov=simplicio.atomic_execution --cov=simplicio.pipeline_integrated --cov-branch --cov-report=term-missing --cov-report=json:/tmp/coverage-issue-256.json` | PASS: 63 tests; 93.01% combined branch coverage; RuntimeEffectSink 93%; atomic executor 96% |
| Integration | Same focused suite: mapping → fake public transport → verified receipt → atomic journal | PASS |
| Fault/security regression | `test_forged_causal_identity_is_rejected`, `test_invalid_receipt_is_durable_unknown_without_unsafe_receipt`, and `test_reconcile_invalid_receipt_is_durable_unknown` | PASS: forged identities become durable `effect_unknown`; rejected receipts and their sensitive payloads are absent from receipt/outcome/event storage |
| System / clean install | `pip wheel . --no-deps`; install wheel plus declared dependencies into a fresh `--target` directory; run probe from `/tmp` against installed package | PASS: wheel SHA-256 `53afe69f2c63f7ec6e803112fad4e057c5e87b3eabcd8a8cc92b5b6ba11db99d`; `installed-wheel receipt rejection: PASS` |
| Performance | `/tmp/wt257-venv/bin/python bench/runtime_effect_sink_benchmark.py` (500 unique transactions) | PASS: median 0.2176 ms; p95 0.3307 ms; 4187.37 transactions/s |
| Generated docs | `python3 scripts/gen_package_interdependence.py --check` | PASS |
| Focused lint/format | `/tmp/wt257-venv/bin/ruff check` and `ruff format --check` on all five changed Python files | PASS |
| Full regression | `/tmp/wt257-venv/bin/python -m pytest -q` | BASELINE RED: 1910 passed, 20 skipped, 41 failed; failures are outside this slice (help snapshots, removed workflow expectations, stale mapper pins, optional extras, provider/local-inference expectations, missing CLI executables, scratch TypeScript dependency, and task-progress guards) |
| Full lint/format | `/tmp/wt257-venv/bin/ruff check .`; `/tmp/wt257-venv/bin/ruff format --check .` | BASELINE RED: 34 lint findings and 32 files with format drift, none in this patch's focused Python files |
| Type check | `/tmp/wt257-venv/bin/mypy simplicio/plan_compiler/runtime_effect_sink.py simplicio/atomic_execution.py` | BASELINE RED: 3 imported-module errors in `plan_compiler/models.py` and `observability.py`; no error reported in either changed module |

## Adversarial verification

- Happy path: a valid receipt produces typed `completed` plus durable intent,
  verified receipt, outcome, and redacted event evidence.
- Edge: capability transport failure before admission produces durable
  `not_started` and zero submit calls.
- Error path: forged causal identity, invalid digest, malformed schema, unsafe
  sensitive field, non-object receipt, reconcile-time forgery, or
  restart-time capability outage produces durable `effect_unknown`; no
  unverified receipt is persisted.
- Regression: atomic execution maps `not_started` to retryable failure instead
  of claiming `effect_submitted`.

## External blocker / honest completion state

The checkout has a Git remote but no `gh` executable. More importantly, no live
public deployment of the Runtime EffectTransaction/v1 service or official
fixtures/SHAs was supplied. Therefore this patch proves the Dev CLI boundary,
state classification, durable safe outcomes, installed-wheel behavior, and
local fault injection, but **does not prove** the required live PlanDAG →
Runtime Gate → mutation → validation → rollback receipt trace,
public-transport parity, coordinator parity against Agent and non-Agent
processes, or a real stale-source pre-mutation block. Issue #256 must remain
open until those cross-repository receipts exist.
