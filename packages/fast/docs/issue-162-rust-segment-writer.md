# Rust segmented writer slice — issue #162

This slice moves segmented publication from Python-only ownership into the Rust
core while preserving the existing `simplicio.fast.segments/v1` boundary.

## Command

```bash
simplicio-fast-rs --publish-segments project.sfast .simplicio/fast/segments
```

The command first opens and fully validates the SFAST001/v2 snapshot. It then:

1. derives one SHA-256 content-addressed file per validated section;
2. reuses an existing segment only after checking its size and digest;
3. writes new segment files with `create_new`, flushes them with `sync_all`,
   and renames them into their final content-addressed paths;
4. preserves the current complete manifest as `manifest.previous.json`;
5. publishes `manifest.json` through a temporary file and atomic rename;
6. returns a receipt containing generation, source digest, written and reused
   segment counts.

Unsafe section names and content-address collisions fail closed. The public
manifest remains readable by the Python `SegmentStore` and Rust
`SegmentReader`; receipt-only counters are additive JSON fields.

## Validation in this slice

Rust unit tests cover:

- no-change refresh reuses all segments;
- a one-section change writes one segment and reuses the rest;
- the previous complete manifest is preserved;
- unsafe segment names never publish a manifest.

Run:

```bash
cd rust
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
```

## Explicit remaining scope

This PR does not claim the entire issue complete. Native source parsing,
monolithic SFAST construction, change-journal-driven dependency invalidation,
checkpoint/resume across the full build pipeline, overlays, >512 MiB proof,
cross-platform CI, and Python/Rust golden execution remain follow-up gates.
