# simplicio-loop

**The Universal Looping AI Orchestrator** — a runtime-agnostic **super-plugin** (7 skills) that
drains any queue of work end-to-end on **any LLM / runtime**:
`discover → implement → verify → merge → close → watch 24/7`, behind safety gates and evidence
checks, at up to **96% fewer tokens**. Not a chatbot. A worker.

![simplicio-loop](https://raw.githubusercontent.com/wesleysimplicio/simplicio-loop/main/assets/simplicio-loop-hero-2026.png)

## Install

```bash
pip install simplicio-loop
```

One wheel: mapper and dev-cli are built in, so it also provides the two required operators,
`simplicio-mapper` and `simplicio-dev-cli`. Update later with `simplicio-loop update`.

Then drop the skills + hooks into your project (or globally):

```bash
simplicio-loop install            # into ./.claude of the current project
simplicio-loop install --global   # into ~/.claude (all projects)
```

Now invoke it from your agent runtime (Claude Code, Cursor, Codex, Gemini, …):

```
/simplicio-loop finish all the open issues
```

## What you get — 7 skills

| Skill | What it does |
|---|---|
| `simplicio-loop` | Unified public entrypoint: orchestrator core + hardened loop behind one command. |
| `simplicio-tasks` | Legacy alias kept only for compatibility with older installs and saved prompts. |
| `simplicio-orient` | Terminal-first token economy — output-reduction catalog, tee-cache, signatures-read. |
| `simplicio-review` | Adversarial review — parallel subagents on distinct rubrics, deduped into one verdict. |
| `simplicio-compress` | Output + memory compression, byte-preserving identifiers. |
| `simplicio-autoresearch` | Evolutionary mutate/eval/keep-revert optimizer — yool-guardrailed caps, git-isolated branch, anti-Goodhart gate-first eval. |
| `simplicio-learn` | Retrospective — durable, deduped lessons written back to memory. |

## Highlights

- **35 runtimes, one protocol** — Claude Code, Codex, Cursor, VS Code/Copilot, Gemini, Kiro, OpenCode,
  Amp, Cline, Continue, Droid, goose, Aider, Simplicio Agent (formerly Hermes), OpenClaw, Orca and more; the
  full list is `adapters/MATRIX.md` in the repository.
- **Evidence-gated completion** — never a false "done"; exits only on a verified `<promise>`,
  cap, spindle handoff, or STOP.
- **Token economy** — honest "answer concisely" baseline; savings credited only on verified-correct
  outcomes.

Requires Python 3.11+. Mapper and dev-cli ship inside this wheel, so there are no separate
`simplicio-mapper` / `simplicio-cli` packages to install. The package remains
pure cross-platform Python.

MIT — part of the [Simplicio](https://github.com/wesleysimplicio) ecosystem.
Full docs: <https://github.com/wesleysimplicio/simplicio-loop>
