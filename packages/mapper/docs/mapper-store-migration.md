# Governed MapperStore migration

`MigrationCoordinator` is the explicit bridge from legacy Loop, Dev CLI and
Runtime SQLite stores to a MapperStore destination. It does not run on import
of the Python package and it never deletes a legacy source.

For the legacy `simplicio-memory.sqlite` Mapper records (`mapper-run` and
`mapper-change`), use the canonical facade's explicit absorb operation. It
preserves stable IDs and full source rows under lineage metadata, journals one
deterministic migration ID in `operations.sqlite`, and writes a read-only
policy sidecar only after conformance verification:

```bash
python3 -m simplicio_mapper.cli mapper-store absorb-legacy \
  --data-dir PATH/to/canonical-data --source PATH/to/simplicio-memory.sqlite --json
```

Re-running the same absorb against the unchanged source returns an unchanged
receipt and imports no rows. A changed row with the same legacy stable ID is a
conflict, not an overwrite. The source file is never deleted or chmodded;
cleanup requires an explicit policy.

The command family is exposed as `simplicio-mapper mapper-store`:

```text
discover  plan  backup  import  validate  shadow  cutover  rollback  status
```

Use `--source NAME=PATH` for each legacy source and `--database PATH` for the
destination. `plan` and `--dry-run` are read-only: they do not create a
directory, SQLite file/WAL, backup, pointer or receipt. `mapper-store` is kept
separate from the existing `store-migrations` DDL registry CLI.

## State and safety

Receipts are append-only JSONL records with a sequence and SHA-256 hash chain.
The state machine is:

```text
DISCOVERED -> PLANNED -> BACKED_UP -> IMPORTED -> VALIDATED -> SHADOWING
                                                        -> READY -> CUTOVER -> OBSERVED
                                                                  \-> HELD / ROLLBACK
```

Discovery checks SQLite integrity, schema version, paths and a legacy writer
lock. Backup uses SQLite's consistent backup API and records a verified hash.
Import creates compatible tables and deduplicates full rows; schema/data
conflicts fail closed. Validation compares row counts and canonical row hashes.
Cutover requires parity and writes an atomic `<database>.active.json` generation
pointer declaring `mapper-store` as the sole writer authority and the legacy
route read-only.

Rollback is allowed only after a known cutover and restores the verified
pre-migration destination backup. If the latest effect is an intent without a
commit receipt, the command returns `RECONCILIATION_REQUIRED` and does not guess
whether the pointer changed.
