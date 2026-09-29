# Gemini adapter

Gemini CLI reads `GEMINI.md` as its standing context and supports MCP servers. Point it at the
skill; drive the loop self-paced; bind natively via MCP or the simplicio-runtime Gemini adapter.

## Install

```bash
bash scripts/install.sh gemini
```

This repo's `GEMINI.md` already loads `.claude/skills/simplicio-tasks/SKILL.md`; the installer
adds the satellites and registers the MCP server in `.gemini/settings.json`.

## Loop drive — self-paced

No stop-hook → self-pace via cron / CI tick:

```bash
*/2 * * * *  cd /repo && gemini -p "/simplicio-tasks continue the open queue"
```

## Token economy

`orient_clamp.py` works as-is. Add it to `GEMINI.md` command conventions.

## Native bind — MCP / native adapter (optional)

`simplicio-runtime` native binding is optional on Gemini. A missing/unreachable bind reports
explicit degraded mode while the standalone loop remains available.

```bash
pip install -U simplicio-installer && simplicio install --global
# or use simplicio-runtime/agent/gemini_native_adapter.py for the native REST path
```

## MCP config

Two related surfaces share the Gemini name; treat them separately:

- **Gemini CLI** — **Config file:** `~/.gemini/settings.json` (user scope) or `.gemini/settings.json`
  (project scope), under an `mcpServers` key. **Verified** conceptually (documented Gemini CLI MCP
  format); this repo's installer writes this file.

```json
{ "mcpServers": { "simplicio": { "command": "simplicio", "args": ["serve", "--mcp", "--stdio"], "cwd": "/path/to/your/repo" } } }
```

- **Gemini Code Assist** (the IDE/VS Code extension side, distinct from the CLI) — uses its own
  IDE-level MCP settings surface, not the `.gemini/settings.json` file above. **Not verified**
  against a real Code Assist install in this repo — best-effort; check the extension's own MCP
  settings UI for the current field names before relying on a JSON snippet here.

- **Verify:** `simplicio doctor --json | grep -A2 mcp-host-registration`, or `gemini mcp list` if
  your Gemini CLI version ships that subcommand. Tier: **best-effort** — Gemini is Tier 2 overall;
  the CLI path is the more reliable of the two surfaces.

## Use

```
gemini -p "/simplicio-tasks finish all the open issues"
```

## Run simplicio-loop

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through the host's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where the host runs its shell (`pip install simplicio-loop`). Full flow: `.claude/skills/simplicio-loop/SKILL.md`.

## Progresso do run

Self-paced (N2): the tick echoes the turn-header (`render --turn-header`). Universal fallback
(N3): open `.simplicio-loop/orchestrator/loop/PROGRESS.md` (auto-regenerated every turn).

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

