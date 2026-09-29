# Durable local task queue

`LocalTaskQueue` is a facade over the MapperStore operations database (`MapperRemoteQueue`); it does not create a parallel broker. Task, lease and fencing authority lives in MapperStore, and outcome projections (dependencies, outcomes, intent/receipts, transitions) are append-only Mapper operations events.

Supported outcomes are `never_started`, `running`, `unknown_outcome`, `verified_success`, `retryable_failure`, `blocked` and `dead_letter`. Unknown effects require reconciliation, and retries require idempotency provenance. STOP blocks claims and requests bounded cooperative cancellation. Terminal GC requires released generation/worktree resources.

Operator commands emit JSON on success and operational failure: `simplicio-loop queue --repo <path> status|top|inspect|cancel|drain|resume|doctor|reclaim|gc|migrate`.
Schema upgrades are explicit: preview the backup with `migrate`, then run `migrate --apply`. Version 1 provenance records are converted to version 2 digested envelopes in one transaction; failure restores the SQLite backup.

Run the benchmark with `python -m bench.benchmark_local_task_queue_889`; it measures 1, 10, 100 and 1000 queued tasks.
The benchmark exits non-zero when per-task enqueue or claim latency exceeds its configurable thresholds.
The queue CLI accepts only a resolved Git worktree root for `--repo`; library callers may still use isolated temporary roots.
