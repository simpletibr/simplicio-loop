# VS Code (Copilot) adapter

GitHub Copilot in VS Code reads `.github/copilot-instructions.md` as repo-wide custom
instructions, supports **MCP servers**, and can run **tasks**. There is **no PreToolUse**.
`adapters/vscode/adapter.py` reports residual unmanaged editor mutations honestly and
requires MCP for Plugin-initiated writes.

## Install

Two distinct modes:

### Project-local (this repo only)

```bash
bash scripts/install.sh vscode
```

Writes `.github/copilot-instructions.md` (loads the orchestrator protocol) and registers the
MCP server in `.vscode/mcp.json` — scoped to the current repo.

### User-global (all repos, wires the real runtime surfaces)

```bash
python3 scripts/install_lib.py vscode --global
```

A global install no longer only drops skills under `~/.claude/skills`. It also mirrors the
skills into the **user-level VS Code/Copilot skill surface** and registers the **user-level
MCP server** (`mcp.json` under the OS user config dir), so GitHub Copilot + VS Code are usable
end-to-end on Windows/macOS/Linux without manual copy or MCP path repair. The user-level paths
resolved per OS:

| OS | User-level skill root | User-level MCP |
|----|----------------------|----------------|
| Windows | `%USERPROFILE%\.vscode\simplicio-skills` | `%APPDATA%\Code\User\mcp.json` |
| macOS | `~/Library/Application Support/Code/User` (mcp) · `~/.vscode/simplicio-skills` | `~/Library/Application Support/Code/User/mcp.json` |
| Linux | `~/.config/Code/User` (mcp) · `~/.vscode/simplicio-skills` | `~/.config/Code/User/mcp.json` |

Verify the install actually wired the active surfaces:

```bash
python3 scripts/doctor.py --json   # reports vscode_global drift (OPTIONAL tier)
python3 scripts/doctor.py --repair  # re-syncs skills + MCP if drift detected
```

Idempotent: a second `--global` run is a clean refresh, never a nested copy.

### Global Windows install (VS Code + GitHub Copilot)

Project-local files are not enough for a user-global Copilot setup. Run the official installer
from this repository with `vscode --global`:

```powershell
pwsh scripts/install.ps1 vscode -Global
```

The global path keeps the project-compatible copy under `~/.claude/skills/`, and also refreshes
the active Copilot surfaces:

- `%USERPROFILE%/.copilot/skills/` — the personal Agent Skills directory;
- `%USERPROFILE%/.copilot/instructions/simplicio-loop.instructions.md` — personal instructions;
- `%USERPROFILE%/.copilot/mcp-config.json` — Copilot CLI user MCP;
- `%APPDATA%/Code/User/mcp.json` — VS Code user MCP.

The installer merges only the `simplicio` server and preserves unrelated skills, instructions,
servers, and settings. It resolves the installed `simplicio` executable (or uses the portable
`simplicio` command name when the runtime is not installed yet). Verify the active surfaces with:

```powershell
python scripts/doctor.py --json
python scripts/doctor.py --repair
```

The VS Code/Copilot global adapter is one surface of the same runtime-neutral loop contract used
by Claude, Codex, Cursor, Gemini, Kiro, Antigravity, Hermes/Simplicio Agent, OpenClaw, and other
providers. GitHub lifecycle comments identify the runtime/device but coordinate all of them through
the same `source_issue`.

## Loop drive — self-paced via tasks

Copilot has no stop-hook. Drive the loop with a VS Code task that re-invokes the agent, or run
`simplicio-loop` self-paced. Minimal `.vscode/tasks.json` tick:

```jsonc
{ "version": "2.0.0", "tasks": [
  { "label": "simplicio-loop tick", "type": "shell",
    "command": "python3 hooks/loop_stop.py < NUL" } ]
}
```

(The agent itself does the work each turn; the task only advances the scratchpad when running
headless. In interactive chat, just keep saying "continue" — the protocol is idempotent.)

## Token economy

`orient_clamp.py` works as-is in the integrated terminal. Reference it in
`copilot-instructions.md` so Copilot routes heavy commands through it.

## Native bind — MCP (optional)

`simplicio-runtime` native binding is optional on VS Code/Copilot. A missing/unreachable bind
reports explicit degraded mode while the standalone loop remains available. `simplicio install --global` writes
`.vscode/mcp.json`:

```json
{ "servers": { "simplicio": { "command": "simplicio", "args": ["serve", "--mcp", "--stdio"] } } }
```

Then the extension points bind to `simplicio-runtime` natively. Use `simplicio doctor --json` to
confirm the bind.

## MCP config

- **Config file (project):** `.vscode/mcp.json`, under a **`servers`** key (note: not
  `mcpServers` — VS Code's MCP schema differs from Claude/Cursor).
- **Config file (user-global):** see the OS table above (`%APPDATA%\Code\User\mcp.json` etc.).
- **Snippet:**

```json
{
  "servers": {
    "simplicio": {
      "type": "stdio",
      "command": "simplicio",
      "args": ["serve", "--mcp", "--stdio"],
      "cwd": "/path/to/your/repo"
    }
  }
}
```

- **Verify:** `simplicio doctor --json | grep -A2 mcp-host-registration`, or VS Code Command
  Palette → "MCP: List Servers" → confirm `simplicio` is running. Tier: **best-effort** — VS Code
  is Tier 2 (not run under the gated per-commit sweep, though `scripts/verify_adapters.py vscode`
  exists and can be run manually).

## Use

Open Copilot Chat and type: `/simplicio-tasks finish all the open issues` (or paste the goal —
the instructions file makes Copilot follow the protocol).

## Progresso do run

Self-paced (N2, via tasks): the task tick echoes the turn-header. Simplest (N3, universal): open
`.simplicio-loop/orchestrator/loop/PROGRESS.md` in the editor — it auto-updates every turn, no extension needed.

## Ecosystem law (2026-08) — read on every host

Canonical guide (what each project is, install, step-by-step):

- In **simplicio-runtime**: `docs/ECOSYSTEM_LLM_GUIDE.md`
- In **simplicio-loop**: `docs/ECOSYSTEM_LLM_GUIDE.md` (same content)

| Project | Role |
|---------|------|
| **runtime** | Kernel: gates, MCP, **owns loop**, **owns execution-report**, decides `use_loop` |
| **loop** | Protocol + hooks + Prism under Runtime authority |
| **mapper / dev-cli / fast** | Operators — **work alone** without Runtime |
| **agent** | Optional coordinator/desktop — not mandatory gateway |

**Commands every host must know:**

```bash
simplicio loop decide --task "<work>" --json
simplicio execution-report start|record-task|finish|show|consolidate --json
simplicio-loop preflight --strict --json
```

After Runtime install on Windows: `packaging/windows/install.ps1` then pip-install loop/mapper/dev-cli and re-run preflight until operational.

