> **2026-08:** Loop is Runtime-owned; operators (mapper/dev-cli/fast) work alone; every run needs `simplicio.execution-report/v1`. Full map: [docs/ECOSYSTEM_LLM_GUIDE.md](../docs/ECOSYSTEM_LLM_GUIDE.md).
# Runtime adapter matrix — simplicio-loop super-plugin

One universal skill core (`.claude/skills/`, 7 skills) + one set of hooks (`hooks/`) drives
**every** runtime. An adapter is thin: it tells a runtime *where to load the skills*, *how to
arm the loop*, and *how to bind native speed*. Nothing in the protocol is runtime-specific —
this is the inverted dependency (the skill names no runtime; the runtime detects the skill).

Three capabilities decide how rich an adapter is:

- **Skill load** — how the runtime discovers `SKILL.md` files.
- **Loop drive** — how `simplicio-loop` re-feeds the goal: a real **stop-hook**, or the
  **self-paced** fallback (host scheduler / cron / `/loop`).
- **Native bind** — whether `simplicio-runtime` (or a native command set) binds extension points
  for near-zero-token determinism. It is optional on every runtime: a missing/unreachable bind is
  reported as explicit degraded mode while the standalone loop remains usable. See
  `docs/MCP_SETUP.md` for the per-host config table and each adapter's "MCP config" section for
  the exact file path and snippet.

`orient_clamp.py` (token economy) works on **all** runtimes with no wiring — it's just a wrapper.

## Runtime tiers

Maintaining real parity across 15 distinct runtimes is infeasible — each host changes its hook/skill
format every release. This repo therefore adopts a **two-tier system**:

### Tier 1 — Guaranteed (gated)

Three runtimes are **verified mechanically on every commit** and enjoy real parity:

| # | Runtime | Skill load | Loop drive | Hooks | Optional native bind (MCP config) | Feedback | Adapter |
|---|---|---|---|---|---|---|---|
| 1 | **Claude Code** | `.claude/skills/` + `.claude-plugin/` | `Stop` hook | ✅ full | optional — `~/.claude.json` / `.mcp.json` | N1 (hook) + N3 | [claude](claude/README.md#mcp-config) |
| 2 | **Codex** | `AGENTS.md` → `SKILL.md` | self-paced | ⚠️ partial | optional — `~/.codex/config.toml` | N2 (transcript) + N3 | [codex](codex/README.md#mcp-config) |
| 3 | **Cursor** | `.cursor-plugin/` + `.claude/skills/` | `stop` + `afterAgentResponse` | ✅ full | optional — `.cursor/mcp.json` | N1 (hook) + N3 | [cursor](cursor/README.md#mcp-config) |

These three are covered by:
- `scripts/verify_adapters.py` running against each tier-1 runtime's install contract
- Gate check `adapter-install-contract` in `scripts/claims_audit.py` (fast per-runtime verification)

**To enter Tier 1**, a runtime must:
1. Have an adapter with documented skill-load, loop-drive, hooks, and native-bind columns
2. Pass `scripts/verify_adapters.py <runtime>` (idempotent, throwaway target, zero risk to real config)
3. Maintain a passing gate for 1 full release cycle without a regression

**To exit Tier 1** (demotion to Tier 2), a runtime:
1. Fails `verify_adapters.py` for 2 consecutive releases, or
2. The upstream runtime changes its skill/hook format and no PR adapts within 1 release cycle

### Tier 2 — Best-effort (ungated)

Twelve runtimes are documented and supported on a best-effort basis — contributions welcome,
no gate, no parity promise per release. The native bind is optional here too; "best-effort"
describes how well the *MCP config path itself* is verified on that host. A missing bind is
reported as degraded mode rather than preventing standalone operation. In the tables, a config
path names how to enable the optional bind; it is not a precondition for the loop:

| # | Runtime | Skill load | Loop drive | Hooks | Optional native bind (MCP config) | Feedback | Adapter |
|---|---|---|---|---|---|---|---|
| 4 | **VS Code (Copilot)** | `.github/copilot-instructions.md` | self-paced (tasks) | ⚠️ tasks | optional — `.vscode/mcp.json` (`servers` key) | N2 (transcript) + N3 | [vscode](vscode/README.md#mcp-config) |
| 4b | **Grok** | `~/.grok/skills` + `~/.grok/rules` + `AGENTS.md` | self-paced | — | none required | N2 + N3 | [grok](grok/README.md) |
| 5 | **Antigravity** | rules / `AGENTS.md` | self-paced | ⚠️ | optional — IDE MCP settings (path not verified) | N2 (transcript) + N3 | [antigravity](antigravity/README.md#mcp-config) |
| 6 | **Kiro** | `.kiro/steering/` | self-paced (specs) | ⚠️ | optional — `.kiro/settings/mcp.json` | N2 (transcript) + N3 | [kiro](kiro/README.md#mcp-config) |
| 7 | **OpenCode** | `AGENTS.md` + config | self-paced | ⚠️ | optional — `opencode.json` (`mcp` key) | N2 (transcript) + N3 | [opencode](opencode/README.md#mcp-config) |
| 8 | **Gemini** (CLI / Code Assist) | `GEMINI.md` → `SKILL.md` | self-paced | ⚠️ | optional — `.gemini/settings.json` (CLI, verified); Code Assist not verified | N2 (transcript) + N3 | [gemini](gemini/README.md#mcp-config) |
| 9 | **Kimi** | inlined conventions file | self-paced | ⚠️ | optional — no verified first-party config; best-effort | N2 (transcript) + N3 | [kimi](kimi/README.md#mcp-config) |
| 10 | **Qwen** (Code / CLI) | `AGENTS.md`-equivalent | self-paced | ⚠️ | optional — `.qwen/settings.json` (best-effort, Gemini-CLI fork shape) | N2 (transcript) + N3 | [qwen](qwen/README.md#mcp-config) |
| 11 | **DeepSeek** | inlined conventions file | self-paced | ⚠️ | optional — no first-party config; route via a wrapper's MCP client | N2 (transcript) + N3 | [deepseek](deepseek/README.md#mcp-config) |
| 12 | **Aider** | `CONVENTIONS.md` (read) | self-paced | ❌ | optional — no host MCP client; standalone LLM execution remains available | N2 (inlined transcript) + N3 | [aider](aider/README.md) |
| 13 | **Simplicio Agent** *(formerly Hermes)* | native skill recall | native loop | ✅ native | optional — native extension points (no MCP shim needed) | N1-equiv (native tick) + N3 | [simplicio_agent](simplicio_agent/README.md) |
| 14 | **OpenClaw** | plugin SDK / `skills/` | native scheduler | ✅ native | optional — **native** (plugin SDK) | N1-equiv (native tick) + N3 | [openclaw](openclaw/README.md) |
| 15 | **Orca** *(client opt-in only — not default)* | via inner agent (`.claude/skills/` + `AGENTS.md`) | **no core Orca hook**; inner agent hook / self-paced if client installed Orca | — | only if client requests (`CLIENT_INTEGRATIONS=orca`) | N1/N2 (inner) + N3 | [orca](orca/README.md#mcp-config) |

Rows 9–11 (Kimi, Qwen, DeepSeek) and Antigravity's IDE-side config are explicitly
**best-effort / community-reported, not gated** — see `docs/MCP_SETUP.md` for the verified-vs-
best-effort breakdown per host.

`hermes` is kept as a **legacy shim** for row 13 (Simplicio Agent), not a 16th runtime — see
[hermes/README.md](hermes/README.md). It installs/binds identically to `simplicio_agent` during
the compat window and will be removed after the deprecation threshold (one release cycle without
a regression report), per the adapter-rebrand rollback policy (#262).

Legend: ✅ first-class · ⚠️ partial / via a generic mechanism · ❌ none (degrade to fallback).
Native binds are optional on every runtime. Missing native capabilities are reported as degraded
mode; installing and driving the standalone loop remains available.

## Acompanhando o progresso (issue #303, EPIC #296)

Three feedback levels, each a strict superset of the one before — no runtime needs new code to
get the last one:

- **N1 (hook).** Where a real stop-hook exists (Claude Code, Cursor, and the native loops of
  Simplicio Agent/OpenClaw), the host injects fase/etapa/item/ACs/% directly into the re-feed
  header (`hooks/loop_stop.py`) — zero extra action from the user.
- **N2 (transcript).** The turn-header contract (SKILL.md § Output: first line of every turn =
  `render --turn-header`) is normative for ALL 15 runtimes, hook or not — it must be reflected in
  whichever surface that host loads the skill FROM (`AGENTS.md`, `GEMINI.md`, `CONVENTIONS.md`,
  `.github/copilot-instructions.md`, `.kiro/steering/`, OpenCode config, …), never forked by hand.
- **N3 (file, universal denominator).** `.simplicio/orchestrator/loop/PROGRESS.md` + `progress.json` are
  regenerated every turn regardless of runtime — any editor, `watch`, or CI panel reads it with
  ZERO adapter code. This is the fallback for every runtime not yet adapted, and for any future
  host: a brand-new runtime gets N3 for free the moment it runs `scripts/loop_progress.py`.

Each adapter README has a "Progresso do run" section naming its own N1/N2 step plus the N3
fallback. `scripts/verify_adapters.py` asserts (Tier 1, gated) that the installed skill-load
surface actually contains the turn-header contract string, and that hook-bound runtimes install
the progress-injecting `loop_stop.py`.

## Install (any runtime)

```bash
# from a clone of this repo:
bash scripts/install.sh <runtime> [--global]      # macOS/Linux
pwsh scripts/install.ps1 <runtime> [-Global]      # Windows / pwsh
# <runtime> ∈ claude codex grok vscode cursor antigravity kiro opencode gemini aider simplicio_agent
#            openclaw orca   (hermes still accepted as a legacy alias for simplicio_agent)
# omit <runtime> to auto-detect
# kimi / qwen / deepseek are NOT yet wired into scripts/install.sh — see their adapter READMEs
# for the manual/best-effort install steps
```

The installer copies the 7 skills into the runtime's skills location and wires the loop hooks
where supported. The native MCP/CLI bind (`simplicio-runtime`) is an optional enhancement — run
`pip install -U simplicio-installer && simplicio install --global` and confirm with
`simplicio doctor --json` when native capabilities are needed; see `docs/MCP_SETUP.md`.

## Loop→Runtime contract adapter

All native bindings use the transport-neutral [`docs/runtime-adapter.md`](../docs/runtime-adapter.md)
contract. The adapter negotiates `simplicio.runtime/v1`, preserves the same Run/WorkItem IDs,
buffers operations during outages, and fails closed on incompatible versions. Standalone mode is
available only with an explicit `standalone=True` choice and never claims runtime delivery.

## What degrades gracefully — and what does not

- **No stop-hook** → the loop self-paces via the host scheduler (`simplicio-loop` "No-hook
  fallback"). Same exit conditions (evidence-gated promise, cap, STOP). This degradation is
  always allowed — it's a drive-mechanism choice, not a policy violation.
- **No native bind** → explicit **degraded mode**. If the `simplicio` binary/MCP server is missing
  or unreachable, the adapter reports degraded preflight status and continues with standalone
  capabilities; install and verify the bind (`simplicio doctor --json`) when native features are
  needed for a task.
- **No skill loader** (e.g. Aider) → the adapter inlines `SKILL.md` as the runtime's
  conventions/instructions file. Larger context, identical behavior. Native capabilities remain
  optional independently of the skill-loading mechanism.

The promise: **same protocol, same gates, same safety on all 16 — Tier 1 verified mechanically,
Tier 2 best-effort with contributions welcome, optional native binds with explicit degradation.**

## Verifying an adapter

The installer's contract (skills copied · entry file marked · hooks present/wired · worker
scripts copied · `scripts/loop_progress.py selftest` runs GREEN from inside the installed
target — #303 AC5, a dedicated per-runtime assertion, not one inferred from the sweep merely
exiting 0) is verified end-to-end per runtime by `scripts/verify_adapters.py`, which installs
into a throwaway target and asserts each promise — no risk to your real config:

```bash
python3 scripts/verify_adapters.py tier1                        # Tier 1 — gated, run on every commit
python3 scripts/verify_adapters.py claude codex cursor          # same as above
python3 scripts/verify_adapters.py                              # all 16 (~45s/runtime — run manually or in a slower CI job)
python3 scripts/verify_adapters.py antigravity kiro opencode aider   # a Tier-2 subset
```

`scripts/claims_audit.py` (check 7, part of `python3 scripts/check.py`) runs the fast, single-runtime
form (`verify_adapters.py claude`, ~15s) on every gate so the Tier-1 install contract is never dead
assurance — it does NOT run the full 14-runtime sweep above; run that manually before a release.

That covers everything up to launching the runtime itself. The final manual smoke — open the
runtime, run `/simplicio-loop <small task>`, confirm the loop drives and the gates fire — is the
one step a file-level harness can't do; do it once per runtime per the adapter's README.
