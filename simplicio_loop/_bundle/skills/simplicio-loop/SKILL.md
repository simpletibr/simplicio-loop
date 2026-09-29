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

On invocation, run the turbo engine. It is the path the benchmark measures, and every host runs the
same commands. You are the model that plans; `simplicio-dev-cli` makes every edit. There is no
provider call and no API key.

1. Run `simplicio-loop "<task>" [--verify "<test command>"]`. It is the short form of
   `simplicio-loop turbo --repo <path> --task "<task>" [--task "<task 2>" ...] [--verify "<test command>"]`.
   Mapper surveys the repo once and the command prints one JSON request, `status: "needs_plan"`:
   `prompt` (the map slice, the task and the current text of the files it names), `format`,
   `plan_path` and the exact `apply` command.
2. Write the plan to `plan_path` as `{"operations":[{"path","find","replace"}]}`. Copy `find` from the
   printed file text; it must occur once. An empty `find` creates the file.
3. Run the printed `apply` command. `simplicio-dev-cli` applies the plan, then `--verify` runs the tests.
4. On `status: "failed"`, fix the plan once from the reported `reason` and `excerpt` (or the `verify`
   output), run the same `apply` command again, then report.

- Put the whole request in `--task` and name every file to create or change in the text (or pass
  `--target`/`--context` with a single `--task`), so the request carries their current content.
  Several requests: one `--task` each, one plan for all.
- Never edit files by hand: dev-cli performs every edit. Do not explore the tree, and do not call
  `simplicio-mapper scan`, `inspect`, or `handoff` by hand.
- Goal over a queue ("all open issues", "drain the board"): list the items (GitHub:
  `gh issue list --state open --json number,title,body`). For each item, in order, run the two
  commands: `simplicio-loop turbo --repo <path> --task "<title>: <body>" --verify "<tests>"` (name the
  files when the item names them), then the printed `apply`. Follow Bounded delivery: one CLAIMED
  issue, one PR per item, done only on `status: "ok"` plus a passing verify.
- The apply step prints `status` (ok or failed), `applied`, `failed` with the dev-cli reason and a file
  excerpt, and `verify`. Report those as printed.
- Pass the project's tests as `--verify` whenever the repository has them.
- Only when the user asks for headless mode: `--provider openrouter` asks OpenRouter for the plan
  instead of you and needs `OPENROUTER_API_KEY` (`turbo_provider_key_missing` without it).

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
- On invocation, run `simplicio-loop "<task>" [--verify "<tests>"]`, short for `simplicio-loop turbo --repo <path> --task "<task>"`. No key, no provider: it prints a `needs_plan` request.
- You are the model: write the JSON plan to `plan_path` (`{"operations":[{"path","find","replace"}]}`, `find` copied from the printed text), then run the printed `apply` command. dev-cli makes every edit; never hand-edit.
- On `failed`, fix the plan once from the reported reason and apply again.
- Queue goal (all open issues, drain the board): list the items (`gh issue list --state open --json number,title,body`), run `simplicio-loop turbo --repo <path> --task "<title>: <body>" --verify "<tests>"` and the printed `apply` per item, in order; one CLAIMED issue and one PR per item.
- Do not explore the tree.
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
- Do not hand-edit source: write the plan, `simplicio-loop turbo --apply` lets dev-cli edit.

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
