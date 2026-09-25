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

- Write every `edit-plan-<N>.json` up front: the loop freezes each one
  (`simplicio-dev-cli edit --compile`) right before applying it, so task 2 binds
  to the tree task 1 left. A `find` that does not match exactly once blocks the
  task with `plan_compile_failed` — fix the text and re-run.
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

Independent verifier: `python3 -m pytest -q -p no:cacheprovider`
```

The `Independent verifier:` line is required: it is the command the watcher runs
to prove the acceptance criteria. Without it nothing can be verified.

## Done

"Done" = `simplicio-loop verify` reaches `phase: done`. It requires the watcher
to MEASURE every criterion **and** a `quality-matrix.json` in the run dir
(implementation, unit, integration, system, regression, benchmark + coverage;
see `references/quality-safety-delivery.md`). Promise only after that, in the
same turn.

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
