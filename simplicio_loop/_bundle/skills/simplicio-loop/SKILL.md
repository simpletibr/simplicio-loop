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

On invocation, start the engine. Do not survey the repository by hand. Any repository via `--repo <path>`.

Monorepo stays: `packages/mapper`, `packages/dev-cli`, loop at the root. No Runtime. No Fast package.

Self-referential iteration: the SAME goal is re-fed each turn. Exit ONLY when the typed `<promise>…</promise>` is true **and** in-turn evidence exists, or when `max_iterations` fires. Credit: Ralph Wiggum / cursor `ralph-loop`.

The host LLM writes find/replace text (`simplicio.dev-cli.edit-plan/v1`). The engine applies it. The loop never calls a provider to generate diffs.

## GitHub source of truth

When the remote is GitHub, GitHub is the coordination SoT: Issues, PR comments, checks, merge path. Re-query live state before closing. Do not substitute another tracker unless the user asks.

## Fast deterministic path

The fast deterministic path is `orient --brief` then `apply`.

```bash
simplicio-loop orient --brief --repo <path> --task "<task>" [--task "<task 2>" ...] --json --tee
simplicio-loop apply .simplicio-loop/ops.json --repo <path> --json
```

- That first call is the survey. It returns the route, target contents, and plan groups. Do not explore the tree before it, and do not re-run it when the brief already answered.
- The Mapper survey is cached and a second call on an unchanged tree reuses it (git tree id plus the working-tree dirty hash).
- `--tee` stores the JSON in the tee cache. `simplicio-loop retrieve` reads that object back.
- `.simplicio-loop/ops.json` is `{"tasks":[{"id","operations":[{"path","find","replace"}],"check","depends_on"}],"repo_state_chain":"<copy from the brief>"}`. A `find` must match exactly once; `""` creates a new file.
- `simplicio-loop apply` validates every `find` before writing, applies through `simplicio-dev-cli`, and runs independent checks concurrently. PASS means those checks already ran.

## Drain path

The drain path is `prepare` → edit plans → `wave` → `verify`.

```bash
simplicio-loop orient --repo <path> --task "<goal>" --json --tee
simplicio-loop prepare --task tasks.md --repo <path>
# .simplicio-loop/loop-runs/<run_id>/edit-plan-<N>.json
# {"operations":[{"path":"<file>","find":"<exact text, unique in file>","replace":"<new text>"}]}
simplicio-loop wave <run_id> --repo <path>
simplicio-loop verify <run_id> --repo <path>
```

Disjoint lanes run together with asyncio and the wave finishes only when every lane has integrated or failed closed. Paths that overlap stay in one lane and run in order. Integration back into the shared tree is serial.

`find: ""` creates a missing file and never overwrites an existing non-empty file. **Never** `simplicio-dev-cli task "prose"` (answers `plan_required`).

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

Journal: `.simplicio-loop/orchestrator/loop/journal.jsonl`. `simplicio-loop verify` re-runs the watcher and the delivery gates. Done means phase `done` and completion `VERIFIED` or `MEASURED`. Emit the promise only after that, in the same turn.

## Drive

Hook hosts (Claude/Cursor): capture + stop hooks re-feed the goal.
Self-paced hosts: re-read the scratchpad every turn; triage → decide → operate → verify → journal.

Wave and governed runs: every turn's first line is `python3 scripts/loop_progress.py render --turn-header`. The fast path skips the scratchpad.

End every message: `DONE | NEXT | BLOCKED`.

<!-- SIMPLICIO-LLM-ORIENTATION:BEGIN -->
Loop orientation:
- On invocation, start the engine. Any repository via `--repo <path>`.
- Monorepo stays: packages/mapper, packages/dev-cli, loop at the root. No Runtime. No Fast package.
- Fast deterministic path: simplicio-loop orient --brief then simplicio-loop apply.
- Drain path: prepare → edit plans → simplicio-loop wave → simplicio-loop verify.
- The Mapper survey is cached and a second call on an unchanged tree reuses it. `--tee` stores the JSON in the tee cache.
- Disjoint lanes run together with asyncio and the wave finishes only when every lane has integrated or failed closed.
- GitHub is SoT for issues/PRs when the remote is GitHub.
- Never simplicio-dev-cli task "prose". No plan → plan_required.
- Review: 1 implement + 1 verify. Promise only after verify MEASURED.
- End: DONE | NEXT | BLOCKED.
<!-- SIMPLICIO-LLM-ORIENTATION:END -->

## Bounded delivery

One implementation issue and one delivery PR per worker. Freeze ACs before mutation. Findings: `AC_BLOCKER` / `REGRESSION_BLOCKER` / `FOLLOW_UP`. Only blockers hold the current delivery.

## Guardrails

- Do not invent MEASURED numbers.
- Do not close issues without a live GitHub re-query.
- Do not hand-edit source as the primary mutation path; write the edit plan and let the engine apply it.
- Parallelism: 1–3 tasks direct; >3 Prism. Writes serialized.

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
