---
name: codegen-disabled-baseline-review
description: Human review workflow for baseline rows where code generation is disabled.
trigger: Use when reviewing baseline result rows that must not generate code and require evidence of fallback, latency, and flags.
auto_generated:
  by: skill-opt
  date: 2026-05-31
  source_goal: Generate a human review workflow for codegen-disabled baseline rows, covering LLM fallback usage, latency, post-verify evidence, and no-codegen flags.
  planner_model: codex-cli/default
  review_required: true
---

# codegen-disabled-baseline-review

## When to use

Use this skill when a baseline row is explicitly marked codegen-disabled, no-codegen, review-only, or equivalent, and a human must confirm that the row was evaluated without producing patches, files, scaffolds, or hidden generated code.

## Steps

1. Identify the exact baseline row under review: row id, scenario name, command, config file, input prompt, model, timestamp, and expected no-codegen behavior.
2. Confirm the no-codegen control was active by recording the exact observed flag or setting, such as `--no-codegen`, `codegen=false`, `CODEGEN_DISABLED=1`, or the project-specific equivalent.
3. Inspect outputs for prohibited codegen artifacts: diffs, created files, modified files, scaffold directories, generated patches, staged changes, or tool logs showing write/edit operations.
4. Review LLM fallback behavior: the LLM may summarize, classify, explain, or recommend next steps, but it must not emit implementation patches or claim generated code was applied.
5. Check latency evidence: capture start time, end time, total duration, and whether fallback/no-codegen behavior materially changed latency versus the expected baseline.
6. Run or inspect the post-verify step after the row completes, using the project's verification command or artifact, and record pass/fail with the exact evidence path.
7. Compare the row result against the baseline contract: no codegen, fallback used only where allowed, latency recorded, post-verify evidence present, and flags visible in logs or metadata.
8. Mark the row as approved only if all evidence is present and the reviewer can independently trace the result from command/config to logs to post-verify artifact.

## DoD

- [ ] Baseline row id, scenario, model, command/config, and timestamp are recorded.
- [ ] The exact no-codegen flag or setting is captured from logs, config, or metadata.
- [ ] No generated files, patches, staged changes, or scaffold artifacts are present.
- [ ] LLM fallback usage is documented and stayed within review-only/non-codegen behavior.
- [ ] Latency is recorded with start time, end time, and total duration.
- [ ] Post-verify evidence is present, linked, and includes pass/fail status.
- [ ] Any failure includes the row id, log excerpt, missing evidence, and likely cause.
- [ ] Human reviewer decision is explicit: approved, rejected, or needs rerun.

## Anti-patterns

- Approving a row because no diff is visible without checking logs, flags, and artifacts.
- Treating an LLM explanation as valid fallback when it includes patch-ready implementation output.
- Recording latency as "fast" or "normal" without exact timing evidence.
- Accepting post-verify claims without an artifact path, command output, or durable evidence.
- Assuming no-codegen was enabled from the scenario name instead of verifying the actual flag/config.
- Hiding failed verification behind baseline status or marking review complete with missing evidence.
