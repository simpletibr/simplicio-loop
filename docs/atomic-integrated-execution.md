# Atomic integrated execution (issue #258)

## Ownership and call graph

Before:

```text
coordinator retry -> run_task -> MAX_ATTEMPTS -> provider/model -> apply/test
feature max_iter  -> run_feature -> run_task
batch drain       -> TaskBatch -> ThreadPoolExecutor/worktree -> run_task
```

That composition could multiply an outer retry budget by the five attempts in
`run_task`. Integrated dispatch now takes the separate path:

```text
coordinator dispatch(PlanNode, AttemptContext)
  -> run_task(mode="integrated")
  -> compile_task_spec_to_plan
  -> execute_work_item_once
  -> EffectSink exactly zero or one time
  -> AtomicObservation
```

`execute_work_item_once` cannot call `run_task`, `run_feature`, `TaskBatch`, a
provider, a subprocess, a worktree factory, or a pool. It rejects nested
attempts, effects for another node, and more than one effect for its selected
node. It does not run a verification node: the coordinator dispatches that
PlanNode separately after interpreting the observation.

## Capability owners

| Capability | Integrated owner | Standalone owner (temporary) |
|---|---|---|
| dispatch / next node / DAG dependencies | coordinator | `run_feature` / `TaskBatch` |
| retry / replan / completion | coordinator | `run_task` / `run_feature` |
| queue / operational state / terminal status | coordinator | local `.simplicio` stores |
| pools / worktrees | coordinator | `TaskBatch` or caller |
| effect authorization and mutation | Runtime `EffectSink` | pipeline apply transaction |
| cancellation / deadline / lease / fence | coordinator, enforced by Dev CLI | local lifecycle |
| observation / executor retryability | Dev CLI | Dev CLI |

The standalone namespace remains explicit (`mode="standalone"`, the current
default) and does not share an integrated queue or scheduler because the
integrated path creates neither. Its legacy lifecycle is scheduled for removal
when issues #256 and #257 make Runtime-backed integrated mode the negotiated
product entry point.

## Contract and recovery

The coordinator must supply non-empty `attempt_id`, `lease_id`,
`fencing_token`, and canonical `context_handle`. Dev CLI preserves them in
`simplicio.dev-cli.atomic-observation/v1`. Cancellation, elapsed deadline,
lease loss, and stale fence are checked before the sole effect boundary. A
lost sink response returns `effect_unknown` with retryability `unknown`; Dev
CLI never retries it. Re-dispatch after a crash uses the same coordinator
`attempt_id` and Runtime idempotency key, with reconciliation owned by the
Runtime/coordinator.

Rollback is a mode switch back to explicit standalone. Never switch modes
after `effect_unknown`, because that could duplicate an effect.

## Benchmark

Run `python bench/run_atomic_attempt_benchmark.py`. The checked-in measurement
in `bench/results_atomic_attempt.json` records raw attempts, sink calls,
threads, worktrees, subprocesses, model calls, tokens, success count, and
p50/p95 latency. The benchmark is deterministic and provider-free.
