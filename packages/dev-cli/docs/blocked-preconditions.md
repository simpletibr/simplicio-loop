# Structured blocked-precondition receipts

`simplicio-py task --dry-run-task --json` is fail-closed when required preconditions are missing. It exits non-zero and emits exactly one `simplicio.dev-cli.task-result/v1` JSON object on stdout. Human diagnostics remain on stderr.

A blocked task result always includes `status: "blocked"`, `applied: false`, `model_invoked`, `next_surface`, `reason_code`, `execution_profile`, and `blocked_preconditions`. Each precondition uses the deterministic `simplicio.dev-cli.blocked-precondition/v1` shape:

```json
{
  "schema": "simplicio.dev-cli.blocked-precondition/v1",
  "code": "artifacts_missing",
  "reason": "artifacts_missing",
  "message": "mapper artifacts required for dry-run task are missing",
  "next_surface": "mapper_artifacts",
  "next_action": "generate fresh Mapper artifacts, then retry",
  "retryable": true,
  "details": {"missing": ["project_map", "precedent_index"]}
}
```

Route `mapper_artifacts` to Mapper generation, `mapper_inspection` to stale-artifact inspection, `context_pack` to a fresh handoff/context pack, and `task_target` to target selection. Provider and execution-mode blocks name those surfaces directly. Treat unknown reasons as blocked and preserve the complete receipt for evidence.

```bash
simplicio-py task "implement the change" --stack python --target src/module.py --dry-run-task --json > receipt.json
```

The JSON schema is additive. Consumers must preserve unknown top-level fields, retain every `blocked_preconditions` entry, and use `reason`/`code` plus `next_surface` instead of parsing human messages. Diagnostics such as `BLOCKED[artifacts_missing]: ...; next_surface=mapper_artifacts` are stderr-only and never corrupt stdout JSON.
