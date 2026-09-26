# Cursor adapter

First-class: native plugin manifest (`.cursor-plugin/`), `stop` + `afterAgentResponse` hooks,
T4 `beforeShellExecution`, rules, and MCP. T3 before-edit is **not** a native Cursor hook
in this adapter — it is declared `self_paced` / `unsupported_native`, never as green
Claude-parity enforcement. See `adapters/cursor/adapter.py`.

## Install

```bash
bash scripts/install.sh cursor
```

Or add the marketplace and install:

```
# Cursor → Settings → Plugins → Add from Git: wesleysimplicio/simplicio-loop
```

The root `.cursor-plugin/plugin.json` declares the skills (`./.claude/skills/`) and hooks
(`./hooks/hooks.json`). `hooks/hooks.json` is already in Cursor's format.

## Loop drive — two-hook split (the original Ralph pattern)

`hooks/hooks.json` wires:
- `afterAgentResponse` → `loop_capture.py` (raise `done` on an evidence-backed `<promise>`)
- `stop` → `loop_stop.py` (re-feed the goal, or exit on promise/cap/STOP)

Detection and termination are decoupled — neither parses the other's state inline.

## Token economy

`orient_clamp.py` works as-is. For automatic clamping, add a `beforeShellExecution`-style
rewrite in your Cursor hooks pointing at `orient_rewrite.py` (opt-in; conservative + fail-open).

## Native bind — MCP / rules (optional)

`simplicio-runtime` native binding is optional on Cursor. A missing/unreachable bind reports
explicit degraded mode while the standalone loop remains available:

```bash
pip install -U simplicio-installer && simplicio install --global   # registers Cursor's MCP config
```

Use `simplicio doctor --json` to confirm the bind. A `.cursor/rules/` entry can pin
model-per-role choices (pstack-style) if you use the simplicio-runtime model router.

## MCP config

- **Config file:** `.cursor/mcp.json` (project scope) or `~/.cursor/mcp.json` (global scope),
  under an `mcpServers` key.
- **Snippet:**

```json
{
  "mcpServers": {
    "simplicio": {
      "command": "simplicio",
      "args": ["serve", "--mcp", "--stdio"],
      "cwd": "/path/to/your/repo"
    }
  }
}
```

- **Verify:** `simplicio doctor --json | grep -A2 mcp-host-registration`, or Cursor → Settings →
  MCP, confirm `simplicio` shows a green/connected status. Tier: **verified** — Cursor is a gated
  Tier 1 runtime (`scripts/verify_adapters.py cursor`).

## Use

```
/simplicio-tasks finish all the open issues
```

## Progresso do run

Hook-bound (N1): both the `stop` hook and `afterAgentResponse` capture feed `loop_stop.py`, which
injects fase/etapa/item/ACs/% into the re-feed header — no action needed. Universal fallback (N3):
open `.simplicio-loop/orchestrator/loop/PROGRESS.md` (auto-regenerated every turn).

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

