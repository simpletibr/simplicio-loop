# MapperStore queue facade

`simplicio_loop.mapper_queue.MapperQueue` is the explicit queue-facing facade
for `operations.sqlite`. It delegates enqueue, atomic claim, heartbeat, release,
completion receipts, cancellation, reclaim, checkpoint, and status to
`MapperOperationsAdapter`.

The facade has no `sqlite3` import, no local schema, and no fallback to
`LocalTaskQueue`. Construction is side-effect free; `initialize()` is the only
explicit initialization call. A completion without a receipt and an enqueue
without an idempotency key fail before reaching a store.

The queue CLI can now select this facade explicitly without creating the legacy
database:

```text
simplicio-loop queue --route mapper --mapper-db ~/.simplicio-loop/data/operations.sqlite status
simplicio-loop queue --route mapper --mapper-db ~/.simplicio-loop/data/operations.sqlite top
```

`status`, `top`, `inspect`, `cancel`, `doctor`, and `reclaim` delegate to
MapperStore. Legacy-only local state-machine actions (`drain`, `resume`,
`migrate`, and `gc`) fail closed on this route. Default route, import/rollback,
standalone/runtime-backed E2E, and final DDL removal remain tracked by
#1026/#1027.
