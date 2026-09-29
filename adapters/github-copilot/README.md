# GitHub Copilot adapter

GitHub Copilot (VS Code agent mode, the Copilot CLI and the coding agent on github.com) reads repository custom instructions. Install status: **wired**.

## Skill load

```bash
bash scripts/install.sh github-copilot     # macOS / Linux
pwsh scripts/install.ps1 github-copilot    # Windows
```

The installer copies the 7 skills into `.claude/skills/` and writes the `simplicio-loop` marker block into `.github/copilot-instructions.md`, which Copilot loads as repository-wide custom instructions (it also reads `AGENTS.md`, `CLAUDE.md` and `GEMINI.md`). The block tells the agent to load `.claude/skills/simplicio-loop/SKILL.md`. A second run changes nothing.

- The [vscode](../vscode/README.md) adapter writes the same file.
- The cloud coding agent runs in GitHub's environment, where this adapter does not install `simplicio-loop`; prefer VS Code agent mode or the Copilot CLI.

Documentation for this surface: <https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions>

## Loop drive

Self-paced: the installer wires no stop hook for GitHub Copilot. The agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through GitHub Copilot's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where GitHub Copilot runs its shell (`pip install simplicio-loop`).
