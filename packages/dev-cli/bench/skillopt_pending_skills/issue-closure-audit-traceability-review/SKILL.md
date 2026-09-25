---
name: issue-closure-audit-traceability-review
description: Human review workflow for issue-closure audit artifacts and blocker traceability across issues.
trigger: Use when auditing issue-closure artifacts for #32, #33, #41, and #46, especially blocker traceability.
auto_generated:
  by: skill-opt
  date: 2026-05-31
  source_goal: Generate a human review workflow for issue-closure audit artifacts, covering blocker traceability across #32, #33, #41, and #46.
  planner_model: codex-cli/default
  review_required: true
---

# issue-closure-audit-traceability-review

## When to use
Use this skill when a human reviewer must verify that issue-closure audit artifacts are complete, consistent, and traceable across issues #32, #33, #41, and #46.

Use it before marking closure evidence as accepted, merging related closure work, or declaring blockers resolved.

## Steps
1. Collect the closure artifacts for #32, #33, #41, and #46, including issue links, final comments, PRs, commits, test logs, screenshots, reports, and any blocker notes.
2. Build a blocker traceability table with one row per blocker and columns for issue number, blocker summary, source artifact, resolution artifact, validation evidence, reviewer verdict, and remaining gap.
3. For each issue, confirm that every closure claim points to concrete evidence and not only to a summary statement.
4. Check cross-issue blocker continuity: if a blocker moved from #32 to #33, #41, or #46, verify that the handoff is explicit and the destination issue contains the continuation evidence.
5. Verify that each blocker has one of three clear outcomes: resolved with evidence, intentionally deferred with owner and rationale, or still open and blocking closure.
6. Compare issue comments, PR descriptions, and audit artifacts for contradictions in blocker status, affected scope, validation results, or closure timing.
7. Confirm that validation evidence is reproducible enough for review: command, environment, artifact path, timestamp when available, and relevant log excerpt.
8. Flag any missing, stale, ambiguous, or unverifiable artifact as a review finding instead of inferring success.
9. Produce a human review verdict for each issue: accepted, accepted with follow-up, or rejected pending artifact/blocker correction.

## DoD
- [ ] Closure artifacts for #32, #33, #41, and #46 were reviewed.
- [ ] Every blocker has a source artifact and a resolution or deferral artifact.
- [ ] Cross-issue blocker handoffs are explicitly traceable.
- [ ] Validation evidence is linked to each resolved blocker.
- [ ] Deferred blockers include owner, rationale, and follow-up location.
- [ ] Remaining gaps are listed with exact missing artifact or contradiction.
- [ ] Final reviewer verdict is recorded per issue.

## Anti-patterns
- Treating a closed issue as proof that its blockers were resolved.
- Accepting summary text without linked evidence.
- Losing blocker history when work moves between #32, #33, #41, and #46.
- Marking blockers resolved when they are only deferred.
- Combining multiple blockers into one vague audit row.
- Ignoring contradictions between comments, PRs, and validation artifacts.
