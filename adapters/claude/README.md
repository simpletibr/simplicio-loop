# Claude Code adapter

First-class: native skills, plugin manifest, and a five-stage Plugin v1 lifecycle
(`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`) implemented by
`adapters/claude/adapter.py`. Missing claimed hooks fail closed. Runtime absence is
degraded, never silent fail-open. Descriptor version/digest must stay aligned with the
canonical package version (`pyproject.toml`) and `plugin/.claude-plugin/plugin.json`.

## Install

```bash
bash scripts/install.sh claude            # project-local
bash scripts/install.sh claude --global   # all projects (~/.claude/skills)
```

Or as a marketplace plugin:

```
/plugin marketplace add wesleysimplicio/simplicio-loop
/plugin install simplicio-loop@simplicio
```

Or by hand: copy `.claude/skills/simplicio-*` into your repo's `.claude/skills/` (this repo
already has them — its own agents load them with zero setup).

## Loop drive — `Stop` hook

Add to `.claude/settings.json` (the installer does this for you):

```json
{ "hooks": {
  "Stop": [ { "hooks": [
    { "type": "command", "command": "python3 ./hooks/loop_stop.py" }
  ] } ],
  "PreToolUse": [ { "matcher": "Bash",
    "hooks": [ { "type": "command", "command": "python3 ./hooks/orient_rewrite.py" } ] } ]
} }
```

`loop_stop.py` re-feeds the goal each turn and exits only on an evidence-backed `<promise>`,
the `max_iterations` cap, spindle handoff, or explicit STOP. `orient_rewrite` (Bash matcher) is opt-in.

## Token economy

`orient_clamp.py` works immediately: `python3 hooks/orient_clamp.py -- go test ./...`. The
`PreToolUse` hook makes it automatic for read-only commands.

## Native bind (optional, near-zero token)

`simplicio-runtime` via MCP is optional on Claude Code. If the binary/MCP server is missing or
unreachable, report explicit degraded mode and continue the standalone loop; install it when a
task needs native capabilities:

```bash
pip install -U simplicio-installer && simplicio install --global
```

This registers the MCP server (`simplicio serve --mcp --stdio`) for Claude in one pass (plus
Codex/Cursor/VS Code/Kiro if present). Verify the bind with:

```bash
simplicio doctor --json | grep -A2 mcp-host-registration
```

## MCP config

- **Config file:** `~/.claude.json` (user scope, under an `mcpServers` key) or a project-local
  `.mcp.json` at the repo root. `simplicio install --global` writes the user-scope entry.
- **Snippet** (either file):

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

- **Verify:** `simplicio doctor --json` → look for `"name":"mcp-host-registration","status":"ok"`
  (it reports registration against `~/.claude.json` and confirms the server is responding). Tier:
  **verified** — this is one of the three gated Tier 1 runtimes (`scripts/verify_adapters.py claude`).

## Use

```
/simplicio-tasks finish all the open issues
```

## Progresso do run

Hook-bound (N1): `loop_stop.py` injects fase/etapa/item/ACs/% straight into the re-feed header —
no action needed. Universal fallback (N3, works everywhere): open
`.simplicio-loop/orchestrator/loop/PROGRESS.md` in the editor (auto-regenerated every turn), or
`watch -n5 cat .simplicio-loop/orchestrator/loop/PROGRESS.md` in a terminal.

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
