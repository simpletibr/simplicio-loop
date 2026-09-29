# Command Code adapter

Command Code loads `AGENTS.md` project memory into every session (it reads `AGENTS.md`, not `CLAUDE.md`). Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh command-code     # macOS / Linux
pwsh scripts/install.ps1 command-code    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `AGENTS.md`, which Command Code reads at the project root (`.commandcode/AGENTS.md` is the alternative; the first that exists is used). The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

- User-level memory lives in `~/.commandcode/AGENTS.md`; the installer does not write there.
- Command Code scans `.commandcode/skills/` and `.agents/skills/` for skills, not `.claude/skills/`.

Documentation for this surface: <https://commandcode.ai/docs/memory>

## Loop drive

Self-paced: the installer wires no stop hook for Command Code. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through Command Code's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where Command Code runs its shell (`pip install simplicio-loop`).
