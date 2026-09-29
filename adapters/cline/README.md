# Cline adapter

Cline reads `AGENTS.md` natively, next to its own `.clinerules/` rules. Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh cline     # macOS / Linux
pwsh scripts/install.ps1 cline    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `AGENTS.md`, which Cline reads alongside `.clinerules/`. The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

- The cross-tool global file is `~/.agents/AGENTS.md`; the installer does not write there.

Documentation for this surface: <https://docs.cline.bot/customization/cline-rules>

## Loop drive

Self-paced: the installer wires no stop hook for Cline. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through Cline's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where Cline runs its shell (`pip install simplicio-loop`).
