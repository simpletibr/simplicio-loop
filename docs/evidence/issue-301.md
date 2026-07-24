# Issue #301 — standalone write migration evidence

Base SHA: `affce3f`. Branch: `agent/issue-301`. Date: 2026-07-23.

## Local slice

This change implements only locally verifiable migration controls:

- governed `shadow`, `opt_in`, `warning`, `read_only`, and `removed` phases;
- compatibility-preserving `shadow` default;
- explicit legacy-write opt-in in the migration window;
- fail-closed invalid phases and `effect_unknown`;
- aggregate-safe route telemetry for task, feature, sprint, and edit;
- additive receipt classification that cannot claim Runtime gating for
  Python local writes;
- an AST inventory guard against new mutation primitives outside the
  production `RuntimeEffectSink`;
- a version/date roadmap and rollback rules.
- an offline `EffectTransaction/v1` executor with durable receipts, authorized
  artifact application, and idempotent reconciliation after a lost response;
- explicit `artifact_ref` propagation from a decided TaskSpec into the
  effect-boundary transaction.

The current-main mutation inventory is 190 symbolic scopes and 248
candidate calls, SHA-256
`4a0fc6cfe9b1cdbc4ee497338b9781ea713d3e4d433df6b1945f51d17f78065f`.
The baseline was refreshed after the subsequent merged contract slices; no
new product mutation boundary was added by this refresh.
The reviewed additions are the reconciliation lock write and verified clear;
existing legacy writes remain inventoried.

## Acceptance matrix

| Acceptance criterion | Local result |
|---|---|
| Roadmap with versions and dates | Implemented in `docs/features/standalone-migration.md`; future dates are explicitly targets. |
| Auto does not silently choose standalone writes | Partial: telemetry is active in compatibility `shadow`; `opt_in` and later fail closed without explicit authorization. Default promotion is blocked on adoption evidence. |
| Every default mutation traverses Effect API | Blocked: `shadow` intentionally preserves existing installations. |
| Offline uses the same contract | Implemented locally by `OfflineRuntimeTransport`; it accepts only an authorized repository-local mechanical-edit artifact and emits a verified `simplicio.effect-receipt/v1` receipt. |
| `effect_unknown` never causes a second write | Locally enforced across invocations by a persistent reconciliation lock and the one-dispatch atomic boundary; live Runtime reconciliation remains external. |
| Receipts distinguish legacy/integrated | Implemented additively for task patch and edit results. |
| Guard blocks new writes outside boundary | Implemented with deterministic AST inventory and baseline test. |
| Upgrade/downgrade and rollback exercised | Phase rollback is covered locally; package-level clean upgrade/downgrade remains pending built-release artifacts. |
| Final removal preserves supported scenarios | Blocked pending offline executor, adoption gates, and a recorded compatibility decision. |

## Evidence commands

No external receipt is inferred. Local results:

- focused unit/integration/system/regression suite: 86 passed;
- new policy and guard branch coverage: 98% combined;
- full repository suite: 1,926 passed, 19 skipped, 41 pre-existing failures
  in help fixtures, dependency expectations, removed workflows, optional
  tools, provider/local-inference drift, and missing real CLI executables;
- focused Ruff lint/format: passed; repository Ruff remains red with 34
  pre-existing findings and format drift outside this slice;
- mypy reports five pre-existing errors in `models.py`, `multi_task.py`,
  `observability.py`, and `task_operator.py`, with no issue-owned error;
- effect-boundary inventory guard and generated dependency documentation:
  passed;
- wheel/sdist build and Twine checks: passed with existing setuptools license
  deprecation warnings;
- clean wheel install: passed; the installed `mechanical-edit --apply`
  blocked without opt-in and left the product file absent;
- installed opt-in compatibility path wrote once and returned a legacy,
  non-Runtime-gated receipt; invalid phase failed closed as `read_only`;
- offline EffectTransaction path applied one authorized artifact, persisted a
  receipt, and reconciled an injected post-apply response loss without a
  second mutation;
- additive `runtime_effect_api` route markers deliberately keep
  `runtime_gated=false`; no local marker substitutes for a causal Runtime
  receipt;
- `effect_unknown` remained blocked even with legacy opt-in;
- benchmark: 100,000 policy resolutions in 0.190342 seconds
  (1.90 microseconds/call); five full AST scans averaged 268.17 ms.

An independent adversarial review identified five release-critical gaps:
cross-process `effect_unknown` persistence, partial native multi-file writes,
empty migration phases failing open, blocked read-only task previews, and
AST alias bypasses. Each finding was corrected and covered by the focused
suite before this evidence was finalized.

Commands:

```text
pytest -q tests/python/test_standalone_migration.py ...
pytest --cov-branch ... --cov-fail-under=85
python scripts/check_effect_boundary.py
python -m build && python -m twine check dist/*
```

## External blockers

No live compatible Runtime deployment was available. The local offline
executor is measured, but this evidence does not claim real rollout adoption
telemetry, cross-repository fault injection, clean upgrade/downgrade between
published versions, or final removal readiness. The Loop checkout is
available for contract inspection, but no installed Loop → Runtime → Dev CLI
production receipt was produced in this worker. Issue #301 remains open for
those external receipts.
