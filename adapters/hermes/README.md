# Hermes adapter (legacy alias)

**This is a legacy alias.** `hermes` was renamed to `simplicio_agent` as the canonical adapter
ID — see [../simplicio_agent/README.md](../simplicio_agent/README.md) for the full adapter
documentation. Treat `hermes` exactly as `simplicio_agent`: same native bindings, same install
contract, same loop behavior; only the id/binary/config-path names differ during the compat
window.

```bash
bash scripts/install.sh hermes          # still works — installs identically to simplicio_agent
```

Kept only so existing installs, saved scripts, and `HERMES_PROFILE` env usage keep working
without a breaking change. It will be removed once the deprecation threshold in
`adapters/MATRIX.md` is reached — migrate to `simplicio_agent` (binary `simplicio-agent`, config
`~/.simplicio-agent/config.yaml`) when convenient.

## Progresso do run

Same as [`simplicio_agent`](../simplicio_agent/README.md#progresso-do-run) — this is a legacy
shim, not a separate feedback surface.

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

