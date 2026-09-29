> There is no Runtime/MCP backend in this stack; operators (mapper/dev-cli/fast) work standalone; every run needs `simplicio.execution-report/v1`. Full map: [docs/ECOSYSTEM_LLM_GUIDE.md](../docs/ECOSYSTEM_LLM_GUIDE.md).
# Runtime adapter matrix — simplicio-loop super-plugin

One universal skill core (`.claude/skills/`, 7 skills) + one set of hooks (`hooks/`) drives
**every** runtime. An adapter is thin: it tells a runtime *where to load the skills*, *how to
arm the loop*, and *how to bind native speed*. Nothing in the protocol is runtime-specific —
this is the inverted dependency (the skill names no runtime; the runtime detects the skill).

Three capabilities decide how rich an adapter is:

- **Skill load** — how the runtime discovers `SKILL.md` files.
- **Loop drive** — how `simplicio-loop` re-feeds the goal: a real **stop-hook**, or the
  **self-paced** fallback (host scheduler / cron / `/loop`).

`orient_clamp.py` (token economy) works on **all** runtimes with no wiring — it's just a wrapper.

## The catalog and install status

The hosts are listed once, in [`simplicio_loop/_catalog/harnesses.json`](../simplicio_loop/_catalog/harnesses.json)
(schema `simplicio.harnesses/v1`): the 32 host surfaces declared by `simpletibr/simplicio`
(`plugins/simplicio/host-surfaces.json`, at the commit recorded in the file) plus Aider, DeepSeek and
OpenClaw. Each entry names its adapter directory (the `id`, or an alias such as `claude` for
`claude-code`), the installer runtime, where the skills and the entry file land, and the official
documentation of that surface.

- **wired** — `scripts/install.sh <runtime>` (`scripts/install.ps1` on Windows) is an installer target for the
  host and writes the files its documentation says it reads. `tests/test_harness_catalog.py` installs every
  wired runtime into a throwaway target and checks that a second run changes nothing.
- **manual** — there is no installer target (DeepSeek is a model provider, not a host); the adapter README lists
  the exact steps.

## Runtime tiers

Maintaining real parity across 35 distinct runtimes is infeasible — each host changes its hook/skill
format every release. This repo therefore adopts a **two-tier system**:

### Tier 1 — Guaranteed (gated)

Three runtimes are **verified mechanically on every commit** and enjoy real parity:

| # | Runtime | Skill load | Loop drive | Hooks | Feedback | Install | Adapter |
|---|---|---|---|---|---|---|---|
| 1 | **Claude Code** | `.claude/skills/` + `.claude-plugin/` | `Stop` hook | ✅ full | N1 (hook) + N3 | wired | [claude](claude/README.md) |
| 2 | **Codex** | `AGENTS.md` → `SKILL.md` | self-paced | ⚠️ partial | N2 (transcript) + N3 | wired | [codex](codex/README.md) |
| 3 | **Cursor** | `.cursor-plugin/` + `.claude/skills/` | `stop` + `afterAgentResponse` | ✅ full | N1 (hook) + N3 | wired | [cursor](cursor/README.md) |

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

Thirty-two runtimes are documented and supported on a best-effort basis — contributions welcome,
no gate, no parity promise per release:

| # | Runtime | Skill load | Loop drive | Hooks | Feedback | Install | Adapter |
|---|---|---|---|---|---|---|---|
| 4 | **VS Code (Copilot)** | `.github/copilot-instructions.md` | self-paced (tasks) | ⚠️ tasks | N2 (transcript) + N3 | wired | [vscode](vscode/README.md) |
| 5 | **Grok** | `~/.grok/skills` + `~/.grok/rules` + `AGENTS.md` | self-paced | — | N2 + N3 | wired | [grok](grok/README.md) |
| 6 | **Antigravity** | rules / `AGENTS.md` | self-paced | ⚠️ | N2 (transcript) + N3 | wired | [antigravity](antigravity/README.md) |
| 7 | **Kiro** | `.kiro/steering/` | self-paced (specs) | ⚠️ | N2 (transcript) + N3 | wired | [kiro](kiro/README.md) |
| 8 | **OpenCode** | `AGENTS.md` + config | self-paced | ⚠️ | N2 (transcript) + N3 | wired | [opencode](opencode/README.md) |
| 9 | **Gemini** (CLI / Code Assist) | `GEMINI.md` → `SKILL.md` | self-paced | ⚠️ | N2 (transcript) + N3 | wired | [gemini](gemini/README.md) |
| 10 | **Kimi** | `AGENTS.md` | self-paced | — | N2 (transcript) + N3 | wired | [kimi](kimi/README.md) |
| 11 | **Qwen** (Code / CLI) | `QWEN.md` | self-paced | — | N2 (transcript) + N3 | wired | [qwen](qwen/README.md) |
| 12 | **DeepSeek** | none: a model provider, run through a wired host | the host's | — | the host's | manual | [deepseek](deepseek/README.md) |
| 13 | **Aider** | `CONVENTIONS.md` (read) | self-paced | ❌ | N2 (inlined transcript) + N3 | wired | [aider](aider/README.md) |
| 14 | **Simplicio Agent** *(formerly Hermes)* | native skill recall | native loop | ✅ native | N1-equiv (native tick) + N3 | wired | [simplicio_agent](simplicio_agent/README.md) |
| 15 | **OpenClaw** | plugin SDK / `skills/` | native scheduler | ✅ native | N1-equiv (native tick) + N3 | wired | [openclaw](openclaw/README.md) |
| 16 | **Orca** *(client opt-in only — not default)* | via inner agent (`.claude/skills/` + `AGENTS.md`) | **no core Orca hook**; inner agent hook / self-paced if client installed Orca | — | N1/N2 (inner) + N3 | wired | [orca](orca/README.md) |
| 17 | **GitHub Copilot** | `.github/copilot-instructions.md` | self-paced | — | N2 (transcript) + N3 | wired | [github-copilot](github-copilot/README.md) |
| 18 | **MiMo Code** | `AGENTS.md` | self-paced | — | N2 (transcript) + N3 | wired | [mimo-code](mimo-code/README.md) |
| 19 | **Amp** | `AGENTS.md` (+ native `.claude/skills/`) | self-paced | — | N2 (transcript) + N3 | wired | [amp](amp/README.md) |
| 20 | **OpenClaude** | `AGENTS.md` | self-paced | — | N2 (transcript) + N3 | wired | [openclaude](openclaude/README.md) |
| 21 | **Pi** | `AGENTS.md` | self-paced | — | N2 (transcript) + N3 | wired | [pi](pi/README.md) |
| 22 | **oh-my-pi** | `AGENTS.md` (+ native `.claude/skills/`) | self-paced | — | N2 (transcript) + N3 | wired | [oh-my-pi](oh-my-pi/README.md) |
| 23 | **Devin** | `AGENTS.md` | self-paced | — | N2 (transcript) + N3 | wired | [devin](devin/README.md) |
| 24 | **goose** | `AGENTS.md` | self-paced | — | N2 (transcript) + N3 | wired | [goose](goose/README.md) |
| 25 | **Auggie** | `AGENTS.md` | self-paced | — | N2 (transcript) + N3 | wired | [auggie](auggie/README.md) |
| 26 | **Autohand Code** | `AGENTS.md` | self-paced | — | N2 (transcript) + N3 | wired | [autohand](autohand/README.md) |
| 27 | **Charm** (Crush) | `AGENTS.md` (+ native `.claude/skills/`) | self-paced | — | N2 (transcript) + N3 | wired | [charm](charm/README.md) |
| 28 | **Cline** | `AGENTS.md` | self-paced | — | N2 (transcript) + N3 | wired | [cline](cline/README.md) |
| 29 | **Codebuff** | `AGENTS.md` | self-paced | — | N2 (transcript) + N3 | wired | [codebuff](codebuff/README.md) |
| 30 | **Command Code** | `AGENTS.md` | self-paced | — | N2 (transcript) + N3 | wired | [command-code](command-code/README.md) |
| 31 | **Continue** | `.continue/rules/simplicio-loop.md` | self-paced | — | N2 (transcript) + N3 | wired | [continue](continue/README.md) |
| 32 | **Droid** | `AGENTS.md` | self-paced | — | N2 (transcript) + N3 | wired | [droid](droid/README.md) |
| 33 | **Kilo Code** | `AGENTS.md` | self-paced | — | N2 (transcript) + N3 | wired | [kilocode](kilocode/README.md) |
| 34 | **Mistral Vibe** | `AGENTS.md` | self-paced | — | N2 (transcript) + N3 | wired | [mistral-vibe](mistral-vibe/README.md) |
| 35 | **Rovo Dev** | `AGENTS.md` | self-paced | — | N2 (transcript) + N3 | wired | [rovo-dev](rovo-dev/README.md) |

Every Tier 2 row is **best-effort, not gated**: the installer writes the files the host's documentation
says it reads (each catalog entry links that documentation) and `scripts/verify_adapters.py` proves the
files land, but launching the host is a manual smoke per adapter README. Antigravity's IDE-side config is
community-reported.

`hermes` is the upstream id of Simplicio Agent (formerly Hermes): the catalog entry `hermes` has the alias
`simplicio_agent`, which is the adapter directory and the installer runtime. The `hermes` directory is a
**legacy shim**, not a separate runtime — see [hermes/README.md](hermes/README.md). It installs/binds
identically to `simplicio_agent` during the compat window and will be removed after the deprecation threshold (one release cycle without
a regression report), per the adapter-rebrand rollback policy (#262).

Legend: ✅ first-class · ⚠️ partial / via a generic mechanism · ❌ none (degrade to fallback) · — none wired
by the installer (the loop self-paces).

## Acompanhando o progresso (issue #303, EPIC #296)

Three feedback levels, each a strict superset of the one before — no runtime needs new code to
get the last one:

- **N1 (hook).** Where a real stop-hook exists (Claude Code, Cursor, and the native loops of
  Simplicio Agent/OpenClaw), the host injects fase/etapa/item/ACs/% directly into the re-feed
  header (`hooks/loop_stop.py`) — zero extra action from the user.
- **N2 (transcript).** The turn-header contract (SKILL.md § Output: first line of every turn =
  `render --turn-header`) is normative for ALL 35 runtimes, hook or not — it must be reflected in
  whichever surface that host loads the skill FROM (`AGENTS.md`, `GEMINI.md`, `CONVENTIONS.md`,
  `.github/copilot-instructions.md`, `.kiro/steering/`, OpenCode config, …), never forked by hand.
- **N3 (file, universal denominator).** `.simplicio-loop/orchestrator/loop/PROGRESS.md` + `progress.json` are
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
# <runtime> = the `install.runtime` of a wired host in simplicio_loop/_catalog/harnesses.json:
#   claude codex cursor vscode grok antigravity kiro opencode gemini aider simplicio_agent openclaw orca
#   github-copilot mimo-code amp openclaude pi oh-my-pi devin goose auggie autohand charm cline codebuff
#   command-code continue droid kilocode kimi mistral-vibe qwen rovo-dev
#   (hermes is still accepted as a legacy alias for simplicio_agent)
# omit <runtime> to auto-detect
# deepseek is a model provider, not a host: adapters/deepseek/README.md lists the manual steps
```

The installer copies the 7 skills into the runtime's skills location and wires the loop hooks
where supported. There is no Runtime/MCP backend in this stack.

## What degrades gracefully — and what does not

- **No stop-hook** → the loop self-paces via the host scheduler (`simplicio-loop` "No-hook
  fallback"). Same exit conditions (evidence-gated promise, cap, STOP). This degradation is
  always allowed — it's a drive-mechanism choice, not a policy violation.

- **No skill loader** (e.g. Aider) → the adapter inlines `SKILL.md` as the runtime's
  conventions/instructions file. Larger context, identical behavior. Native capabilities remain
  optional independently of the skill-loading mechanism.

The promise: **same protocol, same gates, same safety on all 35 — Tier 1 verified mechanically,
Tier 2 best-effort with contributions welcome.**

## Verifying an adapter

The installer's contract (skills copied · entry file marked · hooks present/wired · worker
scripts copied · `scripts/loop_progress.py selftest` runs GREEN from inside the installed
target — #303 AC5, a dedicated per-runtime assertion, not one inferred from the sweep merely
exiting 0) is verified end-to-end per runtime by `scripts/verify_adapters.py`, which installs
into a throwaway target and asserts each promise — no risk to your real config:

```bash
python3 scripts/verify_adapters.py tier1                        # Tier 1 — gated, run on every commit
python3 scripts/verify_adapters.py claude codex cursor          # same as above
python3 scripts/verify_adapters.py                              # every installer runtime (~20s in total)
python3 scripts/verify_adapters.py antigravity kiro opencode aider   # a Tier-2 subset
```

`scripts/claims_audit.py` (check 7, part of `python3 scripts/check.py`) runs the fast, single-runtime
form (`verify_adapters.py claude`, ~15s) on every gate so the Tier-1 install contract is never dead
assurance — it does NOT run the full sweep above; run that manually before a release.

That covers everything up to launching the runtime itself. The final manual smoke — open the
runtime, run `/simplicio-loop <small task>`, confirm the loop drives and the gates fire — is the
one step a file-level harness can't do; do it once per runtime per the adapter's README.
