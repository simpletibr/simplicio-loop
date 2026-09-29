# Qwen Code adapter

Qwen Code (Alibaba's CLI agent) reads `QWEN.md` as its memory file, and also reads an `AGENTS.md` the repository already has. Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh qwen     # macOS / Linux
pwsh scripts/install.ps1 qwen    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `QWEN.md`, which Qwen Code loads from the project root (user-wide memory is `~/.qwen/QWEN.md`). The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

Documentation for this surface: <https://qwenlm.github.io/qwen-code-docs/en/users/features/memory/>

## Loop drive

Self-paced: the installer wires no stop hook for Qwen Code. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through Qwen Code's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where Qwen Code runs its shell (`pip install simplicio-loop`).
