# Issue #256 — RuntimeEffectSink causal receipt evidence

Date: 2026-07-22 (UTC)  
Checkout baseline: `bf2e293` on branch `work`  
Checkout baseline: `bf2e293` on branches `work` and `codex/implement-github-issue-#256-in-simplicio-dev-cli`
Issue: `wesleysimplicio/simplicio-dev-cli#256` (open when inspected)

## Scope of this patch

The existing RuntimeEffectSink already mapped and persisted EffectTransaction
requests. This patch closes a receipt-verification gap found by an adversarial
acceptance-criteria review: a receipt with a valid digest could replace the
coordinator, session, turn, attempt, subworkflow, plan, or goal identity and
still pass. Receipt verification now requires the complete causal object to be
byte-for-byte equivalent to the submitted transaction. The loopback benchmark
and installed-wheel system probe exercise the same strengthened contract.

## Evidence matrix

| Pillar | Command / scenario | Result |
|---|---|---|
| Unit + contract | `python -m pytest -q tests/python/test_runtime_effect_sink.py tests/python/test_pipeline_integrated_mode.py --cov=simplicio.plan_compiler.runtime_effect_sink --cov=simplicio.pipeline_integrated --cov-branch --cov-report=term-missing --cov-report=json:coverage-issue-256.json` | PASS: 44 tests; 91.22% combined branch coverage; RuntimeEffectSink 93% |
| Integration | Same focused suite: mapping → fake public transport → verified receipt → atomic journal | PASS |
| Fault/security regression | `test_forged_causal_identity_is_rejected` mutates each of 8 causal fields and recomputes a valid receipt digest | PASS: every forged identity fails with `RECEIPT_CORRELATION_MISMATCH: causal` |
| System / clean install | Build wheel, install it with dependencies in `/tmp/issue-256-venv`, submit a forged-coordinator receipt through the installed package | PASS: `clean-wheel forged coordinator rejected: RECEIPT_CORRELATION_MISMATCH` |
| Performance | `python bench/runtime_effect_sink_benchmark.py` (500 unique transactions) | PASS: median 0.6251 ms; p95 0.8112 ms; 1533.40 transactions/s |
| Generated docs | `python3 scripts/gen_package_interdependence.py --check` | PASS |
| Focused lint/format | `ruff check simplicio/plan_compiler/runtime_effect_sink.py tests/python/test_runtime_effect_sink.py` and matching `ruff format --check` | PASS |
| Full regression | `pytest -q` | BASELINE RED: 1907 passed, 17 skipped, 26 failed; failures are outside this slice (help snapshots, stale mapper pins, provider/local-inference expectations, meta-audit references, and task-progress guards) |
| Full lint/format | `ruff check .`; `ruff format --check .` | BASELINE RED: 23 lint findings and 27 files with format drift, none in this patch's focused Python files |
| Type check | `mypy simplicio/plan_compiler/runtime_effect_sink.py` | BASELINE RED: 3 imported-module errors in `plan_compiler/models.py` and `observability.py`; no error reported in the changed module |

## Adversarial verification

- Happy path: an unchanged causal object is accepted and produces a typed
  `completed` outcome plus durable intent, receipt, and outcome files.
- Edge: all coordinator-independent causal fields are preserved, including
  numeric `attempt`.
- Error path: changing any causal field while recomputing a valid receipt digest
  is rejected before a receipt or successful outcome is persisted.
- Regression: the performance loopback transport was updated to emit the
  production receipt shape, preventing benchmarks from bypassing verification.

## External blocker / honest completion state

The Codex Cloud checkout has no Git remote configured and no `gh` executable.
More importantly, no live public deployment of the Runtime EffectTransaction/v1
service or its official fixtures/SHAs was provided. Therefore this patch proves
the Dev CLI boundary, clean-wheel behavior, and fault injection, but **does not
prove** the issue's required live PlanDAG → Runtime Gate → mutation → validation
→ rollback receipt trace, coordinator parity against Agent and non-Agent
processes, or a real stale-source pre-mutation block. Issue #256 must remain open
until those cross-repository receipts exist and the change is merged.
