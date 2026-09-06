# ADR-019: MapperStore is the canonical Mapper memory and provenance authority

Status: Accepted

## Context

Mapper data was split between the Mapper-owned `memory.sqlite` and legacy
`simplicio-memory.sqlite` writers. Consumers also need stable provenance and a
truthful description of semantic search capabilities.

## Decision

Mapper owns the schemas, migrations, writes, tombstones/compaction and semantic
indexes for `memory.sqlite` and `operations.sqlite`. Runtime, Fast, Loop and MCP
use a read-only `MapperStoreReader`. Stable record IDs are derived from record
type, repository identity, generation and record identity. Every record keeps
source, producer, version, generation, consent and source lineage. Legacy data
is imported only through the explicit, idempotent `absorb-legacy` path; the
legacy file is not deleted and receives a read-only policy marker only after
verification.

Semantic responses identify the real search backend, embedding model and
dimension. Deterministic hash vectors and brute-force search are not advertised
as learned embeddings or ANN. Precedents remain candidates with applicability
evidence and are never promoted by storage.

## Consequences

Consumers have one versioned read contract and drift fails closed. Absorption is
auditable and repeatable, but cleanup of legacy data remains an explicit policy
decision. Cross-database operations still use receipts rather than pretending
to provide one SQLite transaction.
