---
name: unified-run-f5-live-rows-review
description: Review unified-run F5 live rows for command evidence, status, costs, artifacts, and transcript integrity.
trigger: Use when a human must review unified-run F5 live row evidence before accepting or publishing results.
auto_generated:
  by: skill-opt
  date: 2026-05-31
  source_goal: Generate a human review workflow for unified-run F5 live rows, covering command evidence, exit code, duration, cost, artifacts, and transcript hashes.
  planner_model: codex-cli/default
  review_required: true
---

# unified-run-f5-live-rows-review

## When to use
Use this skill for human review of unified-run F5 live rows where the reviewer must confirm that each row has enough evidence to trust the recorded result, including the command executed, exit code, duration, cost, artifacts, and transcript hash integrity.

## Steps
1. Identify the exact unified-run F5 live row under review, including run id, row id, task id, timestamp, environment, and status.
2. Verify command evidence is complete: command text, working directory, relevant flags, sanitized environment context, and log or transcript pointer.
3. Confirm the exit code is present, numeric, and consistent with the recorded status; nonzero exits must include a failure explanation or blocker note.
4. Check duration evidence: start time, end time, elapsed duration, units, and whether the value is plausible for the command and transcript.
5. Review cost evidence: reported cost, currency or token basis, model or service source, and whether missing or zero cost is explicitly justified.
6. Inspect artifact references: every declared artifact must have a stable path or URL, expected type, creation evidence, and reviewer-accessible contents.
7. Validate transcript hashes: recompute or compare the recorded hash against the transcript source, and flag any mismatch, missing transcript, or ambiguous hash algorithm.
8. Cross-check row consistency: command, transcript, artifacts, exit code, duration, and cost must describe the same execution attempt.
9. Record human review outcome as accepted, rejected, or needs-follow-up, with concise notes for every gap found.
10. Do not approve the row until all required evidence is present, internally consistent, and free of secrets or unredacted sensitive data.

## DoD
- [ ] Row id, run id, task id, timestamp, and reviewer identity are recorded.
- [ ] Command evidence includes command text, cwd, flags, and sanitized context.
- [ ] Exit code is present and matches the row status.
- [ ] Duration has start, end, elapsed value, units, and plausibility check.
- [ ] Cost evidence is present or explicitly justified as unavailable or zero.
- [ ] All artifact references are accessible and match the row claims.
- [ ] Transcript hash algorithm and value are recorded and verified.
- [ ] Transcript, artifacts, command, status, duration, and cost are mutually consistent.
- [ ] Secrets, tokens, credentials, and sensitive paths are redacted.
- [ ] Final human review decision and follow-up notes are written.

## Anti-patterns
- Approving a row from status alone without checking command evidence.
- Treating missing cost or duration as acceptable without an explicit note.
- Accepting artifact paths that are broken, local-only, or unrelated to the run.
- Ignoring a transcript hash mismatch because the visible logs look plausible.
- Collapsing multiple execution attempts into one row without clear evidence.
- Marking a failed exit code as accepted without a documented reason.
- Copying transcript excerpts into review notes when a hash and artifact pointer are sufficient.
