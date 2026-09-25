# ADR-0010: Standalone is a first-class execution route

## Status

Accepted.

## Decision

`simplicio-py` supports a deterministic `standalone` route as a permanent
local execution mode. A direct Fast changeset is admitted by the Dev CLI,
validated, materialized through the existing atomic transaction boundary, and
reported with an explicit standalone receipt. It does not require
`SIMPLICIO_RUNTIME_URL`, Runtime authorization, a provider, or an embedded LLM.

`auto` on the direct changeset entrypoint resolves to `standalone`, because a
changeset already contains the externally produced deterministic intent. The
route is frozen before staging. Runtime-backed authorization remains owned by
the task/integrated entrypoint; passing `--mode integrated` to the direct
changeset entrypoint is refused instead of silently downgrading.

The historical migration policy and its legacy environment variables remain
compatibility surfaces for older task callers. They do not redefine the
standalone changeset contract.

## Consequences

- Offline and air-gapped direct changeset execution has no Runtime/provider
  probe as part of route selection.
- Receipts identify `execution_mode.effective=standalone`,
  `runtime_required=false`, and `provider_calls=0`.
- Runtime authorization is never simulated by the standalone route.
- The existing transaction implementation remains the single atomic effect
  boundary, so idempotency, rollback, and recovery evidence are preserved.
