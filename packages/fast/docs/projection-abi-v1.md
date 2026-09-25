# Projection ABI v1

Fast exposes one dependency-free, read-only envelope for derived projections:
`simplicio.fast.projection/v1`. The machine-readable registry is
`contracts/projection/v1/manifest.json` and the Python registry is
`simplicio_fast.projection.contract_manifest()`.

The common envelope carries provenance, scope, generation, opaque stable handles,
content digests, capabilities, budgets, completeness/fidelity, truncation and
generation lineage. Domain-specific facts remain inside the typed `payload`; the
common envelope never exposes mmap offsets, pointers or ownership details.

The three versioned contracts are:

- `simplicio.fast.projection-envelope/v1`
- `simplicio.fast.projection-type-manifest/v1`
- `simplicio.fast.projection-capabilities/v1`

Readers reject unknown schema majors, invalid digests, malformed scopes and
private layout fields. Inputs are bounded by encoded size, nesting depth, item
count and text length. JSON is an export/debug representation; `encode()` is
canonical and deterministic, while producers remain authoritative for source
data and the store is only a derived read model.

The current Rust reader validates the shared schema, type, required provenance
and SHA-256 payload digest. Its canonical byte-for-byte fixture currently covers
the ASCII contract surface; Unicode and cross-platform conformance remain
explicit follow-up gates.
