# Knowledge projection v1

`KnowledgeFact` preserves producer, stable handle, version, provenance, trust,
digest, repository/scope and temporal bounds. `KnowledgeProjection` accepts
only explicit adapter-provided facts and tombstones; it never opens a Mapper or
Runtime database directly.

Queries exclude revoked, expired, conflicted and tombstoned facts, support
bounded as-of filtering, return handles instead of unbounded content, and keep
producer, repository and scope alongside version, provenance, digest, and keep
relevance, trust, freshness and applicability separate in `explain`. The
current ranking is explicitly labelled `lexical-fallback`; vector ranking is
optional and unavailable vector infrastructure does not silently change the
contract.

Authorized producers can submit an explicit
`simplicio.fast.knowledge-handoff/v1` envelope through `apply_handoff`. The
derived projection accepts only `mapper` or `runtime` producers, validates
repository/scope/generation, reconstructs typed facts, and never opens producer
storage. Cross-runtime conformance, real corpus quality receipts and external
consumer adapters remain open gates for #344.
