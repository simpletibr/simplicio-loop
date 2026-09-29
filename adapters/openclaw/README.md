# OpenClaw adapter

OpenClaw is a multi-channel agent gateway (Node) with a plugin SDK exposing many named
extension points. It is both a target runtime AND a deployment surface — run simplicio-tasks
unattended, reachable from WhatsApp/Slack/Discord/Telegram/etc.

## Install

```bash
bash scripts/install.sh openclaw
```

The installer places the 7 skills under OpenClaw's skills tree and registers a plugin that maps
the OpenClaw SDK extension points (approval-*, channel-*, agent-*) onto the simplicio
contract — notably `notify`/`human_gate` (async approvals over a chat channel) and `watcher`
(the gateway's scheduler).

## Loop drive — native scheduler + channel approvals

The gateway's scheduler drives the loop; `simplicio-loop`'s evidence-gated promise governs exit.
Irreversible-op approvals route through `human_gate` → a chat message awaiting a human reply
(headless rule: no reply = block the destructive op, do the safe part).

## Native bind — plugin SDK

| Simplicio point | OpenClaw SDK |
|---|---|
| `notify` / `human_gate` | `channel-*` send + approval-request handlers |
| `watcher` | gateway scheduler |
| `execute` | agent fan-out across channel sessions |
| `status` | channel digest messages |

## Token economy

`orient_clamp.py` works as-is on the host; channel digests use the HUMAN density tier, internal
reports the MACHINE tier.

## Use

Message the bot on any connected channel: `/simplicio-tasks finish all the open issues`. Progress
digests and approval prompts come back on the same channel.

## Run simplicio-loop

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through the host's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where the host runs its shell (`pip install simplicio-loop`). Full flow: `.claude/skills/simplicio-loop/SKILL.md`.

## Progresso do run

Native scheduler (N1-equivalent): call `loop_progress.py emit`/`render --turn-header` at the
plugin SDK's own tick points, same contract as any other extension point. Universal fallback (N3):
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

