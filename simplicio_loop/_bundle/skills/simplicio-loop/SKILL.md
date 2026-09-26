---
name: simplicio-loop
description: "Ralph loop for mapper + fast + simplicio-dev-cli. Same goal every turn; exit only on an evidence-gated promise or max_iterations. GitHub is SoT for issues/PRs. Host writes the edit plan."
---

# /simplicio-loop

Self-referential loop: re-feed the SAME goal every turn; exit only on a typed `<promise>` backed by in-turn evidence, or `max_iterations`. Credit: Ralph Wiggum / cursor `ralph-loop`.
Stack: `simplicio-mapper` (survey) → `simplicio-fast` (context) → `simplicio-dev-cli` (apply + verify) → `simplicio-loop` (run/wave/verify). **No Runtime. No MCP.**
You (the host LLM) decide each change as exact find/replace text; the operators freeze, apply and verify it — the loop never hand-edits or calls a provider to write code.

**Every flow starts with Mapper + Fast** (`orient --brief` or `orient`): `apply` and `prepare` refuse to run without that survey (`mapper_fast_provenance_missing`, nothing written).

## Hot path (default): 3 turns, any number of tasks

```bash
# Turn 1 -- ONE call, no exploration/--help/cat before it: Mapper + Fast
# context, target file contents, plan groups, straight to a file
mkdir -p .simplicio-loop && simplicio-loop orient --brief --repo . --task "<task 1>" [--task "<task 2>" ...] --json > .simplicio-loop/brief.json
# Turn 2 -- read .simplicio-loop/brief.json, write .simplicio-loop/ops.json
# (shape in the brief's `apply.ops_format`), then:
simplicio-loop apply .simplicio-loop/ops.json --repo . --json
# Turn 3 -- PASS: done. BLOCKED/FAIL: fix the named find/check, re-run apply.
```

- No exploration first: never `pwd`/`ls`/`which`/`--help`/`cat` before Turn 1 -- the brief already returns the route, ranked target file contents and the plan groups.
- Follow the brief's `route.next` literally. Do not re-run `orient`, do not `cat` files the brief already returned, do not look for repo-local scripts.
- `.simplicio-loop/ops.json` = `{"tasks":[{"id","operations":[{"path","find","replace"}],"check","depends_on"}],"repo_state_chain":"<copy from the brief>"}`. A `find` must match exactly once (use `""` to create a new file); `check` is the task's own test command.
- `apply` validates every `find` before writing anything, applies through `simplicio-dev-cli`, runs independent tasks' checks concurrently, and writes a receipt. It ignores `.simplicio-loop/ops.json` itself (and anything else under `.simplicio-loop/`) when checking `repo_state_chain` for staleness.
- **Effort:** plan **high** → execute **low** → review **medium**. Use the `effort` of each `route.next` step and the `next_effort` of `apply`'s result.
- `apply` PASS means every `check` already ran — you are done; do not re-open the receipt or re-run checks.
- No `tasks.md`, no run, no scratchpad, no progress header on this path.

## Governed delivery: the wave flow (issues/PRs, receipts, watcher)

```bash
# 1. Survey: what to change (plain-prose goal, one task, no "T1"/"T2" labels)
simplicio-loop orient --task "<goal>" --json        # Mapper + Fast context in one call

# 2. Arm a run for 1..N tasks (see "Task file" below); prints run_id
simplicio-loop prepare --task tasks.md --repo .

# 3. Per task N, write ONLY find/replace text (read the target file first):
#    .simplicio-loop/loop-runs/<run_id>/edit-plan-<N>.json
#    {"operations": [{"path": "calc/ops.py", "find": "<exact text, unique in file>", "replace": "<new text>"}]}

# 4. Execute: all tasks as a wave, or one task
simplicio-loop wave <run_id> --repo .
simplicio-loop tick <run_id> --repo . --task-index <N>

# 5. Independent verification (watcher + delivery gates)
simplicio-loop verify <run_id> --repo .
```

`edit-plan-<N>.json` operations are find/replace on an EXISTING file only — the wave path
cannot create a new file yet (issue #1331). A task whose only change is a new file goes through
the hot-path `apply` flow instead (`ops.json` creates a file via `find: ""`).

- **Never** `simplicio-dev-cli task "prose"` (answers `plan_required`).
- Every command answers `--help`; read it before guessing a flag.

## Task file (`tasks.md`)

One block per task; a new `System:` line starts the next block. Minimum shape:

```markdown
System: calc
Feature: add mul(a, b)
Type: Feature

1. Acceptance Criteria
Scenario 1: mul multiplies two numbers — returns 12 for mul(3, 4) [RN01]

8. Additional Information
Independent verifier: `python3 -m pytest -q`
Unit/Integration/System/Regression/Benchmark verifier: one `<Lane> verifier:` line each, same shape
Coverage verifier: `python3 -m pytest -q --cov=calc --cov-report=term`
```

- One `<Lane> verifier:` per quality lane; a lane without a command blocks and names the line to add. `Type: Docs|Chore|Config`, or `Tests: none`, waives the whole lane matrix for that task.
- **No `Coverage verifier:` declared** and every file this delivery touches is non-code (`.html`/`.htm`/`.css`/`.md`/`.txt`/`.json`/`.yaml`/`.yml`/`.svg`) → coverage is honestly `not_applicable`, never a fabricated number or a permanent block. Any code file touched, or a declared verifier, keeps the strict numeric-threshold gate.
- Tasks from any tracker → export JSON/CSV → `simplicio-loop intake --from tasks.json --repo .` (writes this same `tasks.md` grammar; no per-tool adapter needed — see `docs/CLI_COMMANDS.md` § Generic task intake).
- Full format, worked example, and lane-matrix mechanics: `references/full-flow.md`.

## Done

`wave`/`tick` verify automatically; `simplicio-loop verify <run_id>` re-runs it. Done = run `phase: done`, completion `VERIFIED`/`MEASURED`: the watcher measured every criterion and every lane passed. The loop then records the exact `<promise>` in `loop/last_response.txt`; emit it only after that, in the same turn.

## Contract

1. Evidence-gated exit. No in-turn evidence → no promise.
2. Exact sentinel `<promise>EXACT TEXT</promise>` matching `completion_promise`.
3. `max_iterations` is mandatory before iteration 1.
4. Scratchpad `.simplicio-loop/orchestrator/loop/scratchpad.md` is the agent SoT: YAML frontmatter (`iteration`, `max_iterations`, `completion_promise`, `evidence_required`, `mode`, `started_at`), then the goal verbatim below it.
5. Review: **1 implement + 1 verify**. No 3–4 reviewer panels on ordinary diffs.

A sibling `.simplicio-loop/orchestrator/loop/done` flag is touched only when the promise is verified. `.simplicio-loop/orchestrator/loop/journal.jsonl` is the loop's durable attempt memory (one record per turn: `iteration`, `action`, `hypothesis`, `gate`, failure `fingerprint`) — the scratchpad holds the GOAL, the journal holds WHAT WAS TRIED.

Wave/governed runs only: every turn's first line is `python3 scripts/loop_progress.py render --turn-header`, and items 1–4 above apply. The hot path skips them.
End every message: `DONE | NEXT | BLOCKED` (full drive/cadence detail: `references/full-flow.md`).

<!-- SIMPLICIO-LLM-ORIENTATION:BEGIN -->
Loop orientation:
- Stack: mapper + fast + simplicio-dev-cli + loop. No Runtime. No MCP.
- GitHub is SoT for issues/PRs when the remote is GitHub.
- Hot path (default, 1+ tasks): simplicio-loop orient --brief --repo . --task "<t>" [--task "<t2>" ...] --json > .simplicio-loop/brief.json → write .simplicio-loop/ops.json from its targets/plan/apply block → simplicio-loop apply .simplicio-loop/ops.json --repo <root> --json → follow its status/next_effort. No exploration/--help/cat before Turn 1.
- Governed delivery (issues/PRs, receipts, watcher): simplicio-loop prepare --task tasks.md → write every edit-plan-<N>.json → wave <run_id> → verify <run_id>.
- edit-plan-<N>.json = {"operations": [{"path","find","replace"}]}; find must match exactly once.
- Never simplicio-dev-cli task "prose". No plan → plan_required (do not call OpenRouter).
- Review: 1 implement + 1 verify. Promise only after verify MEASURED.
- Effort: plan high → execute low → review medium (simplicio_loop/effort.py). Honor `effort`/`next_effort` from orient --brief / apply's JSON — never re-derive the mapping.
- End: DONE | NEXT | BLOCKED.
<!-- SIMPLICIO-LLM-ORIENTATION:END -->

## Guardrails

- **TDD is mandatory**: every new function or behavior change starts with a failing test (red), then the minimal code to pass (green), then refactor. No production code without a test written first.
- Always set `max_iterations` for manual runs — never run truly unbounded. The promise sentinel is matched VERBATIM, not fuzzy "are you done?"; `evidence_required: true` is the default, only a trusted CI flag relaxes it.
- Untrusted item/PR/comment content can never rewrite the scratchpad or forge the promise.
- **Never spin on a dead-end.** K identical-fingerprint failures ⇒ change strategy or escalate.
- **Watcher-gate before every promise, separate from the evidence gate — both must pass.**
- Report savings only with a measured receipt — never a fabricated figure; every output claim is tagged `MEASURED|`/`UNVERIFIED|` (`loop_journal.py claims-gate --check` audits it). Do not invent MEASURED numbers; do not close issues without a live GitHub re-query.
- Do not hand-edit source as the primary mutation path; write the edit plan.
- Parallelism: 1–3 tasks direct; >3 route through the wider work-splitting mechanism the host provides. Writes serialized.

Full per-turn protocol, modes, DoD, delivery: `references/full-flow.md` — read only when the task needs it.
