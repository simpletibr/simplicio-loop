# Issue #496 persistence inventory

The inventory is generated without opening any SQLite database:

```text
python scripts/mapper_store_inventory.py --root . --strict --output .simplicio/mapper-store-inventory.json
```

Current measured result on the clean branch:

- schema: `simplicio-dev-cli.mapper-store-inventory/v1`
- occurrences: `11`
- production stores: `1`
- template/fixture detections: `1`
- strict violations: `0`
- inventory digest: `sha256:bf271bc75726abb0a956a3bae65488d893eb5c7a7721ad637644831fbf15e917`

| Path | Kind | Current source of truth | Target owner |
|---|---|---|---|
| `simplicio/memory_store.py` | derived index | memory Markdown/files | MapperStore memory/handoff |
| `simplicio/templates/stacks/py-django/tree/config/settings.py` | fixture | generated project configuration | excluded from Dev CLI persistence |

The former lock and transaction modules now route through the in-process
`MapperStoreAdapter` and therefore no longer contain SQLite/DDL call sites.
Their authoritative JSON records live under `.simplicio/mapper-store/`, while
Dev CLI remains the owner of mutation decisions and receipts.

The strict gate is source-only and fail-closed: a new SQLite connection or DDL
outside the migration allowlist produces a non-zero exit and records the exact
path, line, and source text.
