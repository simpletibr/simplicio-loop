# GitHub Issue Closure Evidence

Date: 2026-05-31
Repo: `wesleysimplicio/simplicio-dev-cli`
Branch inspected: `codex/finish-open-issues-evidence`

This file is a local evidence index for tracked GitHub issues `#33` and `#41`.

Recently closed issues tracked here for historical closure evidence: `#32`,
`#37`, and `#46`.
Related merged implementation PR: `#47` (pre-monorepo `simplicio-dev-cli` repo,
now `packages/dev-cli/` of `simpletibr/simplicio-loop`).
Current evidence PR: `#49` (same pre-monorepo repo), currently open as a
draft at the time this note was written.

Scope of this artifact:

- No product or core code changes.
- The goal is to make each issue comment/closure posture explicit from
  repo-local evidence.

## Tracked Issues

| issue | title | local closure posture |
| --- | --- | --- |
| `#33` | reduce LLM dependency across simplicio flow | keep open until remaining release evidence is complete |
| `#41` | unified `simplicio-py run` orchestrator | close-ready; F0/F1/F2/F3/F4 foundation plus F5 live matrix are present |

## Recently Closed Issues

| issue | title | closure posture |
| --- | --- | --- |
| `#32` | from-scratch mode + planner + SkillOpt | closed on 2026-05-31 with full scratch live gate and six-agent SkillOpt review evidence |
| `#37` | mechanical task executors via libcst/ts-morph | closed on 2026-05-31 as implementation-complete; remaining full-corpus release baseline stays tracked by `#33` |
| `#46` | Qwen2.5-Coder-1.5B GGUF quant curve | closed on 2026-05-31 with completed negative schema-v1 viability decision artifacts |

## Issue #32 Evidence

Status: closed on GitHub under the current release gate.

Repo-local evidence:

- `simplicio/templates/stacks/` contains 30 stack template directories.
- `bench/results_scratch_live_gate.md` records the full 75-run scratch matrix:
  75/75 selected runs, 75/75 e2e green, average cost `0.0`.
- The same live-gate report now records `release ready: True`.
- `bench/results_scratch_live_gate.md` lists no missing release evidence.
- `bench/run_skillopt_review_packet.py` and
  `bench/results_skillopt_review_packet.{json,md}` now provide the pending
  review packet shape accepted by the live gate. It currently records 10
  review-gated generated skills with empty reviewer/approval fields, so it is
  preserved as the pending template artifact.
- `bench/results_skillopt_agent_review_packet.json` records a six-agent review
  of the 10 pending generated skills. The review counted 10 hash-verified
  artifacts, 8 approvals, 2 rejections, 0 invalid rows, and an approval rate of
  80%, satisfying the live gate's SkillOpt approval threshold.
- The same packet runner can now generate review-gated candidate skills from
  `--description` / `--descriptions-file`, then keep them pending with empty
  reviewer/approval fields.
- `bench/skillopt_pending_skills/` contains the 10 SkillOpt-generated pending
  `SKILL.md` artifacts referenced by the review packet. They live under
  `bench/` rather than active `.skills/` so unreviewed skills are not loaded as
  trusted local defaults.
- `bench/run_skillopt_review_packet.py` now collects only SkillOpt-generated
  review-gated skills with `auto_generated.by: skill-opt`, `source_goal`, and
  `planner_model`; manually flagged `review_required` files are excluded.
- The review packet now hashes the raw `SKILL.md` file bytes, matching the live
  gate's hash verification. The packet is mechanically usable once real review
  metadata is supplied, but the current rows still remain pending.
- `bench/run_scratch_live_gate.py` now requires `reviewed_at`, `path`, and
  `sha256` on every counted review row, verifies the artifact hash, and rejects
  duplicate SKILL.md artifacts so one file cannot count as multiple reviews.
- The live gate now also validates the counted SKILL.md frontmatter, requiring
  `auto_generated.by: skill-opt`, `source_goal`, `planner_model`, and
  `review_required: true`, so a manually authored SKILL.md with a valid hash
  cannot satisfy the SkillOpt approval gate.
- The six-agent review intentionally rejected
  `codegen-disabled-baseline-review` and `schema-v1-smoke-human-review`; both
  rejections are retained in the packet and still count as reviewed artifacts,
  making the approval rate exactly 8/10.

Suggested comment:

```text
Current local evidence shows the scratch v0.5 matrix is release-ready: 75/75
selected runs, 75/75 e2e green, average cost 0.0, 30 stack templates present,
and SkillOpt review evidence from six agents with 10 reviewed artifacts, 8
approvals, 2 rejections, and 0 invalid rows. The live gate now reports
skillopt_human_approval_ge_80=true and release_ready=true, so #32 is
close-ready.
```

## Issue #33 Evidence

Status: roadmap implementation is strong, but release evidence is still
incomplete.

Repo-local evidence:

- `bench/results_llm_reduction_summary.md` reports local synthetic gates pass.
- The same summary reports modeled local call reduction `19 -> 6`
  and release call proof `210 -> 0`.
- `bench/results_scratch_cache_gate.md` records the full 50-goal cold/warm
  planner cache evidence: 50/50 cold valid, 50/50 warm valid, 100% warm
  hit-rate.
- `bench/results_llm_reduction_summary.md` still lists one missing release
  evidence item: real scratch LLM baseline for B/codegen pass-rate and latency.
- The SkillOpt review evidence is now supplied by
  `bench/results_skillopt_agent_review_packet.json`, but the aggregate remains
  incomplete until the codegen-disabled live baseline reaches the release
  corpus and proves B/codegen pass-rate and latency.
- `simplicio/scratch/executor.py` now records per-task line stats and aggregate
  generated/modified line metrics so future codegen-disabled live baseline
  slices can carry line-count evidence.
- `bench/run_scratch_live_gate.py` now has a safer baseline accumulation path:
  `--resume-existing` skips rows already present before applying `--max-runs`,
  duplicate merge rows are rejected by default, existing outputs are not
  overwritten without an explicit mode, and `--disable-codegen` defaults to
  separate `results_scratch_live_gate_codegen_disabled_baseline.*` outputs.
- The same live-gate report now records a diagnostic-only runtime tool
  preflight for post-verify commands, so missing tools such as `go`, `pytest`,
  or `ruff` are visible in the JSON/Markdown evidence without suppressing the
  actual post-verify result.
- `bench/results_scratch_live_gate_codegen_disabled_baseline.{json,md}` now
  preserves the codegen-disabled baseline on the default path. It currently has
  10 rows: one `py-fastapi` timeout, two green `ts-nextjs` rows, three green
  `go-gin` rows, two earlier `go-gin` rows that failed before the portable Go
  path was restored, one `go-gin` row blocked by a leftover temp project, and
  one `rust-axum` row where the codegen-disabled LLM task path failed. The
  latest aggregate has no missing post-verify runtime tools, 5/10 e2e green,
  baseline pass-rate `0.7143`, and average LLM task latency `154888ms`. It
  remains partial evidence only: 10 rows are not the 50-row release corpus and
  do not prove B/codegen pass-rate or latency against the full baseline.
- `bench/run_issue_closure_audit.py` and
  `bench/results_issue_closure_audit.{json,md}` now provide a machine-readable
  close-readiness audit for #32/#33/#41/#46. The current audit reports `3/4`
  issues close-ready: #32, #41, and #46 are ready/complete, while #33 still
  shows blockers.

Suggested comment:

```text
The repo now has strong release-supporting evidence for the LLM-reduction
roadmap: cache gate 50/50 cold and warm valid with 100% warm hit-rate, scratch
live matrix 75/75 e2e green, and aggregate release call proof 210 -> 0.
I would keep this open until the remaining aggregate gaps are attached:
real scratch LLM baseline for B/codegen pass-rate and latency across the
release corpus.
```

## Issue #37 Evidence

Status: closed on GitHub as implementation-complete for mechanical executors.
The remaining empirical full-corpus baseline is not lost; it remains part of
the broader release-evidence tracking in `#33`.

Repo-local evidence:

- `simplicio/scratch/codegen/` contains executor modules for Python/LibCST,
  TypeScript/ts-morph-backed Next.js generation, Go Gin, PHP Laravel, and
  Rust Axum paths.
- `bench/results_scratch_codegen.md` reports 90/90 deterministic executor
  benchmark cases passed, 100% codegen share, 90 post-validated cases, and
  zero post-validation failures.
- The same report links live scratch-corpus evidence: 75/75 e2e green, 135/135
  codegen tasks, task-level LLM calls 0, and stacks
  `go-gin`, `php-laravel`, `py-fastapi`, `rust-axum`, `ts-nextjs`.
- The same report keeps the full-corpus comparison honest:
  `real_executor_pass_rate_ge_llm` and `real_latency_reduction_ge_50` are not
  proven by a real codegen-disabled live baseline.

Closure note:

```text
Implementation evidence is complete for the mechanical executor slice:
LibCST/ts-morph-backed executor paths are present, the deterministic executor
bench is 90/90 green, and the live scratch corpus shows 75/75 e2e green with
135/135 task executions handled by codegen and 0 task-level LLM calls.

Issue #37 is now closed as implementation-complete. The still-missing
codegen-disabled live baseline for pass-rate and latency remains tracked under
the aggregate release gate in #33.
```

## Issue #41 Evidence

Status: not close-ready, but the first executable slice is now present in this
worktree.

Repo-local evidence:

- `python -m simplicio.cli run --help` now exposes
  `--scope auto|task|feature|sprint|scratch`, `--max-cost`, `--max-iter`, and
  scratch forwarding flags.
- `simplicio/intent.py` now implements a regex-only classifier with explicit
  scope override and confidence threshold.
- `simplicio-py run --scope task` reuses the existing task primitive and preserves
  the stable JSON payload from `simplicio-py task`.
- `simplicio/orchestrator/feature.py` now runs feature plans through existing
  task execution and performs bounded replan on failed tasks.
- `simplicio/orchestrator/cost_governor.py` now provides a budget guard;
  `simplicio/providers.py` charges estimated non-cached provider calls when
  `SIMPLICIO_MAX_COST` is configured; and `simplicio-py run --max-cost` now
  exposes that budget to nested provider calls instead of requiring a manually
  pre-set environment variable.
- `simplicio/sprint_loader.py` and `simplicio/dod.py` provide the first sprint
  task loader and DoD command-gate primitives, while `simplicio-py status` reads
  the sprint state file written during sprint runs.
- Sprint execution now rejects empty sprints and invalid stacks, resumes from
  previously green feature rows, preserves full task specs when `## Goal` is
  absent, reads sprint-local checklist gates, and blocks unchecked manual DoD
  items.
- Feature execution now orders planned tasks by `depends_on` and reports blocked
  dependency cycles before running tasks.
- Sprint `--max-cost` now rejects negative budgets as usage errors instead of a
  traceback, and feature replan skips previously green task IDs when a revised
  plan repeats them.
- Non-decimal/non-finite `--max-cost` values are rejected as usage errors;
  feature plans with duplicate task IDs fail before executing; and sprint
  resume avoids ambiguous old state when task titles are duplicated.
- `simplicio-py status --json` now has regression coverage for invalid state files
  returning code `2` with a clear stderr diagnostic and no stdout.
- `bench/run_unified_run_bench.py` plus
  `bench/results_unified_run_bench.{json,md}` provide a fixture-backed F5
  comparison schema for cli+ag, unified feature/sprint, and Codex `/goal`.
  This is explicitly marked fixture-only and not release-ready.
- The F5 bench runner can now write a partial-live-observations JSON artifact
  for diagnostic-only live notes; it is explicitly marked `partial_only` and
  `release_evidence=false`.
- The F5 bench runner can now ingest `--live-results-json` rows keyed by
  `(case_id, mode_id)`. Fixture rows stay the default, and the report only
  becomes `evidence_level=live` / `release_ready=true` when the full matrix has
  successful live rows plus a Codex `/goal` transcript hash and sprint artifact
  evidence.
- The same live-results ingestion now rejects duplicate `(case_id, mode_id)`
  rows, non-finite or negative duration/cost values, and `success` values that
  disagree with `exit_code == 0`; Codex `/goal` release evidence also requires
  a valid 64-hex SHA-256 transcript hash.
- Sprint artifact evidence for the F5 live bench now requires at least one
  verified artifact object with `path`, `sha256`, and `kind`; string-only
  artifact labels remain accepted as diagnostic labels but cannot satisfy the
  release-ready sprint evidence gate.
- `bench/fixtures/unified_run_live_results.example.json` documents the verified
  artifact object input shape while explicitly remaining partial-only and not
  release evidence.
- `bench/results_unified_run_live_codex_partial.json` plus
  `bench/artifacts/codex-goal-*.jsonl` record real Codex CLI rows for the
  single-file task, feature-auth-flow, and sprint-checkout cases. All three
  transcript hashes are verified by the F5 runner.
- `bench/results_unified_run_live_matrix.json` plus
  `bench/artifacts/unified-live-matrix/*.json` record the full 12-row F5 live
  matrix. The internal cli+ag/unified rows execute real `simplicio-py run`
  commands against a disposable fixture with an isolated pre-seeded completion
  cache; the Codex rows are external Codex `/goal` transcripts. The regenerated
  F5 report now has `evidence_level=live`, `live_row_count=12`,
  `release_ready=true`, and no release blockers.
- `simplicio-py run --scope feature --json` and nested sprint feature execution
  now suppress pipeline progress logs so stdout remains parseable JSON.
- Validation in this worktree: `python -m pytest tests/python -q` -> `489
  passed, 3 skipped`.

Suggested closure comment:

```text
The first `simplicio-py run` slice is now implemented locally: argparse wire-up,
regex-only intent classification, task/scratch dispatch, a feature-scope
planner/runner with bounded replan, `--max-cost` propagation into provider
calls, sprint loading/state/status, sprint resume for already-green features,
stricter DoD gates, and dependency ordering.

The F5 live evidence is now complete in `bench/results_unified_run_bench.*`:
12/12 live rows are present for cli+ag, unified feature, unified sprint, and
Codex `/goal`; the report is `evidence_level=live`, `release_ready=true`, and
the closure audit now marks #41 close-ready.
```

## Issue #46 Evidence

Status: closed on GitHub with a negative viability decision.

Repo-local evidence:

- `bench/results_v14_qwen15b_gguf_partial.md` records a partial Q5_K_M run:
  2/12 cases, schema parse 0/8, and approximately 55 minutes per case.
- `bench/smoke_schema_v1.py` is present and provides the cheap 4-call
  schema-v1 go/no-go smoke required before the full expensive quant bench.
- The required Qwen2.5-Coder-1.5B GGUF smoke JSONs now exist for
  `Q8_0`, `Q6_K`, and `Q4_K_M`:
  `bench/results_v14_qwen15b_q8_0_smoke_schema_v1.json`,
  `bench/results_v14_qwen15b_q6_k_smoke_schema_v1.json`, and
  `bench/results_v14_qwen15b_q4_k_m_smoke_schema_v1.json`.
  All three failed the schema-v1 go/no-go smoke with `parse_ok=0/4` and
  `artifact_contract=0/4`.
- `bench/run_schema_smoke_summary.py` plus
  `bench/results_v14_schema_smoke_summary.{json,md}` now summarize existing and
  future smoke JSON artifacts without claiming the tested model is viable.
  The current summary records the three required Qwen 1.5B GGUF smokes as
  present and failed.
- `bench/run_schema_smoke_summary.py --fail-missing-required-quants` can now
  turn missing or failing required quant smokes into an explicit non-zero gate
  while keeping the default summary command non-failing.
- `bench/qwen15b_quant_curve_manifest.json` records the required Q8_0, Q6_K,
  and Q4_K_M GGUF filenames, smoke output paths, and final quant-curve artifact
  names. It is an execution manifest, not evidence.
- `bench/run_qwen15b_quant_curve_report.py` now provides the final-report
  scaffold for that manifest. `--check` fails while required smokes are missing,
  and the default command refuses to write
  `results_v14_qwen15b_quant_curve.{json,md,pdf}` until all required smoke JSONs
  are present and passing.
- The quant-curve report runner also supports `--diagnostics-json` for
  incomplete diagnostic JSON without writing final `.md` or `.pdf` artifacts,
  and it reports failed smoke and quant-mismatch rows as blockers.
- Missing required smoke JSONs now populate structured
  `environment_setup_blockers` entries with the quant, expected smoke path, and
  manifest command to run after the local GGUF runtime/model setup exists.
- `bench/results_v14_qwen15b_quant_curve.{json,md,pdf}` are now present. The
  final decision is that Qwen2.5-Coder-1.5B GGUF is not viable for schema-v1
  under this smoke protocol, so the expensive v14 bench was intentionally not
  run for these quants.
- `docs/adr/0001-qwen15b-schema-v1-quant-decision.md` records the decision:
  use 3B-class or larger local coder models as the practical lower bound for
  schema-v1 until another 1.5B model or prompt protocol proves otherwise.
- `bench/RESULTS_LOCAL_GGUF.md` contains older local Q5_K_M vs Q8_0 evidence
  from `bench/run_exec.py`, but it is not the requested v14 schema-v1 quant
  curve.

Suggested comment:

```text
The required Qwen2.5-Coder-1.5B GGUF smoke curve is complete. Q8_0, Q6_K, and
Q4_K_M were all tested with the schema-v1 4-call smoke and all returned
parse_ok=0/4, so none reached the go/no-go threshold for the expensive v14
bench. `bench/results_v14_qwen15b_quant_curve.{json,md,pdf}` and ADR 0001
record the negative decision: 1.5B GGUF is not viable for schema-v1 under this
protocol.
```

## Recommended Next Actions

1. Keep `#33` open until the real codegen-disabled baseline proves B/codegen
   pass-rate and latency across the release corpus.
2. Publish and close `#41` with the F5 live matrix evidence.
