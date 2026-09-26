# Codex adapter

Codex reads `AGENTS.md` as its standing instructions. Point it at the skill; drive the loop
self-paced (Codex has no general stop-hook); bind natively via MCP or the Python adapter.

## Install

```bash
bash scripts/install.sh codex            # writes/links AGENTS.md → SKILL.md, copies skills
```

The installer ensures `AGENTS.md` at the repo root references
`.claude/skills/simplicio-tasks/SKILL.md` (this repo's `AGENTS.md` already does). Codex loads
that on every run.

## Loop drive — self-paced

Codex `.codex/hooks.json` is empty. This adapter reports
`native_interception=false` and `governed_effect_path=true`. Raw shell/write
tools without MCP are blocked or marked unenforceable — never green.

Codex has no stop-hook, so `simplicio-loop` self-paces: each run does one iteration, checks the
evidence-gated promise, and reschedules itself via the host scheduler until the promise is true,
the cap is hit, spindle handoff is latched, or STOP is signaled. Drive ticks with `codex exec`
on a cron / CI schedule:

```bash
*/2 * * * *  cd /repo && codex exec "/simplicio-tasks continue the open queue"
```

## Token economy

`orient_clamp.py` works as-is. Add it to your `AGENTS.md` command conventions so Codex routes
heavy commands through it:

```
python3 hooks/orient_clamp.py -- <build/test/diff command>
```

## Native bind (optional)

`simplicio-runtime` native binding is optional on Codex. A missing/unreachable bind reports
explicit degraded mode while the self-paced standalone loop remains available:

```bash
pip install -U simplicio-installer && simplicio install --global   # registers Codex's MCP client
# or use the Python adapter at simplicio-runtime/agent/codex_responses_adapter.py
```

Use `simplicio doctor --json` to confirm the bind before scheduling ticks.

## MCP config

- **Config file:** `~/.codex/config.toml`, under an `[mcp_servers.<name>]` table.
- **Snippet:**

```toml
[mcp_servers.simplicio]
command = "simplicio"
args = ["serve", "--mcp", "--stdio"]
cwd = "/path/to/your/repo"
```

- **Verify:** `simplicio doctor --json | grep -A2 mcp-host-registration`, or `codex mcp list` if
  your Codex CLI version ships that subcommand. Tier: **verified** — Codex is a gated Tier 1
  runtime (`scripts/verify_adapters.py codex`).

## Use

```
codex exec "/simplicio-tasks finish all the open issues"
```

## Progresso do run

Self-paced (N2): the tick echoes `python3 scripts/loop_progress.py render --turn-header` at the
start of every turn — the % is right there in the transcript. For a live panel outside the
transcript (N3, universal): `watch -n5 cat .simplicio-loop/orchestrator/loop/PROGRESS.md`.

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

