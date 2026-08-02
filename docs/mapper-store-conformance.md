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

## External cross-repo receipts

The Mapper gate does not import or execute consumer code. A clean-room harness
may produce a hash-bound receipt using
`simplicio.mapper-store-conformance-evidence/v1`, then pass it back with either
of these forms:

```bash
python3 scripts/mapper_store_conformance.py \
  --repo mapper=. --repo loop=../simplicio-loop \
  --repo dev-cli=../simplicio-dev-cli --repo runtime=../simplicio-runtime \
  --evidence-file /tmp/mapper-store-evidence.json \
  --deterministic
```

`--evidence-file` accepts one receipt or a JSON object mapping gate IDs to
receipts. `--evidence runtime_single_authority=/tmp/runtime.json` remains
available for individual files. A receipt is accepted only when its canonical
SHA-256 matches `evidence_hash`, the sandbox is disposable and clean, all four
repository revisions match the frozen gate refs, `writer_authority` is exactly
`mapper-store`, and `legacy_ddl_matches` is zero. Invalid, stale, partial, or
failed receipts remain `unverified`/`fail`; they can never turn a gate green.

Scenario keys use `scenario:<name>`, for example
`scenario:Windows` or `scenario:crash during migration`. The external harness
may mutate only its disposable sandbox; the Mapper gate itself remains
read-only. This is also the handoff point for the Runtime `--evidence-file`
workflow: Runtime/Dev CLI can publish a receipt, while Mapper decides whether
it is current and sufficient for conformance.

## Current local evidence

The local checkouts are intentionally not treated as release sources when they
are dirty or on feature branches. The gate records their exact state and marks
clean-default, installed-package and cross-platform checks `unverified`; it
reports remaining consumer DDL as a concrete failure. A green final rollout
requires clean default SHAs and fresh external evidence, not this source-tree
observation alone.
