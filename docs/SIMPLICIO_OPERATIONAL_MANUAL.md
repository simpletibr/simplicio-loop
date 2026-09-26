# Simplicio operational manual

This manual is the canonical smoke-test artifact for the Simplicio Runtime
integration. It describes the safe local path from task intake to evidence:

1. `simplicio doctor --json` checks the runtime, adapters and local environment.
2. `simplicio contracts smoke --json` verifies the registered schemas and adapter chain.
3. `simplicio-loop` runs the evidence-gated loop; incomplete evidence remains `UNVERIFIED`.
4. `simplicio preflight` (when available) freezes identity, versions and capabilities before writes.

The control plane is fail-closed: a missing model, adapter, receipt, watcher result or
runtime connection blocks mutation instead of reporting a false completion. The local
SQLite queue is suitable for one machine; the HTTP queue adapter is suitable for a
controlled network and must be placed behind TLS and a network policy in production.

Useful checks:

```powershell
simplicio doctor --json
simplicio contracts smoke --json
python scripts/check.py --tests-only
```

See [`REMOTE_QUEUE.md`](REMOTE_QUEUE.md) and
[`delivery-target-receipts.md`](delivery-target-receipts.md) for the detailed
contracts and evidence requirements.
