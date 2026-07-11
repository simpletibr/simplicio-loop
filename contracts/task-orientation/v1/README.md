# Task orientation contract v1

This contract defines the offline, deterministic boundary between raw task
intake and repository orientation.

- `simplicio.task-intent/v1` preserves normalized business intent independent
  of Markdown, Gherkin, or JSON representation.
- `simplicio.task-context/v1` binds the task fingerprint to an existing
  mapper artifact fingerprint and evidence-backed repository candidates.
- `simplicio.task-batch/v1` is a deterministic, plan-only envelope for one or
  more zero-target tasks. It topologically orders dependencies and reports
  shared candidate surfaces as conflicts; it never authorizes execution.
- `simplicio.task-traceability/v1` preserves AC/RN IDs and relates static file,
  symbol, flow, and test candidates to receipt references. Static mapping is
  never verification; only a fresh explicit receipt can set `verified`.

The PLANES fixture is the complete golden example. No schema in this directory
authorizes commands, changes the repository root, or invokes an LLM.

Examples:

```bash
simplicio-mapper orient . --task-file task.md --json
Get-Content task.md | simplicio-mapper orient . --stdin --for-llm toon
simplicio-mapper orient . --task-json tasks/planes.json --json
```

For multiple tasks, invoke `orient` once per task JSON object and retain each
`task.fingerprint`; the normalized contract is intentionally one task per
envelope so cache keys and evidence remain deterministic.
