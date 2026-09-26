# MapperStore/v1 canonical contract

`MapperStore` is the single Mapper authority for `memory.sqlite` and
`operations.sqlite`. Mapper owns DDL, migrations, writes, compaction/tombstones
and semantic-index maintenance. Runtime, Loop and MCP consume the
read-only `MapperStoreReader` contract and must not create schemas or write to
these files directly.

The Python facade is exposed as `simplicio_mapper.store.MapperStore` and the
deterministic CLI surface is:

```bash
python3 -m simplicio_mapper.cli mapper-store canonical-status --json
python3 -m simplicio_mapper.cli mapper-store capabilities --json
python3 -m simplicio_mapper.cli mapper-store conformance --json
python3 -m simplicio_mapper.cli mapper-store absorb-legacy --source PATH --json
```

Mapper record identities are stable hashes over record type, repository ID,
generation and record identity. Run, change, repository-generation, precedent,
recipe, decision and execution-outcome records retain source, producer, version,
generation, consent and lineage. Precedents are stored as candidates; an
applicability-evidence field is required and storage never approves one.

`absorb-legacy` is explicit, idempotent and journaled in `operations.sqlite`.
It reads `simplicio-memory.sqlite` without writing to it, preserves legacy
stable IDs and row lineage, writes a read-only policy sidecar after successful
verification, and never deletes the legacy database. Cleanup requires a
separate human-approved policy.

Search reports the actual backend/model/dimension. The current vector path is
deterministic hash embeddings plus brute-force scoring; sqlite-vec is reported
only as an available module and never as an ANN claim.

`simplicio.mapper-store-inventory/v1` is the read-only evidence envelope for the
MapperStore foundation work. The producer is a review-time source-checkout
tool, intentionally not an import-time or installed-package side effect:
[`scripts/mapper_store_inventory.py`](../../../scripts/mapper_store_inventory.py).

The scanner accepts named repository roots and existing database paths. It records
local and remote branch SHAs, package metadata, SQLite-related source matches,
read-only `sqlite_master` observations, current/target ownership, and the DDL
policy result. It never imports application modules, opens a database for writing,
executes migrations, or removes legacy data.

`repos[].revision` is the source checkout SHA used to produce the snapshot. The
evidence JSON is committed in a follow-up evidence-only commit, so it must not
be treated as a self-referential SHA for the commit that stores the JSON.

## Usage

```bash
python3 scripts/mapper_store_inventory.py --deterministic \
  --repo mapper=. --repo loop=../simplicio-loop \
  --repo dev-cli=../simplicio-dev-cli --repo runtime=../simplicio-runtime \
  --output docs/evidence/mapper-store-inventory.json
```

Use `--database <repo-id>=<path>` to inspect a materialized SQLite file in read-only
mode. Use `--check-ddl` as a local gate; existing consumer DDL is reported as
`legacy_ddl_matches`, while newly detected production DDL in Mapper outside the
allowlist fails closed. No GitHub Actions workflow is added by this issue.

The catalog is an inventory, not a migration receipt. A later issue must add
discover → backup → import → validate → shadow-read → cutover → rollback receipts
before any legacy writer or database can be changed.

The final read-only gate consumes external clean-room receipts through
`conformance-evidence.schema.json`. Those receipts are hash-bound to the exact
Mapper/Loop/Dev CLI/Runtime revisions under test and must prove disposable
sandbox isolation, MapperStore writer authority, and zero remaining legacy DDL.
They are evidence inputs, not permission to mutate a consumer checkout.

The Python foundation in `simplicio_mapper.store` owns path resolution,
connection profiles, transactions, bounded busy retry, file locking and the
side-effect-free `simplicio.mapper-store-status/v1` inspection shape. Domain
schemas and migrations remain follow-up work.
