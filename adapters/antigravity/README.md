# Antigravity adapter

Antigravity (Google's agentic IDE) is a strong agent runtime with MCP support and a
rules/instructions file. It has no public stop-hook, so the loop self-paces.

## Install

```bash
bash scripts/install.sh antigravity
```

The installer writes an `AGENTS.md` / rules entry that loads
`.claude/skills/simplicio-tasks/SKILL.md` + the satellites, and registers the MCP server.

## Loop drive — self-paced

No stop-hook → `simplicio-loop` self-paces via the IDE's task runner or an OS cron tick that
re-invokes the agent. Same exit conditions (evidence-gated promise, cap, STOP). In
interactive use, keep the agent going with "continue" — the protocol is idempotent and
resumes from the journal.

## Token economy

`orient_clamp.py` works as-is in the terminal. Reference it in the rules file so the agent
routes heavy build/test/diff commands through it.

## Native bind — MCP (optional)

`simplicio-runtime` native binding is optional on Antigravity. A missing/unreachable bind reports
explicit degraded mode while the standalone loop remains available.

```bash
pip install -U simplicio-installer && simplicio install --global
```

Use `simplicio doctor --json` to confirm the bind. Antigravity's exact MCP config path isn't
auto-written by the installer yet, so finish it by hand from the snippet below.

## MCP config

- **Config file:** Antigravity (Google's agentic IDE, a VS Code fork) reads MCP servers from its
  own settings surface, documented by Google as following the same shape as the Gemini Code
  Assist / VS Code MCP settings — typically an IDE settings JSON with an `mcpServers` block, or
  the workspace `.vscode/mcp.json`-style file if the fork keeps that convention. **Not verified
  against a real Antigravity install in this repo** — confirm the exact path in your IDE's MCP
  settings UI before relying on the snippet below.
- **Snippet (best-effort, mirrors the VS Code/Gemini shape):**

```json
{ "mcpServers": { "simplicio": { "command": "simplicio", "args": ["serve", "--mcp", "--stdio"], "cwd": "/path/to/your/repo" } } }
```

- **Verify:** `simplicio doctor --json | grep -A2 mcp-host-registration` confirms the `simplicio`
  binary/runtime side; confirm the IDE side from Antigravity's own MCP status panel if it has
  one. Tier: **best-effort / not mechanically gated** — Antigravity is Tier 2.

## Use

Point the agent at: `/simplicio-tasks finish all the open issues` (or paste the goal — the
rules file makes it follow the protocol).

## Run simplicio-loop

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through the host's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where the host runs its shell (`pip install simplicio-loop`). Full flow: `.claude/skills/simplicio-loop/SKILL.md`.

## Progresso do run

Self-paced (N2): the tick echoes `python3 scripts/loop_progress.py render --turn-header`.
Universal fallback (N3): open `.simplicio-loop/orchestrator/loop/PROGRESS.md` (auto-regenerated every turn).

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

