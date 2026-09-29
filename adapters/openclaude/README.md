# OpenClaude adapter

OpenClaude (an open-source coding-agent CLI for any model provider) reads `AGENTS.md` as its primary project instruction file. Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh openclaude     # macOS / Linux
pwsh scripts/install.ps1 openclaude    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `AGENTS.md`, which OpenClaude finds in the working directory or an ancestor (`CLAUDE.md` is used only when there is no `AGENTS.md`). The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

- OpenClaude keeps its own config under `~/.openclaude` and does not read `.claude/`, so the skills load through the block's pointer, not as native skills.

Documentation for this surface: <https://github.com/Twigpine/openclaude/blob/main/src/utils/projectInstructions.ts>

## Loop drive

Self-paced: the installer wires no stop hook for OpenClaude. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through OpenClaude's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where OpenClaude runs its shell (`pip install simplicio-loop`).
