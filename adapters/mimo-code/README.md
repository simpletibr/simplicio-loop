# MiMo Code adapter

MiMo Code (Xiaomi's terminal coding agent) reads `AGENTS.md` as its primary rules file. Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh mimo-code     # macOS / Linux
pwsh scripts/install.ps1 mimo-code    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `AGENTS.md`, which MiMo Code loads from the project root (`CLAUDE.md` is its fallback). The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

- User-level rules live in `~/.config/mimocode/AGENTS.md`; the installer does not write there.
- Native skills are `.mimocode/skills/` and `.agents/skills/`; set `MIMOCODE_ENABLE_CLAUDE_CODE_SKILLS=true` to also scan `.claude/skills/`.

Documentation for this surface: <https://mimo.xiaomi.com/mimocode/rules>

## Loop drive

Self-paced: the installer wires no stop hook for MiMo Code. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through MiMo Code's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where MiMo Code runs its shell (`pip install simplicio-loop`).
