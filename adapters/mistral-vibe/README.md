# Mistral Vibe adapter

Mistral Vibe loads `AGENTS.md` files from the current directory up to the trust root. Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh mistral-vibe     # macOS / Linux
pwsh scripts/install.ps1 mistral-vibe    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `AGENTS.md`, which Vibe loads for trusted folders only. The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

- User-level instructions live in `~/.vibe/AGENTS.md`; the installer does not write there.
- Vibe scans `.vibe/skills/` and `.agents/skills/` for skills.

Documentation for this surface: <https://github.com/mistralai/mistral-vibe>

## Loop drive

Self-paced: the installer wires no stop hook for Mistral Vibe. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through Mistral Vibe's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where Mistral Vibe runs its shell (`pip install simplicio-loop`).
