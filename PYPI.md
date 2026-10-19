# simplicio-loop

**Deterministic operators any agent harness can call, plus a loop that drives them.**
`simplicio-mapper` surveys a repo, `simplicio-dev-cli` applies an edit plan exactly, and
impact-based test selection (`scripts/impact_tests.py`, used by `scripts/check.py`) runs only the
tests a change can reach. None of them provisions a model. The loop (a **super-plugin** of 7 skills) is
one consumer of them: it drains a queue of work end-to-end,
`discover → implement → verify → merge → close → watch 24/7`, behind safety gates and evidence
checks. Not a chatbot. A worker. No headline token-savings percentage is claimed: savings are
reported only when measured (see [`bench/llm_ab`](https://github.com/wesleysimplicio/simplicio-loop/tree/main/bench/llm_ab),
a small A/B on a single model).

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

Now invoke it from a wired host (Claude Code, Codex, Cursor, Grok, Kiro or VS Code):

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

- **Operators as tools** — `simplicio-mapper handoff . --goal "<task>" --json` for the survey,
  `simplicio-dev-cli edit --root . --plan plan.json --apply --json` for the exact edit, and
  `python3 scripts/impact_tests.py --base origin/main --json` (a repo-checkout script) for the tests a
  change can reach. Any harness that can run a command can call them.
- **Honest runtime counts** — 34 wired adapters (code and a host test in the repository: Claude Code,
  Codex, Cursor, Grok, Kiro, VS Code, the 20 AGENTS.md hosts and the eight wave-B hosts) and 0 listed hosts (every
  catalog host has adapter code). DeepSeek is a model provider, not a host. Per-host status is `adapters/MATRIX.md` in
  the repository.
- **Evidence-gated completion** — never a false "done"; exits only on a verified `<promise>`,
  cap, spindle handoff, or STOP.
- **Token economy** — honest "answer concisely" baseline; savings credited only on verified-correct
  outcomes, and never as an unmeasured headline number.

Requires Python 3.11+. Mapper and dev-cli ship inside this wheel, so there are no separate
`simplicio-mapper` / `simplicio-cli` packages to install. The package remains
pure cross-platform Python.

MIT — part of the [Simplicio](https://github.com/wesleysimplicio) ecosystem.
Full docs: <https://github.com/wesleysimplicio/simplicio-loop>
