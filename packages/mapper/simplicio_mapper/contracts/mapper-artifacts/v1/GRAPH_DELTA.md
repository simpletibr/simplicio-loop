# Incremental graph delta contract — `simplicio.graph-delta/v1` (issue #191)

`simplicio-mapper delta <root> --json` emits an initial snapshot on first run
and stores it as `.simplicio-loop/graph-snapshot.json`. Later runs emit the same
versioned envelope with ordered `add`, `update`, `remove`, and `invalidate`
events plus the new snapshot. Ordering is `op,entity_type,id`; consumers can
apply events deterministically and verify `base_revision` before applying.

Entity IDs include kind and repository-relative path. Therefore an unchanged
entity keeps its ID, while a rename or move is intentionally represented as a
remove followed by an add. This is explicit rather than guessing whether a
rename is semantic. `affected_paths` identifies the files that caused or may
need recomputation; `invalidate` is used for dependent analysis that remains
present but is no longer trustworthy.

If the base is missing, corrupt, incompatible, or a consumer detects a
revision mismatch, replace its local state with the `snapshot` from an initial
or `--full-rescan` response. The fallback is bounded and does not pretend
that a partial graph is complete.

The machine-readable schemas are `schemas/graph-snapshot.schema.json` and
`schemas/graph-delta.schema.json`. The API is
`simplicio_mapper.incremental.initial_snapshot`,
`compute_delta`, and `run_incremental_scan`.
