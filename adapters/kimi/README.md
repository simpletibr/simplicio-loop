# Kimi adapter

Kimi Code CLI (Moonshot AI) builds its prompt from the workspace `AGENTS.md`; `/init` generates one. Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh kimi     # macOS / Linux
pwsh scripts/install.ps1 kimi    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `AGENTS.md`, which Kimi Code merges from the project root down to the working directory. The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

- Global instructions live in `~/.kimi-code/AGENTS.md`; the installer does not write there.
- Kimi Code scans `.kimi-code/skills/` and `.agents/skills/`, not `.claude/skills/`, so the skills load through the block's pointer.

Documentation for this surface: <https://moonshotai.github.io/kimi-code/en/customization/agents.html>

## Loop drive

Self-paced: the installer wires no stop hook for Kimi. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through Kimi's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where Kimi runs its shell (`pip install simplicio-loop`).
