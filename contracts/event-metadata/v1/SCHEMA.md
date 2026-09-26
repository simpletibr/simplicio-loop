<!-- simplicio-contract:begin -->
contract: event-metadata/v1
schema: simplicio.contract-doc/v1
purpose: Versioned metadata envelope for append-only loop events and their progress projections.
rules: The JSON schema next to this file is authoritative; mutable data lives in the footer, never in this header.
<!-- simplicio-contract:end -->

# `simplicio.event-metadata/v1`

Versioned metadata envelope for append-only loop events and their progress projections.

| Field | Collection | Task | Scenario |
|---|---|---|---|
| `schema` | required, `simplicio.event-metadata/v1` | same | same |
| `scope` | `collection` | `task` | `scenario` |
| `event_id` | required | required | required |
| `run_id` | required | required | required |
| `task_id` | explicit `null` is valid | required, non-empty | required, non-empty |
| `ac_ids` | optional | optional | required, non-empty |
| `receipt` or `blocker` | one required for measured metadata | one required | one required |

Collection lifecycle events (`contract_frozen`, `watcher_challenge`, phase transitions, and
mapping/planning milestones) use `task_id: null`. This is an intentional policy, not missing
metadata. Task and scenario events remain fail-closed when `task_id` is absent; diagnostics
include `event_id`, `kind`, and `scope`.

New events carry `schema`, `scope`, `event_id`, `run_id`, and `task_id` when applicable. The
append-only ledger is never rewritten. A historical event without `scope` is read through the
legacy compatibility rule and its scope is inferred from the event kind; the source record is
not modified and the projection identifies any genuinely invalid metadata.

The progress JSON envelope exposes the same policy under `event_metadata_policy`, so consumers
can distinguish an expected collection null from a real task/scenario blocker. The independent
watcher, evidence, and oracle gates consume the normalized metadata status and never promote a
metadata failure to success.