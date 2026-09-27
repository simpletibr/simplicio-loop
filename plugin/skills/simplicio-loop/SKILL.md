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

Self-referential iteration: the SAME goal is re-fed each turn. Exit ONLY when the
typed `<promise>…</promise>` is true **and** in-turn evidence exists, or when
`max_iterations` fires. Credit: Ralph Wiggum / cursor `ralph-loop`.

Public stack (one monorepo): `simplicio-mapper`, `simplicio-dev-cli`,
`simplicio-loop`. **No Runtime. No MCP force. No `SIMPLICIO_LOOP_REQUIRE_RUNTIME`.**
The host LLM writes `simplicio.dev-cli.edit-plan/v1`. Loop never calls a provider
to generate diffs.

## GitHub source of truth

When the remote is GitHub, GitHub is the coordination SoT: Issues, PR comments,
checks, merge path. Re-query live state before closing. Do not substitute another
tracker unless the user asks.

## Contract

1. Evidence-gated exit. No in-turn evidence → no promise.
2. Exact sentinel `<promise>EXACT TEXT</promise>` matching `completion_promise`.
3. `max_iterations` is mandatory before iteration 1.
4. Scratchpad `.simplicio-loop/orchestrator/loop/scratchpad.md` is the agent SoT.
5. Review: **1 implement + 1 verify**. No 3–4 reviewer panels on ordinary diffs.

## Hot path (mutate recipe)

```bash
simplicio-mapper scan . --json
simplicio-mapper inspect . --json --await
simplicio-mapper handoff . --goal "..." --token-budget 4000 --for-llm toon
simplicio-dev-cli edit --plan plan.json --apply --json
simplicio-dev-cli test --json
python3 scripts/watcher_verify.py verify
```

- Host writes `plan.json` (`simplicio.dev-cli.edit-plan/v1`).
- **Never** `simplicio-dev-cli task "prose"`. Missing plan → `plan_required`.
- Promise only after watcher + test MEASURED in the same turn.

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

Journal: `.simplicio-loop/orchestrator/loop/journal.jsonl`. Watcher:
`python3 scripts/watcher_verify.py verify` writes `watcher_state.json` — never
hand-write it.

## Drive

Hook hosts (Claude/Cursor): capture + stop hooks re-feed the goal.
Self-paced hosts: re-read the scratchpad every turn; triage → decide → operate
→ verify → journal.

Every turn's first line is `python3 scripts/loop_progress.py render --turn-header`.

End every message: `DONE | NEXT | BLOCKED`.

<!-- SIMPLICIO-LLM-ORIENTATION:BEGIN -->
Loop orientation:
- Stack: mapper + simplicio-dev-cli + loop (one monorepo). No Runtime. No MCP force.
- GitHub is SoT for issues/PRs when the remote is GitHub.
- Survey: mapper scan → inspect → handoff(--token-budget 4000). Context = handoff.
- Host writes simplicio.dev-cli.edit-plan/v1. Apply: simplicio-dev-cli edit --plan --apply.
- Never simplicio-dev-cli task "prose". No plan → plan_required (do not call OpenRouter).
- Review: 1 implement + 1 verify. Promise only with watcher + test MEASURED.
- End: DONE | NEXT | BLOCKED.
<!-- SIMPLICIO-LLM-ORIENTATION:END -->

## Bounded delivery

One implementation issue and one delivery PR per worker. Freeze ACs before
mutation. Findings: `AC_BLOCKER` / `REGRESSION_BLOCKER` / `FOLLOW_UP`. Only
blockers hold the current delivery.

## Guardrails

- Do not invent MEASURED numbers.
- Do not close issues without a live GitHub re-query.
- Do not hand-edit source as the primary mutation path; apply the host plan.
- Parallelism: 1–3 tasks direct; >3 Prism. Writes serialized.

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
