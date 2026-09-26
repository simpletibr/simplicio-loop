# Qwen adapter (Qwen Code / Qwen CLI)

Qwen Code (Alibaba's `qwen-code` CLI, a fork of Gemini CLI) and Qwen's other CLI surfaces read a
`.qwen/settings.json`-style config analogous to Gemini CLI's `.gemini/settings.json`, including
`mcpServers` support inherited from the fork. This is documented upstream but **not verified
against a real install in this repo** — treat the config path/shape as best-effort until you
confirm it against your installed Qwen Code version.

## Install

`qwen` is not yet a recognized target of `scripts/install.sh`/`scripts/install_lib.py` (see
`adapters/MATRIX.md` § Install for the currently wired runtime list). Until it is wired in,
install by hand — write a `QWEN.md` (or reuse `AGENTS.md` if your Qwen CLI reads that convention,
as its Gemini CLI upstream does) that loads `.claude/skills/simplicio-tasks/SKILL.md` +
satellites, mirroring the [Gemini adapter](../gemini/README.md)'s approach.

## Loop drive — self-paced

No stop-hook → self-pace via cron / CI tick:

```bash
*/2 * * * *  cd /repo && qwen -p "/simplicio-tasks continue the open queue"
```

## Token economy

`orient_clamp.py` works as-is. Reference it in your Qwen conventions file.

## Native bind — MCP (optional, best-effort wiring)

`simplicio-runtime` native binding is optional on Qwen. A missing/unreachable bind reports
explicit degraded mode while the standalone loop remains available.

```bash
pip install -U simplicio-installer && simplicio install --global
```

## MCP config

- **Config file:** `.qwen/settings.json` (project scope) or `~/.qwen/settings.json` (user scope),
  under an `mcpServers` key — inherited from the Gemini CLI fork's schema. **Best-effort**: the
  Qwen Code project documents MCP support but this repo has not mechanically verified the exact
  file path/schema against a live install.
- **Snippet:**

```json
{ "mcpServers": { "simplicio": { "command": "simplicio", "args": ["serve", "--mcp", "--stdio"], "cwd": "/path/to/your/repo" } } }
```

- **Verify:** `simplicio doctor --json | grep -A2 mcp-host-registration` confirms the runtime
  side; use `qwen mcp list` if your CLI version ships that subcommand (mirrors Gemini CLI's
  surface). Tier: **best-effort / community-reported, not gated**.

## Use

```
qwen -p "/simplicio-tasks finish all the open issues"
```

## Progresso do run

Self-paced (N2): the tick echoes the turn-header. Universal fallback (N3): open
`.simplicio-loop/orchestrator/loop/PROGRESS.md` (auto-regenerated every turn).

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

