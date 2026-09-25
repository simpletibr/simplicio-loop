# Behavioral corpus and scorecard (v1)

This corpus measures the mapper against real CLI output. Cases contain source
files, a task, and reviewer-owned golden labels; the runner creates a fresh
temporary checkout, runs `map --root`, then runs task-aware `handoff`.

The scorecard is intentionally offline and deterministic. It reports the
baseline (map-only and generic handoff) separately from task-aware handoff;
it never replaces a missing target with a pass and never changes thresholds
automatically. Threshold changes require editing `thresholds.json` with an
explicit `justification` and review.

`MEASURED` fields come from the subprocess output. Token counts are
`utf8-bytes-div-4` estimates, not LLM measurements, and are labeled as such.
