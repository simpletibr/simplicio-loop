---
name: scratch-live-gate-results-review
description: Review scratch live-gate rows for planner validity, verify logs, cost, and line metrics.
trigger: Use when a scratch live-gate result row needs human review before acceptance, promotion, or reporting.
auto_generated:
  by: skill-opt
  date: 2026-05-31
  source_goal: Generate a human review workflow for scratch live-gate result rows, covering planner validity, post-verify logs, cost, and line metrics.
  planner_model: codex-cli/default
  review_required: true
---

# scratch-live-gate-results-review

## When to use
Use this skill when manually reviewing scratch live-gate result rows to decide whether a row is valid, suspicious, incomplete, or ready to promote. Apply it to rows that include planner output, verification/post-verify evidence, cost data, and line-level metrics.

## Steps
1. Identify the row under review and record its stable keys: run id, task id, planner model, timestamp, source goal, and artifact/log locations.
2. Check planner validity: confirm the plan directly addresses the source goal, is scoped to the requested work, has measurable gates, and does not duplicate an existing skill or result row.
3. Verify that planner decisions are supported by row evidence, not only by optimistic labels such as `passed`, `valid`, or `complete`.
4. Review post-verify logs: open the referenced logs, confirm commands actually ran, inspect exit codes, timestamps, and failure text, and note any missing or truncated evidence.
5. Compare post-verify results against the live-gate expectations: required checks must be present, relevant to the row, and not replaced by unrelated validation.
6. Review cost metrics: check total cost, token counts, model usage, retries, and outliers against comparable rows or the expected budget.
7. Review line metrics: inspect lines added, removed, touched, generated, or verified; flag impossible counts, huge unexplained diffs, or zero-line claims for non-empty work.
8. Cross-check cost and line metrics together: high cost with tiny output, tiny cost with large output, or inconsistent retry counts require reviewer notes.
9. Assign a human review status: accept, reject, needs-fix, or needs-more-evidence, with a short reason tied to planner validity, post-verify logs, cost, or line metrics.
10. Preserve review evidence by linking exact logs, row ids, metric fields, and any anomalies so another reviewer can reproduce the decision.

## DoD
- [ ] Row identity and source goal are recorded.
- [ ] Planner validity is checked against the requested goal and expected live-gate criteria.
- [ ] Post-verify logs are inspected directly, including command results and failure excerpts when present.
- [ ] Cost metrics are reviewed for completeness and anomalies.
- [ ] Line metrics are reviewed for plausibility and consistency.
- [ ] Final human review status is assigned with a concise evidence-based reason.
- [ ] Any blocker, missing artifact, or suspicious metric is explicitly noted.

## Anti-patterns
- Trusting a pass/fail field without opening the supporting logs.
- Accepting a planner that is generic, duplicated, or not tied to the source goal.
- Ignoring missing post-verify evidence because other metrics look reasonable.
- Treating cost or token totals as valid without checking retries and model usage.
- Reviewing line metrics in isolation instead of comparing them with task scope and cost.
- Promoting rows with unexplained anomalies, missing artifacts, or unverifiable claims.
