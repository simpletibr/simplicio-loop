# Auggie adapter

Auggie (Augment's CLI agent) reads `AGENTS.md` and `CLAUDE.md` rule files; the workspace-root file is always included. Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh auggie     # macOS / Linux
pwsh scripts/install.ps1 auggie    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `AGENTS.md`, which Auggie always includes from the workspace root (nested ones apply to the files below them). The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

- Workspace rules can also live in `.augment/rules/`.

Documentation for this surface: <https://docs.augmentcode.com/cli/rules>

## Loop drive

Self-paced: the installer wires no stop hook for Auggie. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through Auggie's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where Auggie runs its shell (`pip install simplicio-loop`).
