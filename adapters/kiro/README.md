# Kiro adapter

Kiro (AWS's agentic IDE) uses **steering files** (`.kiro/steering/*.md`) for standing guidance,
**specs** for structured work, and MCP servers. We load the protocol via steering and drive the
loop through specs / self-pacing.

## Install

```bash
bash scripts/install.sh kiro
```

The installer writes `.kiro/steering/simplicio-tasks.md` that loads the orchestrator + satellites
and registers the MCP server in `.kiro/settings/mcp.json`.

## Loop drive — self-paced via specs

No stop-hook is claimed. Specs are not the Simplicio source of truth: a spec
task cannot close while the Runtime receipt is ambiguous. Missing hooks use
the governed self-paced fallback (`adapters/kiro/adapter.py`).

No stop-hook. Use a Kiro **spec** as the durable goal, and let `simplicio-loop` self-pace each
execution against the spec's acceptance criteria (which map directly onto the skill's AC gate).
Exit conditions unchanged (evidence-gated promise, cap, STOP).

## Token economy

`orient_clamp.py` works as-is. Add it to the steering file's command conventions.

## Native bind — MCP (optional)

`simplicio-runtime` native binding is optional on Kiro. A missing/unreachable bind reports
explicit degraded mode while the standalone loop remains available. `simplicio install --global` writes
`.kiro/settings/mcp.json`:

```json
{ "mcpServers": { "simplicio": { "command": "simplicio", "args": ["serve", "--mcp", "--stdio"] } } }
```

Use `simplicio doctor --json` to confirm the bind.

## MCP config

- **Config file:** `.kiro/settings/mcp.json` (project/workspace scope, AWS Kiro's own path), or
  the equivalent global path under the OS user config dir for a user-level install.
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

- **Verify:** `simplicio doctor --json | grep -A2 mcp-host-registration`, or Kiro's MCP panel in
  the IDE (lists connected servers). Tier: **best-effort** — Kiro is Tier 2 (documented, installer
  writes the file, but not run under the gated per-commit sweep).

## Use

Create a spec or chat: `/simplicio-tasks finish all the open issues`. The steering file makes
Kiro follow the protocol and honor the safety gates.

## Progresso do run

Self-paced (N2, via specs): each tick echoes the turn-header. Universal fallback (N3): open
`.simplicio-loop/orchestrator/loop/PROGRESS.md` in the editor (auto-regenerated every turn).

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

