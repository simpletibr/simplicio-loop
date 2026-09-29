# Devin adapter

Devin (Cognition) looks for an `AGENTS.md` in the repository before it starts coding. Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh devin     # macOS / Linux
pwsh scripts/install.ps1 devin    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `AGENTS.md`, which Devin includes in its context (the first 16 KiB of each `AGENTS.md`). The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

- Keep the block inside the first 16 KiB of a long `AGENTS.md`.
- Cloud Devin runs on its own machine: install `simplicio-loop` in the environment where Devin executes. The installer only writes repository files.

Documentation for this surface: <https://docs.devin.ai/onboard-devin/agents-md>

## Loop drive

Self-paced: the installer wires no stop hook for Devin. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through Devin's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where Devin runs its shell (`pip install simplicio-loop`).
