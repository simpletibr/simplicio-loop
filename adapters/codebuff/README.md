# Codebuff adapter

Codebuff reads one project file per directory: `knowledge.md`, else `AGENTS.md`, else `CLAUDE.md`. Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh codebuff     # macOS / Linux
pwsh scripts/install.ps1 codebuff    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `AGENTS.md`, which Codebuff reads when the directory has no `knowledge.md`. The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

- A `knowledge.md` in the same directory takes priority and hides `AGENTS.md`; keep the marker block there instead.

Documentation for this surface: <https://www.codebuff.com/docs/help/faq>

## Loop drive

Self-paced: the installer wires no stop hook for Codebuff. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through Codebuff's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where Codebuff runs its shell (`pip install simplicio-loop`).
