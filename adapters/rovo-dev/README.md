# Rovo Dev adapter

Rovo Dev (Atlassian) keeps its project memory in `AGENTS.md`. Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh rovo-dev     # macOS / Linux
pwsh scripts/install.ps1 rovo-dev    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `AGENTS.md`, which Rovo Dev reads from the working directory and its parents (`AGENTS.local.md` holds personal notes). The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

- User memory lives in `~/.rovodev/AGENTS.md`; the installer does not write there.

Documentation for this surface: <https://support.atlassian.com/rovo/docs/use-memory-in-rovo-dev-cli/>

## Loop drive

Self-paced: the installer wires no stop hook for Rovo Dev. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through Rovo Dev's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where Rovo Dev runs its shell (`pip install simplicio-loop`).
