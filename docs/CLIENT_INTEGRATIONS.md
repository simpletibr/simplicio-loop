# Client integrations (opt-in only)

## Policy

**Default = none.** The core product is Loop + Mapper + Fast + Dev-CLI (+ Runtime when healthy).
Host-specific projections (Orca cards, Linear, Jira, chat, …) are **never** auto-wired into the
lifecycle hot path. They turn on only when the **client requests** them.

## How to enable

### Env (session / CI)

```bash
export SIMPLICIO_LOOP_CLIENT_INTEGRATIONS=orca
# multiple: orca,linear
```

### Repo file (durable client contract)

`.simplicio-loop/client-integrations.json`:

```json
{
  "schema": "simplicio.client-integrations/v1",
  "integrations": ["orca"]
}
```

### Legacy Orca flag

`SIMPLICIO_LOOP_ORCA_LIFECYCLE_SYNC=1` still enables **only** the `orca` integration (compat).
Prefer `SIMPLICIO_LOOP_CLIENT_INTEGRATIONS`.

## What was removed from the default path

| Before | After |
|--------|--------|
| Every runner lifecycle event called `_sync_orca_lifecycle` | Call only if `integration_enabled("orca")` |
| Intake text assumed “requires Orca worktree” | Generic multi-host/worktree language; no Orca default |
| Orca adapter looked like a standard always-on host | Documented as **client opt-in install** |

## Known names (extensible)

`orca`, `linear`, `jira`, `azure-devops`, `slack`, `discord` — unknown names are kept for
forward compatibility but do nothing until a handler exists.

## Inspect

```bash
python3 -c "from simplicio_loop.client_integrations import describe; print(describe())"
```
