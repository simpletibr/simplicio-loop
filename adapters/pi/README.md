# Pi adapter

Pi (the `pi` coding agent) loads `AGENTS.md` or `CLAUDE.md` context files from its agent directory, the working directory and the parent directories. Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh pi     # macOS / Linux
pwsh scripts/install.ps1 pi    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `AGENTS.md`, which Pi loads from the working directory and its parents (an `AGENTS.override.md` in the same directory replaces it). The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

- User-level instructions live in `~/.pi/agent/AGENTS.md`; the installer does not write there.
- Pi also scans `.pi/skills/` and `.agents/skills/` for skills.

Documentation for this surface: <https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/configuration.md>

## Loop drive

Self-paced: the installer wires no stop hook for Pi. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through Pi's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where Pi runs its shell (`pip install simplicio-loop`).
