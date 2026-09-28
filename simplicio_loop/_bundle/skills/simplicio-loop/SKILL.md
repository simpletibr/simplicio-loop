---
name: simplicio-loop
description: "Ralph loop for mapper + simplicio-dev-cli. Same goal every turn; exit only on an evidence-gated promise or max_iterations. GitHub is SoT for issues/PRs. Host writes the edit plan."
---

<!-- simplicio-contract:begin -->
contract: simplicio-loop
schema: simplicio.skill/v1
purpose: Ralph loop for mapper + simplicio-dev-cli: same goal every turn, exit only on an evidence-gated promise or max_iterations.
rules: Follow this skill end-to-end; mutable data (versions, dates, counts) lives in the footer, never in this header.
<!-- simplicio-contract:end -->

# /simplicio-loop

On invocation, start this engine. Do not explore the tree and do not call
`simplicio-mapper scan`, `inspect`, or `handoff` by hand.

One monorepo. `packages/mapper` surveys and `packages/dev-cli` applies.
Do not install those as external projects. No Runtime. No Fast package.
`orient` is the Mapper survey. It is cached: a second call on an unchanged
tree reuses it. `--tee` stores the JSON in the tee cache.

Turbo is the default. Mapper reads the repo once. That project map is the
header and stays byte-identical on every call. The task text and the current
target file are the suffix. The model returns an edit plan and
`simplicio-dev-cli` applies it. A rejected plan is sent back once, then turbo
stops. Up to three tasks share one model call. Above three tasks the first
call runs alone, then the rest follow so every later call can read that
header from prompt cache. Dependent tasks stay in order. Independent tasks
share the header, and dev-cli applies one plan at a time. The model does not
edit files itself. Every model call after the first must read prompt cache
(DeepSeek harness `request-cache.e2e.ts`).

Self-referential iteration: the SAME goal is re-fed each turn. Exit ONLY when
the typed `<promise>…</promise>` is true **and** in-turn evidence exists, or
when `max_iterations` fires. Credit: Ralph Wiggum / cursor `ralph-loop`.

The host LLM writes find/replace text. The engine freezes, applies, and
verifies it. The loop never calls a provider to write code.

## The flow (one task and many tasks)

Run these, in order. The same sequence covers one task and many tasks.
Any repository: pass `--repo <path>`.

```bash
# 1. Survey (plain-prose goal, no "T1"/"T2" labels)
simplicio-loop orient --repo <path> --task "<goal>" --tee --json

# 2. Arm a run for 1..N tasks (see "Task file" below); prints run_id
simplicio-loop prepare --task tasks.md --repo <path>

# 3. Per task N, write ONLY find/replace text:
#    .simplicio-loop/loop-runs/<run_id>/edit-plan-<N>.json
#    {"operations": [{"path": "calc/ops.py", "find": "<exact text, unique in file>", "replace": "<new text>"}]}

# 4. Execute
#    more than one task: one wave, lanes in parallel, finishes when every lane has integrated or failed closed
simplicio-loop wave <run_id> --repo <path>
#    exactly one task
simplicio-loop tick <run_id> --repo <path> --task-index 1

# 5. Independent verification
simplicio-loop verify <run_id> --repo <path>
```

- Write every `edit-plan-<N>.json` up front. The loop freezes each one
  (`simplicio-dev-cli edit --compile`) right before applying it, so task 2
  binds to the tree task 1 left. A `find` that does not match exactly once
  blocks that task. Fix the text and re-run. `find: ""` creates a missing
  file and does not overwrite an existing non-empty file.
- Disjoint paths run together with asyncio. Paths that overlap stay in one
  lane, in order. Integration back into the shared tree is serial.
- The 50 binding points are `references/extension-points.md`. A delivery run
  still closes on `delivery_gate` and `verify`. Two or more tasks are one wave:
  the lanes run together, and the wave returns only when every lane has closed.
  If the machine is under disk pressure but still has safe workers, the wave
  runs at that width instead of being skipped.
- One small change, no run:
  `simplicio-dev-cli edit --plan ops.json --compile plan.json` then
  `simplicio-dev-cli edit --plan plan.json --apply --json` then
  `simplicio-dev-cli test --json`.
- **Never** `simplicio-dev-cli task "prose"` (answers `plan_required`).

## Task file (`tasks.md`)

One block per task. A new `System:` line starts the next block.

```markdown
System: calc
Feature: add mul(a, b)
Type: Feature

1. Acceptance Criteria
Scenario 1: mul multiplies two numbers — returns 12 for mul(3, 4)

8. Additional Information
Independent verifier: `python3 -m pytest -q`
```

`Type: Docs|Chore|Config` or `Tests: none` waives the lane matrix for that task.

`Then` is its own line. A `Then` on the same line as `Given` or `When` is refused.
When the Mapper handoff does not authorize files, each task needs `Target: <path>`.

## Done

`wave` and `tick` verify automatically. `simplicio-loop verify <run_id>`
re-runs it. Done = run phase `done` and completion `VERIFIED` or `MEASURED`.
Emit the `<promise>` only after that, in the same turn.

## Contract

1. Evidence-gated exit. No in-turn evidence → no promise.
2. Exact sentinel `<promise>EXACT TEXT</promise>` matching `completion_promise`.
3. `max_iterations` is mandatory before iteration 1.
4. Scratchpad `.simplicio-loop/orchestrator/loop/scratchpad.md` is the agent SoT.
5. Review: **1 implement + 1 verify**. No 3–4 reviewer panels on ordinary diffs.

## State

`.simplicio-loop/orchestrator/loop/scratchpad.md`:

```markdown
---
iteration: 1
max_iterations: <N>
completion_promise: "<EXACT TEXT>"
evidence_required: true
mode: converge
started_at: "<ISO-8601>"
---

<goal, verbatim>
```

Journal: `.simplicio-loop/orchestrator/loop/journal.jsonl`.

## Drive

Hook hosts (Claude/Cursor): capture + stop hooks re-feed the goal.
Self-paced hosts: re-read the scratchpad every turn; triage → decide → operate → verify → journal.

Every turn's first line is `python3 scripts/loop_progress.py render --turn-header`.

End every message: `DONE | NEXT | BLOCKED`.

<!-- SIMPLICIO-LLM-ORIENTATION:BEGIN -->
Loop orientation:
- On invocation, start the engine. Any repository via `--repo <path>`.
- Monorepo: packages/mapper, packages/dev-cli, loop at the root. Do not install them as external projects. No Runtime. No Fast package.
- One flow for one task and for many: orient --tee → prepare tasks.md → edit-plan-<N>.json → tick when exactly one task, wave when more than one → verify.
- One small change, no run: simplicio-dev-cli edit --plan, compile, apply, test.
- Mapper survey is cached. `--tee` stores the JSON.
- Disjoint lanes run together with asyncio. The wave finishes only when every lane has integrated or failed closed.
- GitHub is SoT for issues/PRs when the remote is GitHub.
- Never simplicio-dev-cli task "prose". No plan → plan_required.
- Review: 1 implement + 1 verify. Promise only after verify MEASURED.
- End: DONE | NEXT | BLOCKED.
<!-- SIMPLICIO-LLM-ORIENTATION:END -->

## Bounded delivery

One implementation issue and one delivery PR per worker. Freeze the goal before mutation. Findings: `AC_BLOCKER` / `REGRESSION_BLOCKER` / `FOLLOW_UP`. Only blockers hold the current delivery.

## Guardrails

- Do not invent MEASURED numbers.
- Do not close issues without a live GitHub re-query.
- Do not hand-edit source as the primary mutation path. Write the edit plan and let the engine apply it.
- Exactly one task uses `tick`. More than one task uses `wave`.

Full per-turn protocol: `references/full-flow.md` — read it only when the task needs it.

## What the model sees

When a host loads this skill, the model receives the YAML frontmatter, the
immutable `simplicio-contract` header, and this body, verbatim. Files under
`references/` enter the context only when this body points to them. Nothing
here is generated per run.

### Token effect

The body is paid once per session as input tokens. References are paid only on
demand, so the always-loaded part stays the short hot path.

### KV cache effect

The frontmatter and header are byte-stable across releases (pinned in
`contracts/headers.lock.json`), and mutable data lives only at the end of the
file. The provider can therefore reuse the cached prefix from the second call
on, and a release does not invalidate it unless a `header-change:` note says so.
