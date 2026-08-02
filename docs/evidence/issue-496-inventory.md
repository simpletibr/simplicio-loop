# Issue #496 persistence inventory

The inventory is generated without opening any SQLite database:

```text
python scripts/mapper_store_inventory.py --root . --strict --output .simplicio/mapper-store-inventory.json
```

Current measured result on the clean branch:

- schema: `simplicio-dev-cli.mapper-store-inventory/v1`
- occurrences: `31`
- production stores: `5`
- template/fixture detections: `1`
- strict violations: `0`
- inventory digest: `sha256:a59d252e7b8d01338a710bba864b40b014b52cf6da3b478aa6596bf13399e8ca`

| Path | Kind | Current source of truth | Target owner |
|---|---|---|---|
| `simplicio/memory_store.py` | derived index | memory Markdown/files | MapperStore memory/handoff |
| `simplicio/effect_transaction.py` | transaction ledger | transaction receipt state | MapperStore adapter; Dev CLI keeps receipt ownership |
| `simplicio/mutation_worker.py` | mutation ledger | mutation lifecycle receipt | MapperStore transaction/ledger adapter |
| `simplicio/prism_transaction.py` | transaction ledger | PRISM transaction receipt | MapperStore transaction adapter |
| `simplicio/write_set_lock.py` | lock ledger | write-set fencing/lock state | MapperStore lock adapter |
| `simplicio/templates/stacks/py-django/tree/config/settings.py` | fixture | generated project configuration | excluded from Dev CLI persistence |

The strict gate is source-only and fail-closed: a new SQLite connection or DDL
outside the migration allowlist produces a non-zero exit and records the exact
path, line, and source text.
