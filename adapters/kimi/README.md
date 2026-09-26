# Kimi adapter

Kimi (Moonshot AI) is reachable as a coding agent mainly through **Kimi CLI** and through
OpenAI-compatible API wrappers used by third-party agent shells. It has no first-party,
independently-documented MCP client contract as stable as Claude/Cursor/VS Code's — this adapter
is intentionally **best-effort**.

## Install

`kimi` is not yet a recognized target of `scripts/install.sh`/`scripts/install_lib.py` (see
`adapters/MATRIX.md` § Install for the currently wired runtime list). Until it is wired in,
install by hand, mirroring the Aider pattern since Kimi has no native `.claude/skills`-style skill
loader:

```bash
cp .claude/skills/simplicio-loop/SKILL.md CONVENTIONS.md   # or your Kimi shell's own instructions file
```

## Loop drive — self-paced

No stop-hook. Drive ticks on a schedule via whichever CLI entrypoint your Kimi install exposes,
same exit conditions (evidence-gated promise, cap, spindle handoff, STOP) as every other
self-paced runtime.

## Token economy

`orient_clamp.py` works as-is: `python3 hooks/orient_clamp.py -- <build/test/diff command>`.

## Native bind — MCP (optional, best-effort wiring)

`simplicio-runtime` native binding is optional on Kimi. A missing/unreachable bind reports
explicit degraded mode while the standalone loop remains available. What differs on Kimi is how
well documented and verified the wiring is, not whether the
bind is optional.

```bash
pip install -U simplicio-installer && simplicio install --global
```

## MCP config

- **Config file:** **not independently verified.** Kimi CLI's MCP support (where present) tracks
  the same `mcpServers`-keyed JSON shape used by most Claude/Anthropic-compatible tooling, and
  some Kimi integrations run entirely through an OpenAI-compatible wrapper/agent shell that has
  its own separate MCP config (e.g. an OpenCode or Claude Code front-end pointed at a Kimi model).
  If you're routing through such a wrapper, use that wrapper's own adapter section in this
  matrix (e.g. [opencode](../opencode/README.md#mcp-config)) instead of this file.
- **Best-effort snippet** (mirrors the common `mcpServers` shape; confirm against your actual
  Kimi CLI version's docs before relying on it):

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

- **Verify:** `simplicio doctor --json | grep -A2 mcp-host-registration` confirms the runtime
  side (binary reachable, contracts smoke passing); there is no verified Kimi-side MCP status
  command known to this repo. Tier: **best-effort / community-reported, not gated** — treat any
  claim of a fully working Kimi MCP integration as unverified until confirmed against a real
  install.

## Use

Whatever prompt surface your Kimi CLI/agent shell exposes: paste or reference the goal, e.g.
"`/simplicio-loop finish all the open issues`" if the shell loads the inlined conventions file.

## Progresso do run

Self-paced (N2): the tick should echo `python3 scripts/loop_progress.py render --turn-header`.
Universal fallback (N3): open `.simplicio-loop/orchestrator/loop/PROGRESS.md` (auto-regenerated every turn) —
this works with zero Kimi-specific code.

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

