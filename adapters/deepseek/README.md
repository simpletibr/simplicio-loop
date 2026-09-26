# DeepSeek adapter

DeepSeek has no first-party agentic IDE/CLI with an independently documented MCP client contract
comparable to Claude/Cursor/VS Code. In practice, DeepSeek models are reached from agent shells
(OpenCode, generic OpenAI-compatible wrappers, or a Claude Code/Cursor front-end configured to
route model calls at a DeepSeek-compatible endpoint) that bring their own MCP support. This
adapter documents the protocol wiring and is explicitly **best-effort / community-reported**.

## Install

`deepseek` is not yet a recognized target of `scripts/install.sh`/`scripts/install_lib.py` (see
`adapters/MATRIX.md` § Install for the currently wired runtime list). Until it is wired in,
install by hand, mirroring the Aider pattern since there's no native `.claude/skills`-style loader
for a bare DeepSeek CLI:

```bash
cp .claude/skills/simplicio-loop/SKILL.md CONVENTIONS.md   # or your wrapper's own instructions file
```

## Loop drive — self-paced

No stop-hook. Drive ticks via whichever wrapper/CLI you use to reach a DeepSeek model, same exit
conditions (evidence-gated promise, cap, spindle handoff, STOP) as any self-paced runtime.

## Token economy

`orient_clamp.py` works as-is: `python3 hooks/orient_clamp.py -- <build/test/diff command>`.

## Native bind — MCP (optional, best-effort wiring)

`simplicio-runtime` native binding is optional on DeepSeek. A missing/unreachable bind reports
explicit degraded mode while the standalone loop remains available.

```bash
pip install -U simplicio-installer && simplicio install --global
```

## MCP config

- **Config file:** **no verified, DeepSeek-specific MCP config file is known to this repo.** If
  you reach DeepSeek through a wrapper that has its own MCP client (e.g. OpenCode configured with
  a DeepSeek-compatible provider, or a generic Anthropic/OpenAI-compatible agent shell), configure
  the bind through *that wrapper's* adapter section instead — e.g.
  [opencode](../opencode/README.md#mcp-config). This file exists so DeepSeek is not silently
  undocumented, not to claim a first-party integration that doesn't exist.
- **Best-effort snippet** (generic `mcpServers` shape, for wrappers that support it):

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
  side only; there is no known DeepSeek-side MCP status command. Tier: **best-effort /
  community-reported, not gated** — do not treat this as equivalent to the Tier 1 verified hosts.

## Use

Whatever prompt surface your DeepSeek wrapper/CLI exposes: paste or reference the goal, e.g.
"`/simplicio-loop finish all the open issues`" if the shell loads the inlined conventions file.

## Progresso do run

Self-paced (N2): the tick should echo `python3 scripts/loop_progress.py render --turn-header`.
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

