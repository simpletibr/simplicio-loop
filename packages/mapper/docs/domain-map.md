# Domain map — simplicio-mapper

Mapper is the canonical observer: it reads a repository and emits bounded,
versioned context for downstream consumers. It does not own execution,
convergence, or Fast storage internals.

## Canonical vocabulary

| Term | Meaning | Source of truth |
|---|---|---|
| ContextGraph | Versioned public graph of repository facts and relations across micro, meso, and macro scales. | `contracts/context-snapshot/v1/` and `contracts/context-graph/v1/` |
| ContextSnapshot | Content-addressed envelope containing a graph, repository identity, revision, freshness and fidelity metadata. | `simplicio_mapper/context_snapshot.py` |
| generation | Stable public identifier for the mapped graph revision; snapshot generation uses `snapshot_id`. | `simplicio_mapper/context_graph_contract.py` |
| stable ID | Logical node/edge ID that remains comparable across language channels and does not expose storage offsets. | `contracts/context-graph/v1/README.md` |
| digest | SHA-256 of canonical UTF-8 JSON with sorted keys and no insignificant whitespace. | `simplicio_mapper/context_graph_contract.py` |
| canonical_api | In-process seam for a safe, lazy effective map view. | `simplicio_mapper/mapper/canonical_api.py` |
| Fast handoff | Versioned Mapper-to-Fast projection carrying identity, generation, capabilities and artifact digests. | `simplicio_mapper/fast_handoff.py` |
| provenance | Source handle and channel/version information that lets a result be traced or diagnosed. | `simplicio_mapper/context_snapshot.py` |

## Public rules

- Consumers validate schema and version before use and fail closed on unknown majors.
- Public behavior is defined by contract fields, ordering, IDs, digests, and error reasons—not parser classes, cache paths, mmap offsets, or serialized implementation objects.
- Missing optional Rust acceleration must use the Python behavior without changing the contract.
- Partial context is explicit through omissions/fidelity metadata; Mapper never fabricates complete evidence.

## Out of scope / not yet specified

- Cross-repository graph composition and sequence conformance remain blocked by
  the Runtime issue that coordinates Mapper → Fast → Dev CLI → Runtime → Loop.
- Storage placement, mmap layout, and parser-specific AST details are private
  implementation concerns and are intentionally not part of this vocabulary.
