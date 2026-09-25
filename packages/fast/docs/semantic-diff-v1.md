# Semantic diff and what-if overlay v1

`simplicio_fast.semantic_diff` compares two caller-pinned generations by stable
handle and emits deterministic `add`, `remove` and `update` records. It creates
an immutable `simplicio.fast.what-if-overlay/v1`; no source, MapperStore or base
generation is written or mutated.

Each record carries before/after payloads, source/proposed generations, a typed
reason and confidence. Future rename heuristics must use `derived=true` and a
confidence below 1.0; they cannot replace a producer stable identity. Impact
closure is bounded and returns a reason for each included node plus an explicit
completion flag when the budget truncates traversal.

`impact_federated()` accepts an explicit pinned Federation only; it records the
federation generation and provenance paths while traversing downstream
consumers. There is no implicit cross-repository lookup or `latest` resolution.

The implementation is a fact calculator only. It does not apply changes, make
release decisions, authorize effects or claim post-apply reconciliation. Real
federation, Rust parity, adapter fixtures, leases and Dev CLI comparison remain
open gates for issue #342.
