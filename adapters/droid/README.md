# Droid adapter

Factory's Droid searches for `AGENTS.md` from the working directory up to the git root. Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh droid     # macOS / Linux
pwsh scripts/install.ps1 droid    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `AGENTS.md`, which Droid reads. The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

- Repository context can also live in `.factory/`, `.agents/` or `.agent/`; personal files live in `~/.factory/`.

Documentation for this surface: <https://docs.factory.ai/harness/agents-md>

## Loop drive

Self-paced: the installer wires no stop hook for Droid. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through Droid's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where Droid runs its shell (`pip install simplicio-loop`).
