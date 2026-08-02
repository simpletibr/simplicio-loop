# MapperStore final conformance gate

`scripts/mapper_store_conformance.py` is the final read-only gate for the
MapperStore rollout. It freezes each repository's default remote SHA and
version metadata, reuses the MapperStore inventory/DDL scanner, records the
ownership and database evidence, and reports every release scenario as
`pass`, `fail` or `unverified`.

It does not import Loop, Dev CLI or Runtime packages, change a checkout, create
or migrate a database, perform cutover, delete legacy files, or declare an
external rollout complete. This is deliberate: external package smoke and
cross-platform fault injection must be run in clean sandboxes and their raw
evidence supplied to the gate.

```bash
python3 scripts/mapper_store_conformance.py \
  --repo mapper=. \
  --repo loop=../simplicio-loop \
  --repo dev-cli=../simplicio-dev-cli \
  --repo runtime=../simplicio-runtime \
  --repo fast=../simplicio-fast \
  --database loop=../simplicio-loop/path/to/legacy.sqlite \
  --deterministic \
  --output docs/evidence/mapper-store-conformance.json
```

The default exit code is non-zero only for a concrete failure, such as
external legacy DDL evidence or an unreadable supplied database. Missing
installed-package, OS, rollout and fault-injection evidence remains explicit
`unverified` data in the JSON instead of being turned into a false pass.

The report includes the mandatory release order: publish Mapper contracts,
validate installed packages/bindings, shadow consumers, collect zero unexplained
mismatch, cut over explicitly in sandboxes, fault-inject and rollback, promote
MapperStore defaults, retain legacy read-only during the window, then remove
legacy writers only after verified backup and migration evidence.

## Current local evidence

The local checkouts are intentionally not treated as release sources when they
are dirty or on feature branches. The gate records their exact state and marks
clean-default, installed-package and cross-platform checks `unverified`; it
reports remaining consumer DDL as a concrete failure. A green final rollout
requires clean default SHAs and fresh external evidence, not this source-tree
observation alone.
