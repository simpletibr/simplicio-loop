# Orca adapter (**client opt-in only**)

> **Not part of the default Simplicio armada.** Install and enable Orca **only when the client
> contracted the Orca host**. Core Loop / Mapper / Fast / Dev-CLI never depend on Orca.
> Lifecycle card sync stays **off** unless the client enables the `orca` integration
> (`SIMPLICIO_LOOP_CLIENT_INTEGRATIONS=orca` or `.simplicio-loop/client-integrations.json`).
> See `docs/CLIENT_INTEGRATIONS.md` and `simplicio_loop/client_integrations.py`.

[Orca](https://www.onorca.dev/docs) is a desktop **worktree IDE for AI coding agents**: it runs
multiple agent CLIs (Claude Code, Codex, Cursor CLI) in parallel, each task in its own isolated
**git worktree** with its own terminal and browser tab, plus agent hooks & memory, worktree
checkpoints, scheduled automations, and an MCP/skills registry.

Orca is a **host of hosts**: the simplicio-loop protocol runs inside whichever inner agent CLI
Orca drives. The adapter therefore installs into the *repo* (which every Orca worktree sees), and
the inner runtime picks the skills up natively. **There is no Orca stop-hook in the core loop.**

## Install (only if client requested Orca)

```bash
bash scripts/install.sh orca            # macOS/Linux
pwsh scripts/install.ps1 orca           # Windows
# enable lifecycle card projection (optional, client-requested):
export SIMPLICIO_LOOP_CLIENT_INTEGRATIONS=orca
# or: echo '{"schema":"simplicio.client-integrations/v1","integrations":["orca"]}' > .simplicio-loop/client-integrations.json
```

The installer copies the 7 skills into `.claude/skills/` and writes the idempotent
`simplicio-loop` marker block into `AGENTS.md` — the two discovery surfaces the inner agents use
(Claude Code/Cursor read the skills tree; Codex reads `AGENTS.md`). Both are committed repo
files, so **every Orca worktree inherits them automatically** — no per-task setup.

## Skill load

Via the inner agent: `.claude/skills/` (Claude Code, Cursor CLI) or `AGENTS.md → SKILL.md`
(Codex). Orca's own skills registry can additionally surface `/simplicio-loop` as a first-class
command; that registration is optional and never replaces the repo-level install.

## Loop drive — inner hook where available, else scheduled automations

- **Inner agent = Claude Code or Cursor CLI** → the real stop-hook drive applies unchanged
  (`hooks/loop_stop.py` / `loop_capture.py`), exactly as in the [claude](../claude/README.md) /
  [cursor](../cursor/README.md) adapters.
- **Inner agent = Codex (or anything hook-less)** → self-paced drive via **Orca scheduled
  automations**: schedule a tick that re-invokes `/simplicio-loop` per the skill's "Self-paced
  drive" section. Same exit conditions (evidence-gated promise, `max_iterations` cap, STOP).

**Worktree isolation fits the loop's state model.** All loop state (`.simplicio-loop/orchestrator/loop/`,
`.simplicio-loop/orchestrator/backlog/`) is per-worktree, so each Orca task runs its own independent loop — one
scratchpad, one journal, one anchor per task, with no cross-task interference. Orca's worktree
checkpoints compose with (never replace) the loop's own journal + evidence gates.

## Native bind — MCP (optional)

`simplicio-runtime` via Orca's MCP registry is optional. A missing/unreachable bind reports
explicit degraded mode while the standalone loop remains available.
`simplicio doctor --json` confirms an installed runtime inside the Orca session.

## MCP config

- **Config file:** Orca's own skills/MCP registry (per [onorca.dev docs](https://www.onorca.dev/docs)),
  which registers servers available to every inner agent session in a worktree. Where the inner
  agent is Claude Code or Cursor, its own MCP config file (see the
  [claude](../claude/README.md#mcp-config) / [cursor](../cursor/README.md#mcp-config) sections)
  also applies inside that worktree.
- **Snippet** (generic form registered with Orca's registry):

```json
{ "mcpServers": { "simplicio": { "command": "simplicio", "args": ["serve", "--mcp", "--stdio"], "cwd": "/path/to/worktree" } } }
```

- **Verify:** `simplicio doctor --json | grep -A2 mcp-host-registration` from inside the Orca
  worktree terminal. Tier: **best-effort** — Orca is Tier 2; the registry's own MCP-status surface
  (if any) is the more authoritative check when available.

## Token economy

`orient_clamp.py` works as-is in every Orca terminal (`python3 hooks/orient_clamp.py -- <cmd>`),
no wiring.

## Use

Open a task in Orca (it allocates the worktree), then in the task's agent session:

```
/simplicio-loop finish all the open issues
```

Manual smoke (the one step a file-level harness can't do): run a small `/simplicio-loop` task in
an Orca worktree, confirm the loop drives (hook or scheduled tick), the gates fire, and the state
stays inside that worktree's `.simplicio-loop/orchestrator/`.

## Progresso do run

Inner-agent hook or self-paced tick (N1/N2 depending on how the inner agent is configured): the
turn-header contract applies identically inside the Orca worktree. Universal fallback (N3): open
`.simplicio-loop/orchestrator/loop/PROGRESS.md` inside that worktree (auto-regenerated every turn, scoped to the
worktree like all other loop state).

## Status e comentários automáticos

Quando o run está dentro de um worktree Orca ativo, o loop consulta `orca worktree current`
e atualiza somente o card desse worktree com `orca worktree set`: o status usa `todo`,
`in-progress`, `in-review` ou `completed`, e o comentário contém o estado lifecycle, run e
uma mensagem curta. Fora do Orca, a sincronização é um no-op tipado e não toca outro card.

No GitHub, o workflow de lifecycle mantém o comentário canônico, a label e o `Status` do
Project pertencente ao próprio repositório; se a issue ainda não estiver no Project, ela é
adicionada antes da movimentação. `SIMPLICIO_PROJECT_NUMBER` continua sendo aceito para
selecionar explicitamente um Project quando houver mais de um.

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

