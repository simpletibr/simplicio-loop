# Fast V3 contract matrix

This matrix is the implementation checklist for ADR-0001
and issue #38.

## Public contracts

| Contract | Producer | Consumer | Required fields | Forbidden |
| --- | --- | --- | --- | --- |
| simplicio.context-snapshot/v1 | Mapper | Fast adapter, Loop/Runtime handles | repository, commit, snapshot, IDs, fidelity | mmap offsets |
| simplicio.fast.snapshot/v3 | Fast | Fast readers/adapters | schema, generation, sections, checksums, source hashes, Mapper projection provenance | mutable in-place records or an independent ContextGraph |
| simplicio.fast.context/v1 | Fast | Agent/Loop/Runtime/Prompt | generation, spans, IDs, hashes, budgets, provenance | unbounded repository dump |
| simplicio.fast.understanding/v1 | Fast | coordinator/Dev CLI handoff | task hash, targets, impact, risks, tests, generation | public competing ContextGraph |
| simplicio.fast.changeset/v2 | Fast/Dev CLI boundary | Dev CLI/Runtime | generation, paths, expected hashes, idempotency | stale or hashless writes |
| simplicio.fast.delivery-engine/v1 | Fast | Loop/Runtime/Code/Sprint | engine, profile, cache metrics, stages, receipts | secret/prompt payloads |
| simplicio.fast.receipt/v1 | Fast/Dev CLI/Runtime | Loop/quality/replay | request hash, generation, status, reason, evidence | unverifiable claims |

## Ownership rules

1. Mapper remains the only public ContextGraph producer.
2. Fast is the only owner of its compiled snapshot and generation lifecycle.
3. Dev CLI is the only owner of mechanical source editing.
4. Loop is the only owner of attempt progression, slot assignment and convergence.
5. Runtime is the only effect/policy authority in Full mode.
6. Agent/LLM/coordinators own decisions and provider calls.
7. Consumers use handles and contracts, never binary offsets or private records.
8. Python and Rust must produce semantically equivalent contracts.
9. JSON is boundary output; internal persistence follows binary/HBP/HBI rules.
10. Missing capability must be explicit; empty context is not success.

Every v2 `.sfast` projection also carries
`simplicio.fast.snapshot-provenance/v1` in its validated index metadata. Integrated
projections must pin the Mapper handoff schema, Mapper version, repository id,
Mapper generation, aggregate artifact digest, Fast format version and capability
coverage. A source-parser bootstrap snapshot is development-only and is never
accepted as an integrated Mapper projection. A generation, version or artifact
digest mismatch causes Fast to rebuild from the new handoff or fail closed.

## Engine selector contract

The selector must return:

- requested_engine: auto|rust|python|off;
- selected_engine;
- engine_version;
- schema_version;
- capabilities;
- conformance_digest;
- reason_code;
- profile: full|loop-standalone;
- python_loaded: boolean;
- rust_loaded: boolean.

Invalid combinations are failures:

- requested_engine=rust and Rust unavailable;
- requested_engine=python and Rust loaded;
- selected_engine=rust with failed conformance;
- profile=full with an effect bypassing Runtime;
- stale generation or missing source hash on a write.

## State transitions

unknown → probing → selected → healthy → degraded → rolled_back

- probing: bounded read-only capability check.
- selected: one engine is chosen; the other is not loaded.
- healthy: conformance and health gates pass.
- degraded: a typed capability/health issue is emitted.
- rolled_back: previous engine/profile is restored without changing source truth.

## Evidence required for promotion

- selected engine and process/module load proof;
- schema and conformance digests;
- base/overlay generation;
- source hashes for context and changes;
- cache hit/miss/invalidation metrics;
- test/gate results;
- rollback proof;
- benchmark receipt with raw data or explicit null reasons.
