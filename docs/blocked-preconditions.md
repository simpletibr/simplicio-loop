# Structured blocked-precondition receipts

`simplicio-py task --dry-run-task --json` is fail-closed when required preconditions are missing. It exits non-zero and emits JSON with `status: blocked`, `applied: false`, and `blocked_preconditions`. Each entry contains stable `reason`, actionable `next_surface`, and a human-readable `message`.

```json
{"status":"blocked","applied":false,"blocked_preconditions":[{"reason":"artifacts_missing","next_surface":"mapper_artifacts","message":"mapper artifacts are required before task generation"}]}
```

Route `mapper_artifacts` to the mapper, `mapper_inspection` to inspect or await its job, and `context_pack` to provide missing handoff context. Dry-run never applies a patch or runs tests. Treat unknown reasons as blocked and preserve the complete receipt for evidence.

```bash
simplicio-py task "implement the change" --stack python --target src/module.py --dry-run-task --json > receipt.json
```

The schema is additive; preserve `blocked_preconditions`, `warnings`, and `next_surface` for operators.
