# Canonical Mapper projection v1

Fast consumes a validated `simplicio.mapper-fast-handoff/v1` envelope. Mapper
owns the ContextGraph, stable ids and source facts; Fast only verifies those
facts and derives a bounded binary/mmap projection for retrieval and planning.

Each v2 `.sfast` snapshot stores the following `provenance` object in its
validated index metadata:

```json
{
  "schema": "simplicio.fast.snapshot-provenance/v1",
  "mode": "integrated",
  "authority": "simplicio-mapper",
  "mapper_schema": "simplicio.mapper-fast-handoff/v1",
  "mapper_version": "0.26.20",
  "repository_id": "repo",
  "mapper_generation": "g1",
  "artifact_digest": "<sha256>",
  "fast_format_version": 2,
  "capability_coverage": {
    "context_graph": true,
    "files": true,
    "symbols": true,
    "relations": true,
    "source_hashes": true,
    "stable_handles": true
  }
}
```

`artifact_digest` is the SHA-256 of the canonical, sorted artifact manifest
(`name`, `path`, `bytes`, `sha256`). It changes if any Mapper artifact changes,
even when a generation label is accidentally reused. Fast compares the complete
Mapper identity before reusing a projection. A mismatch triggers compilation
from the supplied handoff; missing or invalid canonical input fails closed.

The Python source extractor remains an explicit bootstrap path for development
and tests. It is marked `mode: "bootstrap"`, has no Mapper identity, and cannot
overwrite an integrated projection or be used as an integrated handoff.
