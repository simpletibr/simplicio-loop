---
name: schema-v1-smoke-human-review
description: Human review workflow for schema-v1 smoke outputs before go/no-go decisions.
trigger: Use when a reviewer validates schema-v1 smoke outputs for parse status, release threshold, model identity, and quant labels.
auto_generated:
  by: skill-opt
  date: 2026-05-31
  source_goal: Generate a human review workflow for schema-v1 smoke outputs, covering parse_ok, go/no-go threshold, model identity, and quant labeling.
  planner_model: codex-cli/default
  review_required: true
---

# schema-v1-smoke-human-review

## When to use

Use this skill when reviewing schema-v1 smoke output artifacts before accepting, publishing, or using them as gate evidence. It applies when a human must confirm that the output parsed successfully, meets the go/no-go threshold, identifies the model correctly, and labels quantitative results consistently.

## Steps

1. Locate the schema-v1 smoke output artifact and confirm it is the exact artifact under review, not a stale or regenerated file.
2. Verify the artifact declares schema-v1 and contains the expected top-level fields for the smoke output format.
3. Check `parse_ok` first:
   - If `parse_ok` is not present, not boolean, or `false`, mark the review as no-go.
   - Record the parse failure reason if the artifact provides one.
4. Review the go/no-go threshold:
   - Identify the configured threshold used for the smoke run.
   - Compare the observed score or pass count against that threshold.
   - Mark go only when the threshold is explicitly met or exceeded.
   - Mark no-go when the threshold is missing, ambiguous, or failed.
5. Validate model identity:
   - Confirm the model name/id is present.
   - Confirm it matches the expected model for the run.
   - Flag aliases, missing versions, or unexpected providers for follow-up before go.
6. Validate quant labeling:
   - Confirm quantitative fields are labeled with clear metric names.
   - Confirm units, percentages, counts, or score ranges are explicit.
   - Confirm labels distinguish raw values from normalized, averaged, or thresholded values.
7. Review any warnings, skipped checks, or partial results and decide whether they affect the gate.
8. Record the final human decision as `go` or `no-go` with a short reason tied to `parse_ok`, threshold result, model identity, and quant labeling.
9. If no-go, provide the minimum corrective action needed before re-running or re-reviewing the smoke output.

## DoD

- [ ] The reviewed artifact is confirmed to be the intended schema-v1 smoke output.
- [ ] `parse_ok` is present, boolean, and explicitly evaluated.
- [ ] The go/no-go threshold is identified and compared against the observed result.
- [ ] The final go/no-go decision is recorded with a reason.
- [ ] Model identity is present and matches the expected run configuration.
- [ ] Quantitative labels are checked for metric name, unit or scale, and value meaning.
- [ ] Any missing, ambiguous, stale, or partial evidence is called out as a blocker or risk.

## Anti-patterns

- Treating a successful file read as equivalent to `parse_ok: true`.
- Approving a run when the threshold is missing or inferred from memory.
- Ignoring model aliases, missing versions, or unexpected provider names.
- Accepting unlabeled numbers without units, score ranges, or metric names.
- Mixing raw counts, percentages, normalized scores, and threshold decisions under one label.
- Re-reviewing a regenerated artifact while claiming it is the original smoke output.
