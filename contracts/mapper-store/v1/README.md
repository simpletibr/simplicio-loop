# MapperStore/v1 inventory contract

`simplicio.mapper-store-inventory/v1` is the read-only evidence envelope for the
MapperStore foundation work. The producer is
[`scripts/mapper_store_inventory.py`](../../../scripts/mapper_store_inventory.py).

The scanner accepts named repository roots and existing database paths. It records
local and remote branch SHAs, package metadata, SQLite-related source matches,
read-only `sqlite_master` observations, current/target ownership, and the DDL
policy result. It never imports application modules, opens a database for writing,
executes migrations, or removes legacy data.

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
