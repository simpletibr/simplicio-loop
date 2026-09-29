# Autohand Code adapter

Autohand Code loads a global `~/.autohand/AGENTS.md`, then the `AGENTS.md` at the project root. Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh autohand     # macOS / Linux
pwsh scripts/install.ps1 autohand    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `AGENTS.md`, which Autohand always loads. The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

- Skills of its own live in `.autohand/skills/`.

Documentation for this surface: <https://docs.autohand.ai/working-with-autohand-code/agents-md>

## Loop drive

Self-paced: the installer wires no stop hook for Autohand Code. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through Autohand Code's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where Autohand Code runs its shell (`pip install simplicio-loop`).
