# Simplicio Operational Manual

This repository is the Dev CLI materialization and verification boundary.
Mapper observes context, Runtime authorizes governed effects when configured,
and the Dev CLI stages, commits, verifies, rolls back, and records receipts.

## Local verification

Run the reproducible local gate from a clean checkout:

```powershell
python scripts/quality_gate.py --help
python scripts/issue_422_e2e.py --root . --repeats 10
```

Standalone execution does not require Runtime. Runtime-backed evidence is
separate and must identify its configured effect endpoint and repository root;
missing capabilities remain explicitly `UNVERIFIED`.

## Safe mutation flow

1. Validate the changeset, repository identity, generation, lease, fence, and
   write-set before the first effect.
2. Stage every file and persist the transaction intent before publication.
3. Commit atomically where the platform permits and verify resulting hashes.
4. On failure, restore the before-state and prove the restored hashes, or emit
   an explicit recovery-required/rollback-failed state.
5. Seal the receipt only after verification; identical replay is idempotent and
   conflicting replay is rejected.

## Evidence and diagnostics

Receipts and raw reports must bind to the tested commit SHA. Unavailable
Runtime, Fast, or platform lanes are recorded with a reason and are never
converted into a passing result.

See [the quality gate](ci-quality-gate.md), [the changeset contract](changeset-v2.md),
[the runtime effect sink](runtime-effect-sink.md), and [troubleshooting](troubleshooting.md).
