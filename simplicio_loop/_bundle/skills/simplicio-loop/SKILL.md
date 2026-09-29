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

A task is ONE command: `simplicio-loop "<task>" [--verify "<test command>"]`, the short form of
`simplicio-loop turbo --repo <path> --task "<task>"`. It runs the Mapper survey,
the model through your own CLI, `simplicio-dev-cli` and `--verify`, and prints one JSON result. There is no provider call and
no API key. `status: "ok"` or `"failed"` (`mode: "hybrid"`) is final: report it as printed.

Only when it prints `status: "needs_plan"` (`mode: "host"`, with a `reason`) you plan: `tasks` (what is left; `applied` is
done), `map`, the current text of the files it names (`files`), `format`, `rules` and the exact `apply` command. Run that
command once, your plan as its heredoc body:

   ```bash
   simplicio-loop turbo --repo <path> --apply - --verify "<test command>" <<'PLAN'
   {"operations":[{"path":"<file>","find":"<text from files, occurs once>","replace":"<new text>"}]}
   PLAN
   ```

   An empty `find` creates the file. dev-cli applies the plan, then `--verify` runs: `status` (`ok` or `failed`), `applied`,
   `failed` (dev-cli reason and file excerpt), `verify`.

Nothing else. Do not explore, list or read files: the request holds their text (name every file to change in
the task text, or pass `--target`/`--context` with one `--task`). Do not run tests yourself: `--verify` does;
pass the test command you already know, never search for one. Do not run `--help`, `simplicio-mapper` or
`simplicio-dev-cli`, and do not write a plan file, a scratchpad, a journal or a turn header. Never hand-edit; the
plan is the edit. On `status: "failed"`, fix the plan once from `reason` and `excerpt` (or the `verify` output)
and run the `apply` command printed with it. Several requests: one `--task` each.
Allow the one command once so the host never prompts: OpenCode `permission.bash` rule `"simplicio-loop *": "allow"` in
`opencode.json`, Claude Code `Bash(simplicio-loop:*)`. That one approval covers everything the engine runs inside it.
`.simplicio-loop/` is local run state: keep it in `.gitignore` (the engine adds it when the file exists) and never commit it.

Goal over a queue ("all open issues", "drain the board"): one such command per item, in order; the orientation block below
has the recipe. Done only on `status: "ok"` plus a passing verify.

## Done

Done = `status: "ok"` and, when `--verify` was given, `verify.passed: true`. Report `applied`, `failed` and
`verify` as printed, then end with `DONE`. Emit the `<promise>` only after that, in the same turn, and only
when a loop is armed.

## Loop

Queue goals and re-fed goals only; a task run needs none of it. The SAME goal is re-fed each turn. Exit ONLY
when the typed `<promise>…</promise>` is true **and** in-turn evidence exists, or when `max_iterations` fires.
Credit: Ralph Wiggum / cursor `ralph-loop`.

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

Armed loop only: every turn's first line is `python3 scripts/loop_progress.py render --turn-header`; skip it when the script is missing.

End every message: `DONE | NEXT | BLOCKED`.

<!-- SIMPLICIO-LLM-ORIENTATION:BEGIN -->
Loop orientation:
- A task is ONE command: `simplicio-loop "<task>" [--verify "<tests>"]`, short for `simplicio-loop turbo --repo <path> --task "<task>"` (no key, no provider): Mapper, the model through the host's own CLI, dev-cli edits and `--verify`. `status ok` or `failed` is final: report it as printed.
- Only on `needs_plan`: run the request's `apply` command once, your JSON plan as its heredoc body (`... --apply - <<'PLAN'`); `find` is copied from the printed text. dev-cli makes every edit; never hand-edit.
- Do not explore, list or read files, and do not run tests yourself (`--verify` does). No plan file, scratchpad, journal or turn header for a task run.
- On `failed`, fix the plan once from the reported reason and apply again.
- Queue goal (all open issues, drain the board): list the items (`gh issue list --state open --json number,title,body`), run `simplicio-loop turbo --repo <path> --task "<title>: <body>" --verify "<tests>"` per item, in order (name the files when the item names them), and the printed `apply` on `needs_plan`; one CLAIMED issue and one PR per item.
- `.simplicio-loop/` is local run state: keep it in `.gitignore` (the engine adds it when the file exists) and never commit it.
- Done = status ok and, when `--verify` was given, verify passed. Promise only after that.
- One monorepo: packages/mapper surveys, packages/dev-cli applies. Do not install those as external projects. No Runtime. No Fast package.
- GitHub is SoT for issues/PRs when the remote is GitHub.
- Review: 1 implement + 1 verify.
- End: DONE | NEXT | BLOCKED.
<!-- SIMPLICIO-LLM-ORIENTATION:END -->

## Bounded delivery

For queue goals: one implementation issue and one delivery PR per worker. Freeze the goal before mutation. Findings: `AC_BLOCKER` / `REGRESSION_BLOCKER` / `FOLLOW_UP`. Only blockers hold the current delivery.

## Guardrails

- Do not invent MEASURED numbers.
- Do not close issues without a live GitHub re-query.
- Do not hand-edit source: the plan is the edit, `simplicio-loop turbo --apply -` lets dev-cli apply it.

Armed loops and queues only: the full per-turn protocol is `references/full-flow.md`; a task run never needs it.

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
