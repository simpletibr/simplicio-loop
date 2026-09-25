---
name: simplicio-loop
description: "Ralph loop for mapper + fast + simplicio-dev-cli. Same goal every turn; exit only on an evidence-gated promise or max_iterations. GitHub is SoT for issues/PRs. Host writes the edit plan."
---

# /simplicio-loop

Self-referential iteration: the SAME goal is re-fed each turn. Exit ONLY when the
typed `<promise>…</promise>` is true **and** in-turn evidence exists, or when
`max_iterations` fires. Credit: Ralph Wiggum / cursor `ralph-loop`.

Stack: `simplicio-mapper` (survey) → `simplicio-fast` (context) →
`simplicio-dev-cli` (apply + test) → `simplicio-loop` (run, wave, verify).
**No Runtime. No MCP force.** You (the host LLM) decide each change as exact
find/replace text; the tools freeze, apply and verify it. The loop never calls
a provider to write code.

## The flow (run these, in order)

```bash
# 1. Survey: what to change (plain-prose goal, one task, no "T1"/"T2" labels)
simplicio-loop orient --task "<goal>" --json        # Mapper + Fast context in one call

# 2. Arm a run for 1..N tasks (see "Task file" below); prints run_id
simplicio-loop prepare --task tasks.md --repo .

# 3. Per task N, write ONLY find/replace text (read the target file first):
#    .simplicio/loop-runs/<run_id>/edit-plan-<N>.json
#    {"operations": [{"path": "calc/ops.py", "find": "<exact text, unique in file>", "replace": "<new text>"}]}

# 4. Execute: all tasks as a wave, or one task
simplicio-loop wave <run_id> --repo .
simplicio-loop tick <run_id> --repo . --task-index <N>

# 5. Independent verification (watcher + delivery gates)
simplicio-loop verify <run_id> --repo .
```

- `orient --json` answers with a `commands` card (the exact `prepare`/`wave`/
  `verify`/`tick` invocations for this repo, the edit-plan path/format, and
  the task-file lanes) and `targets` (bounded, grounded file contents —
  small files in full, larger ones as a line-numbered symbol span — to copy
  `find` text from, so the host never hallucinates a path or an anchor).
- Write every `edit-plan-<N>.json` up front: the loop freezes each one
  (`simplicio-dev-cli edit --compile`) right before applying it, so task 2 binds
  to the tree task 1 left. A bad plan blocks with a precise reason instead of
  retrying: `plan_path_not_found`, `plan_path_not_authorized`,
  `plan_find_not_found`, `plan_find_not_unique` — fix the text and re-run.
- One small change, no run needed:
  `simplicio-dev-cli edit --plan ops.json --compile plan.json` →
  `simplicio-dev-cli edit --plan plan.json --apply --json` →
  `simplicio-dev-cli test --json`.
- **Never** `simplicio-dev-cli task "prose"` (answers `plan_required`).
- Every command answers `--help`; read it before guessing a flag.

## Task file (`tasks.md`)

One block per task; blocks are separated by a new `System:` line.

```markdown
System: calc
Feature: add mul(a, b)
Type: Feature

AS a calc user
I WANT a mul(a, b) function in calc/ops.py
SO THAT I can multiply numbers

1. Acceptance Criteria

Scenario 1: mul multiplies two numbers
  Given calc/ops.py
  When I call mul(3, 4)
  Then it returns 12 and tests/test_ops.py has a test_mul test [RN01]

2. Business Rules

RN01 – mul lives in calc/ops.py next to add and sub.

8. Additional Information

Independent verifier: `python3 -m pytest -q`
Unit verifier: `python3 -m pytest -q tests/unit`
Integration verifier: `python3 -m pytest -q tests/integration`
System verifier: `python3 -m app --smoke`
Regression verifier: `python3 -m pytest -q tests/regression`
Benchmark verifier: `python3 bench.py`
Coverage verifier: `python3 -m pytest -q --cov=calc --cov-report=term`
```

- `Independent verifier:` is the command the watcher runs to prove the
  acceptance criteria.
- One `<Lane> verifier:` per quality lane: the loop runs each in the repo and
  builds `quality-matrix.json` from what it measured (implementation comes from
  the applied Dev CLI receipts; coverage is the last `NN%` the coverage command
  prints, minimum 85%). A lane without a command blocks and names the line to add.
  Lanes run **concurrently** (`asyncio.gather`), once at wave end on the
  integrated tree — not per task and not one lane after another.
- `Type: Docs|Chore|Config`, or an explicit `Tests: none` line, waives the
  lane matrix for that task: implementation (the applied receipt) plus its
  `Independent verifier:`, if declared, are the whole story — no
  unit/integration/system/regression/benchmark/coverage line is required or
  blocks. `Type: Feature|Bug|Fix|Refactor` (or no `Type:` header at all) keeps
  every lane mandatory, exactly as before. In a mixed wave, one task that
  needs the matrix means the whole batch still measures it
  (`simplicio_loop/lane_verifiers.py::lanes_required`).

## Wave: parallel worktrees, serial integration

`wave` runs each disjoint-path lane of tasks concurrently in its own git
worktree (`asyncio.Semaphore(min(cpu_count, lanes))`), then integrates every
lane's result back into the main repo **serially, in task order** — the only
step allowed to touch the shared tree. Two tasks whose edit-plan paths
overlap stay in the same lane, in order, so one file is never raced.
A lane whose patch no longer applies (the tree moved under it during
integration) falls back to a serial re-run of that lane's edit-plan directly
on the now-integrated tree — the same "compile binds to the tree the
previous task left" contract as `edit-plan-<N>.json`, just recovered instead
of blocked. Worktrees and lane branches are removed once integration
finishes. Implementation: `simplicio_loop/wave_worktree.py`
(`group_disjoint_tasks`, `run_worktree_wave`, `integrate_lane_results`).

Mapper + Fast survey the **default branch** (`origin/HEAD`, falling back to
the current `HEAD`) once per commit SHA; every worker in the wave reuses that
one cached survey read-only instead of re-running it
(`wave_worktree.ArtifactCache`, keyed by the default-branch SHA). A worker
never re-surveys; a missing/stale cache rebuilds once, centrally — the same
"workers never rebuild canonical artifacts" rule as `CLAUDE.md`'s central
artifact rule.

**Effort guidance for the host LLM**: planning/decomposition (turning the
goal into `tasks.md`'s per-task ACs and dependencies) deserves *high* effort —
mistakes there fan out into every worker. Executing one worker's edit-plan is
mechanical and deserves *low* effort. Reviewing/verifying a wave's result
(reading the quality matrix, the reconciled diff, the oracle verdict) is
*medium* effort — enough to catch a false pass, not enough to re-derive the
whole plan.

## Done

`wave`/`tick` verify automatically; `simplicio-loop verify <run_id>` re-runs it.
Done = run `phase: done`, completion `VERIFIED`/`MEASURED`: the watcher measured
every criterion and every lane passed. The loop then records the exact
`<promise>` in `loop/last_response.txt`; emit it only after that, in the same turn.

## GitHub source of truth

When the remote is GitHub, GitHub is the coordination SoT: Issues, PR comments,
checks, merge path. Re-query live state before closing. Do not substitute another
tracker unless the user asks.

## Contract

1. Evidence-gated exit. No in-turn evidence → no promise.
2. Exact sentinel `<promise>EXACT TEXT</promise>` matching `completion_promise`.
3. `max_iterations` is mandatory before iteration 1.
4. Scratchpad `.simplicio/orchestrator/loop/scratchpad.md` is the agent SoT:

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

5. Review: **1 implement + 1 verify**. No 3–4 reviewer panels on ordinary diffs.

## Drive

Hook hosts (Claude/Cursor): capture + stop hooks re-feed the goal and print the
progress header. Self-paced hosts: re-read the scratchpad every turn; triage →
decide → operate → verify.

Every turn's first line is the `loop_progress.py render --turn-header` line
(the N2 progress contract; see `references/progress-feedback.md`).

End every message: `DONE | NEXT | BLOCKED`.

<!-- SIMPLICIO-LLM-ORIENTATION:BEGIN -->
Loop orientation:
- Stack: mapper + fast + simplicio-dev-cli + loop. No Runtime. No MCP force.
- GitHub is SoT for issues/PRs when the remote is GitHub.
- Context: simplicio-loop orient --task "<goal>" --json (Mapper + Fast).
- Run: simplicio-loop prepare --task tasks.md → write edit-plan-<N>.json → wave <run_id> → verify <run_id>.
- edit-plan-<N>.json = {"operations": [{"path","find","replace"}]}; find must match exactly once.
- Never simplicio-dev-cli task "prose". No plan → plan_required (do not call OpenRouter).
- Review: 1 implement + 1 verify. Promise only after verify MEASURED.
- End: DONE | NEXT | BLOCKED.
<!-- SIMPLICIO-LLM-ORIENTATION:END -->

## Bounded delivery

One implementation issue and one delivery PR per worker. Freeze ACs before
mutation. Findings: `AC_BLOCKER` / `REGRESSION_BLOCKER` / `FOLLOW_UP`. Only
blockers hold the current delivery.

## Guardrails

- Do not invent MEASURED numbers.
- Do not close issues without a live GitHub re-query.
- Do not hand-edit source as the primary mutation path; write the edit plan.
- Parallelism: 1–3 tasks direct; >3 Prism. Writes serialized.
