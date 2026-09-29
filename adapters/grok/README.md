# Grok adapter (self-paced)

Grok Build / Grok CLI has **no stop-hook** in this matrix. The loop is **self-paced**.
`adapters/grok/adapter.py` normalizes tool calls against a bounded Simplicio catalog.
Unknown tools never fall back to shell. Live xAI API stays UNVERIFIED unless
`SIMPLICIO_GROK_LIVE=1`. This adapter stores no credentials.

Grok Build / Grok CLI has **no stop-hook** in this matrix. The loop is **self-paced**:
same scratchpad, journal, promise, and operator stack as Claude — the host re-invokes
each turn (or the operator ticks manually).

## Install

```bash
python3 scripts/install_lib.py grok --global
python3 scripts/host_rule_sync.py --global --json
```

- Skills → `~/.grok/skills/` (and `~/.agents/skills/` via host_rule_sync mirrors)
- Always-on rule → `~/.grok/rules/simplicio-loop-operator-flow.md`
- Strict env → `~/.simplicio-loop/loop-env.ps1` / `loop-env.sh`

## MUST

1. Source strict env (`loop-env`).
2. `simplicio-loop preflight --strict --json`
3. Mapper survey · Fast hot path · dev-cli mutate under STRICT
4. Never mass hand-edit as primary path when STRICT is on
5. Orca only if client requested (`CLIENT_INTEGRATIONS`)

## Invoke

```text
/simplicio-loop <body of work>
# or
python3 scripts/arm_drain_prism.py --repo . --slots 4 --json
```

See `docs/MULTI_LLM_CONTRACT.md`.

## Loop drive — self-paced

Grok has no stop hook in this matrix: the agent re-reads `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn and ends each message with `DONE | NEXT | BLOCKED`. Progress: the first line of every turn is `python3 scripts/loop_progress.py render --turn-header` (N2), and `.simplicio-loop/orchestrator/loop/PROGRESS.md` is regenerated every turn (N3).

## Run simplicio-loop

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through the host's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where the host runs its shell (`pip install simplicio-loop`). Full flow: `.claude/skills/simplicio-loop/SKILL.md`.

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

