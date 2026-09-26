# ADR 0010: Super-detailed execution metrics report is standard

- **Status:** Accepted
- **Date:** 2026-08-04
- **Mirrors:** `simplicio-runtime` ADR-2026-08-05
- **Schema:** `simplicio.execution-report/v1`

## Context

Drain waves and single-issue runs need comparable, honest metrics: speed,
latency, CPU, RAM, tokens in/out, per task/issue and consolidated. Partial
savings events alone are not enough.

## Decision

1. **Every** loop/runtime execution emits `simplicio.execution-report/v1`.
2. **Per-task rows** + **consolidated** rollup are both required.
3. Minimum metric classes: identity, timing (`wall_ms`, phase latency, speed),
   resources (CPU/RAM when MEASURED), tokens (in/out/cached/reasoning only from
   usage receipts), operators used, loop decision, measured vs unverified fields.
4. Canonical paths (Runtime profile):
   - `.simplicio-loop/runtime/execution-reports/<run_id>.json`
   - `.simplicio-loop/runtime/execution-reports/latest.json`
   - `index.jsonl` append-only
5. Operator-standalone runs use the same schema with
   `execution_profile: "operator-standalone"` via
   `simplicio_loop/execution_report.py`.
6. **Never invent** CPU/RAM/token numbers. Prefer `null` +
   `unavailable_reasons` / `UNVERIFIED|…`.

## CLI

```text
# Runtime (preferred)
simplicio execution-report start|record-task|finish|show|consolidate --json

# Loop package (operator-standalone / dual path)
python -m simplicio_loop.execution_report start|record-task|finish|show --json
```

## Consequences

Close gates and Prism reducers should require a latest report for non-trivial
runs. Host dashboards read this schema only — no parallel invent-a-metric formats.
