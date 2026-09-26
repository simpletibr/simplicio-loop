# `simplicio.loop-execution/v2`

This is the canonical universal execution envelope for the existing Loop
execution family. It is produced and validated by the pure
`simplicio_loop.execution_envelope` core and is transport-neutral across:

`run`, `tick`, `batch`, `wave`, and `prism`.

## Why v2

The published `simplicio.loop-execution/v1` receipt is intentionally a
verified-success projection. Its fixed chain and `result.verified: true` cannot
represent a partial result, an execution error, or an expected physical-governor
block without changing the meaning of existing v1 fields. v2 is therefore an
explicit successor, not a second contract family.

Compatibility is one-way and structural:

- Existing v1 receipts remain valid v1 receipts and are not rewritten.
- A v1 receipt is the verified-success subset of the execution family; use
  `is_v1_receipt_compatible()` to recognize that shape.
- A v2 envelope never masquerades as v1. Consumers that only understand v1 may
  accept only the v1 verified-success projection and must fail closed for other
  v2 statuses.

## Envelope rules

- `schema` is always exactly `simplicio.loop-execution/v2`.
- `flow` is one of the six transport names above; the envelope shape does not
  change by transport.
- `tasks` are ordered, have unique `task_id` values, and dependencies must refer
  to earlier tasks in an acyclic graph. `task_order` repeats the canonical order
  explicitly for consumers that do not preserve array order.
- `phases` always contain `mapper`, `dev_cli`, and `loop`. A phase with
  `provider_called: true` must carry a structured `receipt`; a phase that did not
  call a provider carries `receipt: null`.
- `execution_report` reuses `simplicio.execution-report/v1`. Unknown metrics are
  represented by `null`; observed metrics are finite, non-negative numbers.
- `complete` requires all tasks and phases complete, non-empty evidence, and
  `completion: {"verified": true, "oracle": "MEASURED"}`. Every other status
  rejects a true completion claim.
- `expected_governor_blocked` requires an explicit expected blocked governor
  decision and proves that no provider was called.
- Credential material is outside this payload boundary. Sensitive credential
  field names are rejected recursively rather than stripped or redacted.

The JSON Schema is [`receipt.schema.json`](receipt.schema.json). The Python core
is intentionally side-effect-free and performs the cross-field checks that JSON
Schema alone cannot express (DAG order/cycles, provider/receipt coupling, and
false-completion rejection).
