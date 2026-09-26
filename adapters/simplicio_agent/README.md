# Simplicio Agent adapter

Simplicio Agent (formerly Hermes) is a native simplicio runtime: it has a real agent/sub-agent
fabric and binds the extension points directly (no MCP shim needed). This is the deepest
integration — most steps run deterministically at near-zero token cost.

## Install

```bash
bash scripts/install.sh simplicio_agent
```

The installer places the 7 skills where Simplicio Agent's skill-recall finds them and confirms
the native bindings are active.

## Loop drive — native loop

Simplicio Agent drives the loop natively (its scheduler IS the watcher). `simplicio-loop` binds
to the native durable scheduler; the evidence-gated completion-promise, cap, and STOP guards are
enforced by the runtime, not a shell hook.

## Native bind — extension points (optional acceleration)

`simplicio-runtime` native binding is optional on Simplicio Agent. When it is unavailable, run
the standard-tool fallback and keep the protocol's normal evidence and safety gates. Use
`simplicio doctor --json` to diagnose an installed bind.

Simplicio Agent binds, among others: `orient`, `recall`, `deterministic_edit`, `claim`,
`worktree`, `diagnostics`, `validate`, `pr`, `watcher`, `savings_ledger`, `model_route`. When
bound, the orchestrator delegates to them and the satellite skills become near-free:

| Satellite | Native binding |
|---|---|
| simplicio-orient | `orient` · `shell_exec` · `compress` (native clamp + tee) |
| simplicio-loop | `watcher` · `durable_workflow` (native loop) |
| simplicio-review | native parallel sub-agent fan-out |
| simplicio-compress | native `transform_guard` + `savings_ledger` |
| simplicio-learn | native `trajectory` · `learn` · `recall` |

## Token economy

Native: the runtime measures REAL token spend via `savings_ledger`; the savings line is exact,
not estimated.

## Use

```
simplicio-agent run "/simplicio-tasks finish all the open issues"
```

## Migrating from Hermes

`simplicio-agent` is the same binary/CLI previously distributed as `hermes` — the config path
moved from `~/.hermes/config.yaml` to `~/.simplicio-agent/config.yaml` and logs from
`~/.hermes/logs/` to `~/.simplicio-agent/logs/`. The [`hermes` adapter](../hermes/README.md) is
kept as a legacy shim for one release cycle; scripts in this repo detect either binary and warn
when they fall back to the legacy one.

## Progresso do run

Native loop (N1-equivalent): wire the native tick to call `python3 scripts/loop_progress.py emit
--step <step> --status begin|end` at its own extension points and `render --turn-header` before
re-feeding — same contract, native transport instead of a hook file. Universal fallback (N3): open
`.simplicio-loop/orchestrator/loop/PROGRESS.md` (auto-regenerated every turn) regardless of native wiring.

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

