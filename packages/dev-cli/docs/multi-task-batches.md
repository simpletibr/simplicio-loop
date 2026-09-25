# Multi-task batches

`simplicio.orchestrator.multi_task.TaskBatch` freezes a deterministic task DAG and persists each
item's `pending`, `running`, `passed`, or `blocked` state. The batch identity (`source_hash`,
`plan_hash`, `base_sha`) is frozen; stale transitions are rejected. State writes use a temporary
file plus `os.replace`, so resume never observes a partially written JSON document.

Independent items are returned by `ready()`. A dependent item is not runnable until every predecessor
is `passed`; `status()` returns counts, task receipts, identity, and the next ready items for loop/runtime
consumers.
