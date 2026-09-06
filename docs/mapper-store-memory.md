# MapperStore memory and handoff

`MapperStore` is the single canonical facade for Mapper memory, semantic
indexes, operations provenance and record identity. It creates exactly
`memory.sqlite` and `operations.sqlite`; the read-only `MapperStoreReader` is
the consumer boundary for Runtime, Fast, Loop and MCP. Domain classes remain
the implementation owners behind that facade, not parallel consumer stores.

`simplicio_mapper.store.memory` is the canonical cross-agent memory adapter for
MapperStore/v1. The SQLite `memory_entries` table owns identity, provenance,
consent, retention and outcomes. Search is delegated to the existing
`SemanticStore` tables and indexes through the same stable ID; memory does not
maintain a second FTS/vector index or copy vector columns.

## Compatibility surface

`MarkdownGitAdapter` reads the Dev CLI layout:

```text
<root>/README.md
<root>/notes/<topic>.md
```

Each note may contain append-only sections in the form
`## <ISO timestamp> — <actor>`, an optional `tags:` line and Markdown content.
`import_markdown()` is idempotent: the stable ID is derived from the relative
note path, entry metadata and content hash, so inserting a new section does not
renumber later entries. Existing ordinal-based IDs are retained when their
source path and content still match during an upgrade. The original path and
file SHA-256 are stored as provenance. Import never rewrites the source
Markdown. `export_markdown()` is explicit and produces readable files from
canonical rows; `commit=True` makes the optional git audit commit.

## API and failure policy

- `store()` always redacts secret-like values and rejects empty, oversized or
  invalid JSON payloads before writing.
- `recall()` accepts `fts5`, `vector` and `hybrid`; responses identify the
  actual brute-force search backend, active model, dimension and embedding
  provenance. `sqlite-vec` availability is not an ANN claim and is reported
  separately.
- `record_run()`, `record_change()`, `record_generation()`, `record_precedent()`,
  `record_recipe()`, `record_decision()` and `record_execution_outcome()` use
  stable IDs and retain source/producer/version/generation/consent metadata.
  Precedents require applicability evidence and remain candidates.
- `handoff()` emits a deterministic, hash-addressed
  `simplicio.mapper-store.handoff/v1` packet. Legacy
  `simplicio.memory-handoff/v1` packets are accepted by `validate_handoff()`.
- `export_snapshot()` and `restore_snapshot()` use a SHA-256 protected
  `memory-snapshot/v1` envelope and preserve entry hashes/outcomes.
- `validate()` reports broken memory-to-semantic references, malformed
  Markdown and source drift; it never fabricates health.
- Expired entries are excluded from recall and `purge_expired()` tombstones
  them while retaining audit rows.

Convenience functions (`init_memory`, `store_memory`, `recall_memory`,
`validate_memory`, `build_handoff`) preserve the Dev CLI's direct namespace
shape while making MapperStore the SQLite/index owner.
