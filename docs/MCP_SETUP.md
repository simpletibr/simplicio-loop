# MCP setup — `simplicio-runtime` across every host

`simplicio-runtime` (binary `simplicio`, MCP subcommand `simplicio serve --mcp --stdio`) is an
**optional** token-economy tool surface. It is **not** a dependency of `simplicio-loop`
(core = mapper + dev-cli; Fast when operational).

When Runtime **is** installed and `SIMPLICIO_REQUIRE_MCP=1` (set by
`scripts/mcp_force_sync.py --global`), agents are instructed and gated to prefer Runtime MCP
tools (`simplicio_map`, `simplicio_search`, `simplicio_memory`, `simplicio_gate`,
`simplicio_edit`, …) over bulk host Read/Grep/cat of source trees. The gate only blocks host
bulk-reads if `simplicio` is on PATH.

When Runtime/MCP is missing or unreachable, the **standalone loop continues** with
`simplicio-mapper` / `simplicio-dev-cli` and must report degraded mode — never fake MCP use,
never fail the loop solely because Runtime is absent.

**Optional force wiring (all hosts, when you want Runtime MCP):**

```bash
python3 scripts/mcp_force_sync.py --global --json
# sets REQUIRE_MCP=1 + EXECUTION_PROFILE=auto, writes rules, merges MCP configs, runs register
# Runtime remains optional: REQUIRE_RUNTIME=auto
```

This page is the single skimmable entry point for wiring the bind on any of the 15 hosts this
repo documents. Each row's config differs by host — read the linked adapter section for the exact
file, snippet, and verification step; don't copy a snippet from the wrong host.

Universal verification, works from any host's terminal once the binary is installed:

```bash
simplicio doctor --json | grep -A2 mcp-host-registration
```

## Host table

| Host | MCP config file | Status | Adapter section |
|---|---|---|---|
| Claude Code | `~/.claude.json` (`mcpServers`) or project `.mcp.json` | **verified** (Tier 1, gated) | [claude/README.md#mcp-config](../adapters/claude/README.md#mcp-config) |
| Codex | `~/.codex/config.toml` (`[mcp_servers.simplicio]`) | **verified** (Tier 1, gated) | [codex/README.md#mcp-config](../adapters/codex/README.md#mcp-config) |
| Cursor | `.cursor/mcp.json` or `~/.cursor/mcp.json` (`mcpServers`) | **verified** (Tier 1, gated) | [cursor/README.md#mcp-config](../adapters/cursor/README.md#mcp-config) |
| VS Code (Copilot) | `.vscode/mcp.json` (`servers`) / `%APPDATA%\Code\User\mcp.json` etc. (user-global) | **verified** (Tier 2, installer-written, not per-commit gated) | [vscode/README.md#mcp-config](../adapters/vscode/README.md#mcp-config) |
| Antigravity | IDE MCP settings (path not confirmed against a live install) | **best-effort** | [antigravity/README.md#mcp-config](../adapters/antigravity/README.md#mcp-config) |
| Orca Dev | Orca's MCP/skills registry, or the inner agent's own config (Claude Code/Cursor) | **best-effort** (Tier 2; inner-agent config is verified where that inner agent is Tier 1) | [orca/README.md#mcp-config](../adapters/orca/README.md#mcp-config) |
| OpenCode | `opencode.json` (`mcp`, `type: "local"`) | **best-effort** (documented upstream, not gated here) | [opencode/README.md#mcp-config](../adapters/opencode/README.md#mcp-config) |
| Gemini CLI | `.gemini/settings.json` or `~/.gemini/settings.json` (`mcpServers`) | **best-effort** (documented shape, not gated here) | [gemini/README.md#mcp-config](../adapters/gemini/README.md#mcp-config) |
| Gemini Code Assist | IDE-level MCP settings (distinct from Gemini CLI's file) | **best-effort, not verified** | [gemini/README.md#mcp-config](../adapters/gemini/README.md#mcp-config) |
| Kimi | no confirmed first-party MCP client; route via a wrapper's own config if applicable | **best-effort / community-reported, not gated** | [kimi/README.md#mcp-config](../adapters/kimi/README.md#mcp-config) |
| Qwen (Code/CLI) | `.qwen/settings.json` (`mcpServers`, inherited from the Gemini CLI fork) | **best-effort, not verified** | [qwen/README.md#mcp-config](../adapters/qwen/README.md#mcp-config) |
| DeepSeek | no first-party MCP client; route via a wrapper's own config (e.g. OpenCode) | **best-effort / community-reported, not gated** | [deepseek/README.md#mcp-config](../adapters/deepseek/README.md#mcp-config) |
| Kiro | `.kiro/settings/mcp.json` (`mcpServers`) | **best-effort** (installer-written, not per-commit gated) | [kiro/README.md#mcp-config](../adapters/kiro/README.md#mcp-config) |

Not in the table above because they have no host-level MCP client at all: **Aider** (LLM/git/gh
tool fallback), **Simplicio Agent** (native extension points, no MCP shim needed), **OpenClaw**
(native plugin SDK). See their adapter READMEs for optional runtime integration details.

## What "verified" vs "best-effort" means here

- **Verified (Tier 1, gated):** `scripts/verify_adapters.py <runtime>` runs this host's install
  contract on every commit (`scripts/claims_audit.py` check 7 runs the fast `claude` subset on
  every gate; the full Tier 1 set is `claude codex cursor`).
- **Verified (Tier 2, installer-written):** the installer (`scripts/install_lib.py` /
  `scripts/install.ps1`) actively writes this host's MCP config file and the shape is documented
  from that source, but it is not re-run on every commit.
- **Best-effort / community-reported, not gated:** the config shape is either inherited from a
  well-known upstream fork (Qwen ← Gemini CLI), or not independently confirmed against a real
  install in this repo (Antigravity, Gemini Code Assist, Kimi, DeepSeek). Treat these as a
  starting point, not a guarantee — confirm the exact field names against your installed version
  before relying on them, and prefer routing through a Tier 1/verified wrapper's MCP client where
  one is available (e.g. an OpenCode or Claude Code front-end configured against a Kimi/DeepSeek
  model).

## Installing the bind (any host)

```bash
pip install -U simplicio-installer && simplicio install --global
simplicio doctor --json | grep -A2 mcp-host-registration
```

`simplicio install --global` writes the Claude/Codex/Cursor/VS Code/Kiro configs directly where
present; hosts without a native client detected by the installer need the manual snippet from
their adapter section above.

## Related docs

- `AGENTS.md` § Hooks — optional-bind degraded-mode messaging; a missing Runtime bind
  never blocks the standalone Loop core.
- `adapters/MATRIX.md` — the full runtime tier system and the "Native bind" column per host.
- `docs/runtime-adapter.md` — the transport-neutral `simplicio.runtime/v1` contract every native
  binding negotiates, independent of the specific MCP config file.
