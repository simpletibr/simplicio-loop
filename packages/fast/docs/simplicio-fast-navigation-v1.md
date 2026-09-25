# `simplicio.fast-navigation/v1`

This bounded Python slice exposes one read-only navigation call over an already
opened `simplicio_fast.snapshot.Snapshot`:

```python
page = navigate(snapshot, handle, relation, direction, budget, cursor=None, generation=None)
```

`handle` must be a `Symbol.symbol_id` already present in the SFAST snapshot.
`generation`, when supplied, must exactly equal `snapshot.generation`, which is
`SFAST001:<sha256 of the opened snapshot bytes>`. A mismatch fails with
`NavigationError.reason_code == "stale_generation"`.

The page schema is `simplicio.fast-navigation/v1`. Each returned item contains
the canonical snapshot ID, relation, direction, location, a minimal snippet,
confidence, and the existing `simplicio.fast.provenance/v1` snapshot provenance.
The page also contains `ids`,
`generation`, `provenance`, and an opaque continuation `cursor`. `max_nodes`
and `max_bytes` are hard page limits; a cursor is bound to the handle, query,
direction, and generation. Invalid cursors fail with `invalid_cursor`.

The current SFAST v2 snapshot can resolve one-hop `definition`, `references`,
`callers`, `callees`, and `tests` when the relation has canonical IDs or a
unique destination name in the same snapshot. `imports`, `dependents`,
`implementations`, `overrides`, `history`, and `next_executable_hop` are
accepted contract relation names but return an explicit incomplete page with
`residual == "relation_not_materialized_by_sfast_v2"`; no ID is synthesized.

This slice deliberately does not claim Rust parity, Loop integration, Mapper
freshness, multi-hop planning, or benchmark/coverage completion for issue #84.
