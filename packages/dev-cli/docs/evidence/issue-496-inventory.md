# Issue #496 persistence inventory

The inventory is generated without opening any SQLite database:

```text
python scripts/mapper_store_inventory.py --root . --strict --output .simplicio/mapper-store-inventory.json
```

Current measured result on the clean branch:

- schema: `simplicio-dev-cli.mapper-store-inventory/v1`
- occurrences: `1`
- production stores: `0`
- template/fixture detections: `1`
- strict violations: `0`
- inventory digest: `sha256:664b97b7a13c20aa6d6c7b35f5736d7695d529be4a24c02c5652e8c8b274b98f`

| Path | Kind | Current source of truth | Target owner |
|---|---|---|---|
| `simplicio/templates/stacks/py-django/tree/config/settings.py` | fixture | generated project configuration | excluded from Dev CLI persistence |

The memory, lock, and transaction modules now route through the in-process
`MapperStoreAdapter` and therefore no longer contain SQLite/DDL call sites.
Their authoritative JSON records live under `.simplicio/mapper-store/`, while
Dev CLI remains the owner of mutation decisions and receipts.

The strict gate is source-only and fail-closed: a new SQLite connection or DDL
outside the migration allowlist produces a non-zero exit and records the exact
path, line, and source text.
