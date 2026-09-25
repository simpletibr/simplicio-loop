# Simplicio Fast operational manual

## Install and verify

Install the package in a Python 3.11+ environment, then verify the integrated
adapters and snapshot with:

```powershell
simplicio-fast --help
simplicio-fast build . -o .simplicio/fast/project.sfast
simplicio-fast doctor -s .simplicio/fast/project.sfast
```

`doctor` reports `integrated_ready: true` only when compatible Mapper and Dev
CLI executables are installed. The preferred action binary is
`simplicio-dev-cli`; `simplicio-cli` is accepted as a legacy compatibility
alias. If either adapter is missing or below its minimum contract, the command
fails closed; `ingest` and `apply` emit an explicit bootstrap-fallback receipt
instead of silently returning empty context or claiming an integrated write.

## Safe processing loop

1. Run `ingest` or `build` to create the derived snapshot.
2. Use `context`, `understand` or `plan` to obtain bounded, hash-verified data.
3. Review the generated `simplicio.fast.changeset/v2`.
4. Run `apply` without `--write` first; inspect its receipt.
5. Use `apply --write` only after the source hashes and acceptance checks pass.
6. Refresh the snapshot and rerun the validation commands from the receipt.

When Dev CLI is installed but rejects a valid `simplicio.fast.changeset/v2`
contract (including a native hash mismatch on Windows), `apply` records the
native refusal, verifies a no-write/rollback proof, and uses Fast's explicit
internal atomic fallback. The resulting `simplicio.fast.apply-receipt/v2`
contains before/after SHA-256 values for every target and marks the executor as
`fallback`; it must not be treated as an integrated Dev CLI write. Stale Fast
source hashes still fail closed before either executor can run.

Fast is not the policy or effect authority: Runtime authorizes effects and
emits execution receipts, while Loop owns retries, slots and convergence.

## Rollout and rollback

Record explicit rollout state with:

```powershell
simplicio-fast rollout shadow --generation SFAST001:1
simplicio-fast rollout canary --generation SFAST001:2
simplicio-fast rollout integrated --generation SFAST001:3
simplicio-fast rollout rollback --reason "validation failed"
```

Receipts use `simplicio.fast.rollout-receipt/v1` and are atomically published.
Rollback is a distinct `rolled-back` status and must not be reported as an
integrated success.

## Troubleshooting

- Corrupt or stale snapshots fail closed; rebuild them from source.
- A stale changeset must be regenerated because every replacement is guarded by
  the expected source SHA-256.
- If `doctor` is not integrated-ready, inspect the reported package version and
  executable path, then install the minimum Mapper `0.24.2` and Dev CLI `0.16.3`.
- The benchmark reports observed wall/CPU/RSS values only. A native metric that
  is unavailable is emitted as `null` with a reason.
