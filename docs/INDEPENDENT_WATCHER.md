# Independent watcher plan

`scripts/independent_watcher.py` is a fail-closed behavioral verifier for a
committed implementation snapshot. It receives a versioned plan containing a
challenge, run ID, task-contract hash, commit/diff fingerprints, and one safe
command per acceptance criterion. Each criterion declares the implementer's
`reported_result` and evidence IDs; the watcher emits its own
`recomputed_result`, per-criterion match, result status, and artifact checks.
The watcher never consumes `verification_state` or `watcher_state.json` from the
implementer.

```powershell
python scripts/independent_watcher.py --repo . `
  --plan .simplicio-loop/orchestrator/runs/<run>/watcher-plan.json `
  --out .simplicio-loop/orchestrator/runs/<run>/independent-watcher-receipt.json
```

The plan is rejected when the commit or diff fingerprint is stale, when the
working tree is dirty, when a command is outside the safe executable policy,
or when any criterion exits with an unexpected code. A receipt is
`MEASURED` only when every criterion was recomputed successfully. Dirty trees
must be committed and re-planned; this prevents a watcher from silently
testing `HEAD` while the implementer reports uncommitted behavior.

Each criterion is launched as a child process and the receipt records watcher
and runner PIDs (`process_isolated=true`). Timeout kills the child and returns
`UNVERIFIED`; the receipt also binds task-contract/plan hashes and toolchain
versions when available.

`contracts/task-to-delivery/golden-corpus.json` is the raw-Markdown corpus
manifest used by the parser regression test. It covers frontend, backend,
full-stack, migration, bug, CLI, docs, security, multi-task DAG, and PLANES
inputs. The corpus test is local contract evidence; published clean-install
and browser evidence remain separate release gates.

Run the local mutation gate with `python scripts/golden_mutation.py --json`.
It emits `simplicio.golden-mutation-receipt/v1` and fails if structural-last,
split-type, descending-date, or reverse-plant-order mutants survive. This is
local behavioral evidence only, not a published-package or browser claim.
