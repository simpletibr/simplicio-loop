# oh-my-pi adapter

oh-my-pi (`omp`) discovers context files from several providers, `AGENTS.md` at the repository root among them. Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh oh-my-pi     # macOS / Linux
pwsh scripts/install.ps1 oh-my-pi    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `AGENTS.md`, which the `agents-md` provider discovers at the repository root. The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

- A non-empty `.omp/AGENTS.md` (the native provider) shadows the root `AGENTS.md` at the same depth.
- omp scans `.claude/skills/`, `.agents/skills/` and `.github/skills/` for skills, so the skills copy is also a native skill install.

Documentation for this surface: <https://github.com/can1357/oh-my-pi/blob/main/docs/context-files.md>

## Loop drive

Self-paced: the installer wires no stop hook for oh-my-pi. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through oh-my-pi's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where oh-my-pi runs its shell (`pip install simplicio-loop`).
