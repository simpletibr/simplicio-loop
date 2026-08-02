# MapperStore operations

Issue #480 adds a conservative operational surface around the canonical
MapperStore. The Python API is in `simplicio_mapper.store` and the installed
CLI is `simplicio-mapper mapper-store`.

## Health and safety

`doctor_store(path)` is read-only and returns one of `missing`, `legacy`,
`migrating`, `ready`, `stale`, `corrupt`, `split_brain` or
`rollback_required`. It checks SQLite integrity, foreign keys, schema checksum,
migration ledger continuity, FTS synchronisation, extension capabilities,
writer/migration locks, size and row budgets. It never creates a path, lock,
WAL or receipt. A report contains counts and reason codes, not row contents.

```bash
simplicio-mapper mapper-store doctor --database ./mapper-store.sqlite --json
simplicio-mapper mapper-store capacity --database ./mapper-store.sqlite --json
```

## Backup, restore and repair

Backups use SQLite's online backup API, are created with mode `0600`, and have a
sidecar manifest containing a SHA-256 and schema checksum. Existing backup or
restore destinations fail closed. Restore targets a new destination by default;
overwriting requires both `--allow-overwrite` and the explicit authorization
token `mapper-store-restore-overwrite/v1`.

Repair is separate from doctor. The default is a side-effect-free plan. Apply
requires a verified backup manifest and only rebuilds derived FTS rows; it does
not invent, rewrite or delete authoritative rows.

```bash
simplicio-mapper mapper-store backup --database ./mapper-store.sqlite \
  --destination ./backups/mapper-store.sqlite --json
simplicio-mapper mapper-store repair --database ./mapper-store.sqlite --json
simplicio-mapper mapper-store repair --database ./mapper-store.sqlite --apply \
  --manifest ./backups/mapper-store.sqlite.manifest.json --json
```

## Metrics and benchmark evidence

`Metrics` reports p50/p95/p99 operation latency, retries, lock wait, errors,
row counts and size/WAL gauges without storing SQL, content, secrets or PII.
Cache observability is explicitly `null` with a reason when no cache adapter is
bound. The benchmark reports environment, repetitions and raw cold/warm read
samples for 1/6/64 workers; it makes no end-to-end performance claim.

```bash
simplicio-mapper mapper-store metrics --database ./mapper-store.sqlite --json
simplicio-mapper mapper-store benchmark --database ./mapper-store.sqlite --json
```

## Runbook

1. `doctor` first; preserve its JSON and SHA-256 export.
2. `corrupt` or failed foreign-key/integrity checks: stop writers, make a
   verified backup if readable, and restore to a new destination.
3. `split_brain`: stop all but the canonical `mapper-store` writer and inspect
   the active pointer before any write.
4. `migrating` or `rollback_required`: do not retry blindly; reconcile the
   migration receipt/pointer and use the existing migration rollback flow.
5. `stale`: verify the recorded PID and lease before removing or recreating any
   lock; never infer that a stale lock means data corruption.
6. Disk or row budget alerts are capacity signals, not permission to delete
   data. Export redacted evidence and plan retention separately.

Installed-package and Windows/Linux/macOS end-to-end smoke remain `UNVERIFIED`
until run on those installed environments.
