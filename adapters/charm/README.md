# Charm adapter

Charm's Crush includes `AGENTS.md` among its default context files. Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh charm     # macOS / Linux
pwsh scripts/install.ps1 charm    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `AGENTS.md`, which Crush reads as project context (`crush init` creates one). The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

- Crush also loads skills from the project's `.claude/skills/`, so the skills copy is also a native skill install.
- Global context lives in `~/.config/AGENTS.md`; the installer does not write there.

Documentation for this surface: <https://github.com/charmbracelet/crush>

## Loop drive

Self-paced: the installer wires no stop hook for Charm. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through Charm's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where Charm runs its shell (`pip install simplicio-loop`).
