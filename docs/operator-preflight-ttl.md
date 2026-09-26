# Operator preflight TTL

`scripts/operator_preflight.py` separates operator availability from network
upgrades. A successful check is cached for seven days by default in
`~/.simplicio-loop/operator-check.json`; inside that TTL, no upgrade is allowed.

Each run records its observed versions in
`.simplicio-loop/orchestrator/loop/operator-pin.json`. A later iteration that observes a
different version emits a warning and never upgrades silently. Missing or
expired checks emit `refresh_required`, leaving the actual package upgrade to
the explicit preflight command.

```powershell
python scripts/operator_preflight.py --run-id run-123 --record
python scripts/operator_preflight.py --run-id run-123
```
