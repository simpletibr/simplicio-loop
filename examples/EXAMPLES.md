# Simplicio Runtime examples

These examples are intentionally model-free and safe to run as read-only smoke
checks. They exercise the same artifact path used by the Runtime compatibility gate.

## Doctor and contract smoke

```powershell
simplicio doctor --json
simplicio contracts smoke --json
```

## Local evidence loop

```powershell
python scripts/check.py --tests-only
python scripts/claims_audit.py --json
python scripts/mirror_parity.py check
```

The commands above must report their measured result. A missing local model or
external service is reported as `UNVERIFIED`/`BLOCKED`; it is never replaced with a
simulated success.

## Shared queue smoke

```powershell
$env:SIMPLICIO_QUEUE_TOKEN = "development-only-token"
python scripts/remote_queue_server.py --db .simplicio-loop/orchestrator/shared-queue.db --port 8765 --token $env:SIMPLICIO_QUEUE_TOKEN
```

Use `HTTPRemoteQueue` from `simplicio_loop.remote_queue` for authenticated claims,
leases, fencing and ordered event reconciliation. For production, terminate TLS at
the network boundary and keep the token outside source control.
