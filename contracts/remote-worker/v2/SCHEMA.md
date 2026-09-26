<!-- simplicio-contract:begin -->
contract: remote-worker/v2
schema: simplicio.contract-doc/v1
purpose: Immutable task envelope for the real multi-device worker protocol (issue #286):
rules: The JSON schema next to this file is authoritative; mutable data lives in the footer, never in this header.
<!-- simplicio-contract:end -->

# `simplicio.remote-worker/v2`

Immutable task envelope for the real multi-device worker protocol (issue #286):

`enqueue → pull → claim → materialize context → execute → heartbeat → validate receipt → complete/release/cancel`

Files:

- `schema.json`: envelope shape published by the Producer/Coordinator into the
  `simplicio.queue/v1` store (`RemoteQueue.enqueue(task_id, payload)`); a
  `RemoteWorkerDaemon` on a different device/process pulls, claims, and executes it.
- ADR: `docs/adr/0002-remote-worker-v2-protocol.md` — rationale, state machine, and how this
  relates to the lease/fencing envelope already implemented in
  `simplicio_loop/remote_queue.py` (`simplicio.queue/v1`).

Deliberately out of scope for this schema (owned by `simplicio.queue/v1` instead, so there is
exactly one source of truth for each):

- `attempt_id`, `lease_id`, `fencing_token`, `agent_id` — minted and enforced by the queue on
  `claim`/`heartbeat`/`complete`, never by the envelope.
- Receipt content — `simplicio_loop/receipt_verifier.py`'s `OPERATOR_RECEIPT_SCHEMA` /
  `EVIDENCE_RECEIPT_SCHEMA` already cover the operator/evidence receipt pair a completed
  attempt must produce; this envelope is the *input* to a worker's run, not its output.

## No secrets, ever

`schema.json`'s trailing `not/anyOf` block rejects `token`, `secret`, `credentials`, `env`, or
`transcript` keys outright — the context pack a worker receives must never carry a way to
authenticate anywhere; the worker's own already-provisioned queue credential (short-lived,
`scripts/short_lived_credentials.py`) is what it uses to talk back to the queue.

## `context_digest`

`sha256:<hex>` of the canonical (`json.dumps(..., sort_keys=True)`) serialization of
`{goal, acceptance_criteria, source, allowed_paths}`. A worker validates this digest against
its own recomputation *before* creating a workspace, and refuses the task on mismatch — this
is the "conferido por hash no worker" requirement from the issue, not merely a schema
property nobody checks.
