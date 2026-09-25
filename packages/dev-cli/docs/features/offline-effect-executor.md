# Offline EffectTransaction executor

Issue #301 keeps offline work available without restoring a silent standalone
write path. Set `SIMPLICIO_RUNTIME_OFFLINE=1` to select the local
`OfflineRuntimeTransport`. It speaks the same
`simplicio.effect-transaction/v1` and `simplicio.effect-receipt/v1` contracts
as the HTTP Runtime sink.

The local executor accepts only an authorized transaction with an
`effect.artifact_ref` that points to a repository-local
`simplicio.mechanical-edit/v1` plan. The plan is applied inside the Effect
boundary, and the receipt is persisted below
`.simplicio/runtime-effects/`. A missing, malformed, or escaping artifact is
denied; it never falls back to the legacy standalone writer.

For a raw task entrypoint, provide the decided artifact explicitly:

```bash
SIMPLICIO_RUNTIME_OFFLINE=1 \
SIMPLICIO_EXECUTION_ROLLOUT=default \
SIMPLICIO_EFFECT_ARTIFACT_REF=.simplicio/effects/issue-301.json \
simplicio-dev-cli task "apply the decided change" --target src/app.py \
  --mode integrated --json
```

The local transport uses the transaction idempotency key as its durable
identity. If a response is lost after applying an effect, a later submission
reconciles the persisted receipt and does not apply the artifact again.
`effect_unknown` remains a reconciliation state and still creates the normal
cross-invocation lock; it is never converted into a standalone retry.

This is an offline executor receipt, not proof of a live Runtime deployment.
Online Runtime/Loop adoption and published-package upgrade/downgrade receipts
must still be measured by the cross-repository harness.

## Local E2E matrix

Run the issue-specific offline matrix with the repository's test environment:

```bash
pytest -q tests/python/test_issue_301_e2e.py
```

The matrix uses a loopback HTTP Runtime and the production offline transport;
it covers Runtime absent/present/incompatible, all migration phases, kill
switch and `effect_unknown` locking, task/feature/sprint/edit routing,
authorization, receipts, idempotency, response-loss reconciliation, rollback,
and isolated source-install contract smoke. It does not claim a published
wheel upgrade/downgrade or a live Loop → Runtime → Dev CLI receipt.
