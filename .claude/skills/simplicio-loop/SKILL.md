---
name: simplicio-loop
description: "Ralph loop for mapper + simplicio-dev-cli. Same goal every turn; exit only on an evidence-gated promise or max_iterations. GitHub is SoT for issues/PRs. Invoking it runs simplicio-loop turbo."
---

<!-- simplicio-contract:begin -->
contract: simplicio-loop
schema: simplicio.skill/v1
purpose: Ralph loop for mapper + simplicio-dev-cli: same goal every turn, exit only on an evidence-gated promise or max_iterations.
rules: Follow this skill end-to-end; mutable data (versions, dates, counts) lives in the footer, never in this header.
<!-- simplicio-contract:end -->

# /simplicio-loop

On invocation, run the turbo engine. It is the path the benchmark measures,
and every host runs the same command:

```bash
simplicio-loop turbo --repo <path> --task "<task>" [--task "<task 2>" ...] [--verify "<test command>"]
```

- Put the whole request in `--task` and name every file to create or change
  in the text (or pass `--target`/`--context` with a single `--task`), so the
  model sees its current content. Several requests: one `--task` each, in one
  command.
- Do not explore the tree, write plans, or edit files yourself, and do not
  call `simplicio-mapper scan`, `inspect`, or `handoff` by hand.
- Turbo is the default. Mapper reads the repo once. That project map is the
  header and stays byte-identical on every call; the task text and the current
  target file are the suffix. The model (`deepseek/deepseek-v4.1-flash` on
  OpenRouter, pinned session, reasoning off) returns a find/replace plan and
  `simplicio-dev-cli` applies it. A rejected plan is sent back once, then turbo
  stops. Up to three tasks share one model call. Above three tasks the first
  call runs alone, then the rest fan out and read the header from prompt cache.
  Tasks on the same file stay in order.
- It needs `OPENROUTER_API_KEY`. Without it the command prints
  `status: blocked` with `reason_code: turbo_provider_key_missing`: tell the
  user to export the key, and stop. Never fall back to hand edits.
- It prints one JSON document: `status` (ok, failed or blocked), `applied`,
  `failed` with the dev-cli reason, `model_calls`, `retries`, tokens,
  `cache_hit_pct`, `cost_usd`, `wall_s`, and `verify`. Report those numbers as
  printed.
- On `failed`, re-run once with a sharper `--task` that names the file and the
  exact change, then report.
- Pass the project's tests as `--verify` whenever the repository has them.

One monorepo. `packages/mapper` surveys and `packages/dev-cli` applies.
Do not install those as external projects. No Runtime. No Fast package.
`orient` is the Mapper survey. It is cached: a second call on an unchanged
tree reuses it. `--tee` stores the JSON in the tee cache.

Self-referential iteration: the SAME goal is re-fed each turn. Exit ONLY when
the typed `<promise>…</promise>` is true **and** in-turn evidence exists, or
when `max_iterations` fires. Credit: Ralph Wiggum / cursor `ralph-loop`.

## Done

Done = `status: "ok"` and, when `--verify` was given, `verify.passed: true`.
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
- On invocation, run `simplicio-loop turbo --repo <path> --task "<task>" [--verify "<tests>"]`. One command for one task and for many: one `--task` each.
- It needs `OPENROUTER_API_KEY`. Without it the command prints status blocked (`turbo_provider_key_missing`): tell the user, stop. No fallback to hand edits.
- Do not write plans or edit files yourself. Do not explore the tree.
- Done = status ok and, when `--verify` was given, verify passed. Promise only after that.
- Monorepo: packages/mapper, packages/dev-cli, loop at the root. Do not install them as external projects. No Runtime. No Fast package.
- GitHub is SoT for issues/PRs when the remote is GitHub.
- Review: 1 implement + 1 verify.
- End: DONE | NEXT | BLOCKED.
<!-- SIMPLICIO-LLM-ORIENTATION:END -->

## Bounded delivery

One implementation issue and one delivery PR per worker. Freeze the goal before mutation. Findings: `AC_BLOCKER` / `REGRESSION_BLOCKER` / `FOLLOW_UP`. Only blockers hold the current delivery.

## Guardrails

- Do not invent MEASURED numbers.
- Do not close issues without a live GitHub re-query.
- Do not hand-edit source. Run simplicio-loop turbo.

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
