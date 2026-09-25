# Operations projection v1

`OperationsProjection` ingests explicit versioned receipts and exposes a
bounded, deterministic read model for status/kind queries and snapshots. It
pins one repository and generation, rejects stale sequence regressions and
generation mixing, and reports incremental changed handles.

Fast does not read SQLite, own queues or journals, schedule work, grant leases,
reduce effects, or become completion authority. Mapper, Loop, Runtime, Dev CLI
and Resource Fabric remain canonical producers; their receipt contracts and
cross-platform operational fixtures are required before #347 can close.

The projection also exposes bounded slot/attempt queries, producer-reported
lease facts with derived `active` status at an explicit observation time, and
read-only status/kind statistics. It never acquires, renews, fences or releases
a lease; the producer remains authoritative.

Receipts may carry a `payload.causal_parent` handle. A missing predecessor or
non-increasing predecessor sequence is surfaced as `consistency: causal_gap`;
the projection never returns that receipt from a `status=complete` query.
Replaying the exact same sequence/payload is idempotent, while a different
payload at the same handle and sequence fails closed with
`receipt_fork_detected`.
