# Semantic federation v1

`simplicio_fast.federation` compiles a bounded, read-only view from explicitly
pinned members. Every member records repository, commit, generation, producer
schema, scope and digest. Every edge uses opaque stable handles; derived edges
must include evidence and confidence. The compiler rejects case-insensitive
repository collisions and tombstoned members instead of producing a misleading
complete generation.

The serialized contracts are `simplicio.fast.federation-manifest/v1`,
`simplicio.fast.federated-edge/v1` and `simplicio.fast.federated-generation/v1`.
Members and edges are sorted before hashing, so identical pinned input produces
identical bytes and generation IDs. `consumers`, `dependencies` and `traverse`
are bounded lookups; traversal returns provenance paths and an explicit
`complete` flag. No query discovers or resolves an implicit `latest` member.

`Federation.apply_delta()` returns a new generation, preserving unchanged
members, removing tombstoned-member edges and reporting changed repositories,
closure handles, tombstones and member reuse. The original federation remains
available after a failed or partial proposal.

This is a derived index, not a graph database, dependency resolver, source of
truth, scheduler or release authority. Cross-repository fixtures, Rust parity,
real Mapper contracts, worktree isolation and resource receipts remain required
before issue #341 can close.
