# Issue #299 — typed TaskSpec handoff

## Objective

Replace the integrated pipeline's reconstruction of a minimal `TaskSpec` from
`goal`, `criteria`, and `constraints` with a typed, versioned handoff that
preserves the intake contract through plan compilation.

## Implemented boundary

- `TaskSpec.from_dict()` validates `simplicio.task-spec/v2`, required causal
  identity, a lowercase SHA-256 source hash, and unique non-empty acceptance
  criterion IDs.
- Unknown additive v2 fields are retained in an internal `extra_fields` map
  and emitted again, but reserved
  schema/identity names cannot collide with canonical fields.
- `TaskSpec.canonical_hash()` gives producers and consumers a deterministic
  handoff digest.
- `simplicio-py task --task-spec PATH` and `--task-spec-stdin` import either a
  single task object or a one-task document.
- `pipeline.run_task(..., task_spec=...)` passes the original object into the
  integrated compiler. The standalone path rejects typed input instead of
  silently flattening or ignoring it.
- `pipeline.run_task_spec(...)` is the public typed API; it derives only the
  legacy positional fields while preserving the original TaskSpec object and
  can derive the declared verification command without a global env override.
- Legacy string arguments remain supported and continue through the existing
  compatibility bridge.

## Acceptance evidence

The focused suite covers:

1. stable round-trip and hash behavior, including an unknown additive field;
2. incompatible schema, malformed source hash, empty criteria, and duplicate
   criteria fail-closed behavior;
3. object identity and complete payload preservation at the compiler boundary;
4. typed-input rejection by standalone execution;
5. file-based CLI import and the existing task/help/pipeline regressions.
6. malformed known containers/items, invalid verifier commands, non-finite
   numbers and future additive `tasks` metadata fail or round-trip
   deterministically without tracebacks or document misclassification.

Run:

```text
PYTHONPATH=$PWD /tmp/simplicio-dev-cli-venv/bin/pytest -q \
  tests/python/test_typed_task_spec_handoff.py \
  tests/python/test_task_spec.py \
  tests/python/test_pipeline_integrated_mode.py \
  tests/python/test_commands_direct_namespace.py \
  tests/python/test_cli_help_snapshot.py
```

Initial focused result: `63 passed`; after adversarial review and hardening,
the rebased affected suite reached `118 passed`. All executable lines and branch destinations
introduced in `TaskSpec.from_dict()`, `TaskSpecDocument.from_dict()` and
`canonical_hash()` were covered.

Repository-wide result: `1917 passed`, `20 skipped`, `41 failed`. The same
baseline families already recorded by adjacent slices remain red: stale help
and dependency fixtures, intentionally removed workflow references, optional
proxy/TypeScript tools, provider-policy expectations and missing installed
entrypoints. No changed or newly added test failed.

`mypy simplicio` still reports five pre-existing source-module errors plus no
error in this slice after the typed `Path` adapter correction.

## Rollback

Remove the two CLI flags and the optional `task_spec` arguments. The legacy
string bridge remains isolated in `_build_task_spec()` and can continue to
serve older callers.

## Cross-repository status

This repository now supplies and consumes the typed boundary. End-to-end
proof that `simplicio-loop` sends its original intake object requires a
correlated change and trace in that repository; this document does not claim
that external evidence.
