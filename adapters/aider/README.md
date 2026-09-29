# Aider adapter

Aider is a pair-programming CLI with no skill system and no hooks. The adapter inlines the
protocol as Aider's conventions file and self-paces the loop from the shell. Everything degrades
to the LLM fallback — same gates, larger context.

## Install

```bash
bash scripts/install.sh aider
```

The installer writes `CONVENTIONS.md` (the orchestrator protocol, condensed via
`simplicio-compress` so it costs less every turn) and configures `.aider.conf.yml` to always
read it:

```yaml
read: [CONVENTIONS.md]
```

## Loop drive — self-paced from the shell

No hooks. Drive the loop with Aider's non-interactive mode on a tick:

```bash
*/2 * * * *  cd /repo && aider --message "/simplicio-tasks continue the open queue" --yes-always
```

`simplicio-loop` runs in self-paced mode: one iteration per invocation, exit on the
evidence-gated promise, the cap, spindle handoff, or explicit STOP. Keep `--yes-always` OFF for
irreversible-op safety unless a human gate is otherwise wired.

## Token economy

This matters most here (no native bind). Route every heavy command through the wrapper:

```bash
python3 hooks/orient_clamp.py -- pytest -q
```

and keep `CONVENTIONS.md` compressed (input-side savings amortized across every turn).

## Native bind

None. The LLM performs each extension point with git/gh/file tools — the documented fallback.

## Use

```
aider --message "/simplicio-tasks finish all the open issues"
```

## Run simplicio-loop

Tell the agent `/simplicio-loop <task>`. It runs `simplicio-loop "<task>" --verify "<tests>"` through the host's shell tool, writes the JSON plan the command prints to `plan_path` and runs the printed `apply` command; `simplicio-dev-cli` makes every edit. `simplicio-loop` must be on the PATH of the machine where the host runs its shell (`pip install simplicio-loop`). Full flow: `.claude/skills/simplicio-loop/SKILL.md`.

## Progresso do run

`CONVENTIONS.md` inlines SKILL.md verbatim, so the turn-header contract (§ Output) is part of
what Aider reads every turn — the model echoes `render --turn-header` in its own reply. Universal
fallback (N3): open `.simplicio-loop/orchestrator/loop/PROGRESS.md` in the editor.

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

