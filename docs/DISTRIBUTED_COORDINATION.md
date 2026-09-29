# Distributed coordination contract

This is the transport-neutral contract used when the same backlog is visible to
Codex, Claude, or another runtime on a different device. The backlog file may
live on a shared filesystem today; a remote queue can persist the same fields
without changing the worker protocol.

## Identity

Each participant has a `simplicio.agent-identity/v1` record with:

```json
{
  "agent_id": "agent-codex-a",
  "runtime": "codex",
  "device_id": "device-laptop-a",
  "session_id": "session-2026-07-11",
  "protocol": "simplicio-distributed/v1"
}
```

`agent_id` and `device_id` identify the participant across reconnects;
`session_id` changes on each runtime invocation. The identity is persisted by
`scripts/agent_identity.py` and may be overridden with `SIMPLICIO_*` variables.

## Claim, heartbeat, fencing

```text
next --agent-id ... --runtime ... --session-id ... --device-id ...
  -> lease.worker + lease.identity + monotonic fencing token
heartbeat --item ... --fence ... [same identity]
transition/done --item ... --fence ... [same identity]
```

The queue lock serializes claim/renew/transition. A lease expiry returns the
task to `ready`; a late worker cannot renew or finish it because both the
fencing token and the complete identity must match. Legacy callers remain
compatible when they use `--worker` plus `--fence` without an identity.

## Multi-device safety boundary

The local JSONL backend is safe only when all devices can atomically access the
same filesystem. A future HTTP/SQLite/Redis adapter MUST preserve the same
identity, lease, heartbeat, fencing, and compare-and-swap fields; it must not
silently downgrade to last-write-wins. Runtime adapters should show the
identity in task receipts, never expose another agent's prompt/context, and
re-query the source after reconnecting.

## Default fan-out

`execute_operator_batch` fans out independent tasks into isolated worktrees by
default; overlapping or unallocatable work falls back to a serialized lane. The
runner persists a stable identity at `.simplicio-loop/orchestrator/agent-identity.json`
(override with `SIMPLICIO_IDENTITY_FILE`), and `SIMPLICIO_RUNTIME` labels the runtime
(for example `codex` or `claude`). The shared-queue remote mode
(`SIMPLICIO_REMOTE_QUEUE_*`) was removed in 3.46.0.

## Context isolation and receipts

`simplicio_loop.agent_contract` is the shared boundary for every transport:

- `validate_identity()` rejects missing identity fields, unknown capabilities,
  and duplicate capabilities before a lease or runtime mutation is accepted.
- `build_context_pack()` emits only the assigned task, acceptance criteria,
  dependency IDs, and source paths explicitly allow-listed for that worker. It
  never includes prompts, transcripts, environment variables, or another
  worker's private state.
- `bind_receipt()` attaches the immutable `agent` record and rejects a receipt
  or context pack assigned to a different agent.

A reconnecting worker must present the same identity and fencing token; a
duplicate/replayed identity is rejected.

