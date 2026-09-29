# Goose adapter

goose loads `AGENTS.md` and `.goosehints` by default, at every level of the working directory hierarchy. Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh goose     # macOS / Linux
pwsh scripts/install.ps1 goose    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `AGENTS.md`, which goose loads by default. The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

- Global hints live in `~/.config/goose/.goosehints`.
- `CONTEXT_FILE_NAMES` changes which files goose reads; keep `AGENTS.md` in it.

Documentation for this surface: <https://goose-docs.ai/docs/guides/context-engineering/using-goosehints/>

## Loop drive

Self-paced: the installer wires no stop hook for Goose. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through Goose's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where Goose runs its shell (`pip install simplicio-loop`).
