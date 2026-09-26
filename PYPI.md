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

- **12 runtimes, one protocol** — Claude Code, Codex, VS Code/Copilot, Cursor, Antigravity, Kiro,
  OpenCode, Gemini, Aider, Simplicio Agent (formerly Hermes), OpenClaw, Orca.
- **Evidence-gated completion** — never a false "done"; exits only on a verified `<promise>`,
  cap, spindle handoff, or STOP.
- **Token economy** — honest "answer concisely" baseline; savings credited only on verified-correct
  outcomes.

Requires Python 3.11+. The Loop dependency closure includes `simplicio-mapper`
and `simplicio-cli` (issue #1343 removed `simplicio-fast`); Python 3.11 is
therefore the honest minimum for an installed bundle. The package remains
pure cross-platform Python.

MIT — part of the [Simplicio](https://github.com/wesleysimplicio) ecosystem.
Full docs: <https://github.com/wesleysimplicio/simplicio-loop>
