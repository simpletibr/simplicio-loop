# Aider adapter

Aider is a pair-programming CLI with no skill system and no hooks. The adapter inlines the
protocol as Aider's conventions file and self-paces the loop from the shell. Everything degrades
to the LLM fallback — same gates, larger context.

## Install

```bash
bash scripts/install.sh aider
```

The installer writes `CONVENTIONS.md` (the marker block that points at the loop skill) and creates
`.aider.conf.yml` when there is none, so aider reads both files on every launch:

```yaml
read:
  - CONVENTIONS.md
  - .claude/skills/simplicio-loop/SKILL.md
```

An existing `.aider.conf.yml` is left alone: add those two entries under `read:` by hand.

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

`.aider.conf.yml` makes aider read `SKILL.md` on every launch, so the turn-header contract (§ Output) is part of
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

On Windows: run the public installer (`irm https://raw.githubusercontent.com/simpletibr/simplicio/master/install.ps1 | iex`); it installs the Runtime and simplicio-loop (with Mapper and Dev CLI) via pip. Then run `simplicio-loop doctor`.

