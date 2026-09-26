# OpenCode adapter

OpenCode is a terminal-native agent that reads `AGENTS.md`, supports MCP servers, and has its
own config (`opencode.json`). No stop-hook → self-paced loop.

## Install

```bash
bash scripts/install.sh opencode
```

The installer ensures `AGENTS.md` loads `.claude/skills/simplicio-tasks/SKILL.md` + satellites
and registers the MCP server in `opencode.json`.

## Loop drive — self-paced

Drive ticks headlessly on a schedule:

```bash
*/2 * * * *  cd /repo && opencode run "/simplicio-tasks continue the open queue"
```

`simplicio-loop` advances the scratchpad and exits on the evidence-gated promise, the cap,
spindle handoff, or explicit STOP.

## Token economy

`orient_clamp.py` works as-is. Reference it in `AGENTS.md` so heavy commands are clamped.

## Native bind — MCP (optional)

`simplicio-runtime` native binding is optional on OpenCode. A missing/unreachable bind reports
explicit degraded mode while the standalone loop remains available. Add this to `opencode.json`
when native capabilities are needed:

```json
{ "mcp": { "simplicio": { "type": "local", "command": ["simplicio", "serve", "--mcp", "--stdio"] } } }
```

Use `simplicio doctor --json` to confirm the bind.

## MCP config

- **Config file:** `opencode.json` (or `opencode.jsonc`) at the repo root, under the **`mcp`**
  key — OpenCode's schema uses `type: "local"` + a `command` array, not `command`/`args` split
  like most other hosts.
- **Snippet:**

```json
{
  "mcp": {
    "simplicio": {
      "type": "local",
      "command": ["simplicio", "serve", "--mcp", "--stdio"],
      "environment": {}
    }
  }
}
```

  (OpenCode inherits the working directory it was launched from; run `opencode` from the target
  repo, or set `environment`/`cwd` per your OpenCode version's config reference.)
- **Verify:** `simplicio doctor --json | grep -A2 mcp-host-registration`, or `opencode mcp list`
  if your version ships that subcommand. Tier: **best-effort** — OpenCode is Tier 2 (provider-
  agnostic MCP support is documented upstream but not mechanically gated here).

## Use

```
opencode run "/simplicio-tasks finish all the open issues"
```

## Progresso do run

Self-paced (N2): the tick echoes the turn-header. Universal fallback (N3, works with any config):
`watch -n5 cat .simplicio-loop/orchestrator/loop/PROGRESS.md`.

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

