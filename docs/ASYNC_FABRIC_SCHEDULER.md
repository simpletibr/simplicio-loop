# Async execution fabric

Issue [#806](https://github.com/wesleysimplicio/simplicio-loop/issues/806)
introduces `AsyncFabricScheduler`, the bounded scheduler for logical Loop slots.
It is independent of an LLM/provider and does not start one implicitly.

## Contract

- `max_running` is the physical global ceiling.
- `capability_limits` bounds each capability independently.
- `queue_capacity` is a hard admission bound. `submit()` suspends its producer
  on an `asyncio.Condition`; no sleep/poll loop is used.
- `capability_queue_limits` and `resource_queue_limits` optionally add narrower
  bounded admission lanes without creating polling workers.
- `asyncio.TaskGroup` owns the dispatcher and every running slot.
- priorities are combined with monotonic-time aging; FIFO sequence breaks ties.
- reads sharing a resource may overlap; `write`, `build`, and `release` are
  exclusive on overlapping resource keys. A release is globally exclusive.
- cancellation reaches the owned coroutine. When the coroutine delegates to
  `PythonProcessAdapter`, its process group is killed and reaped before the
  job becomes `cancelled`.
- every lifecycle transition is fsync'd to a hash-chained JSONL journal.
  `replay_terminal()` validates the whole chain before reconstructing terminal
  states.

The lifecycle is `queued -> ready -> running -> succeeded|failed|cancelled`.
During shutdown, admitted non-terminal jobs pass through `draining`.

## Usage

```python
async with AsyncFabricScheduler(
    max_running=6,
    queue_capacity=64,
    capability_limits={"cpu": 4, "network": 6},
    journal_path=".simplicio-loop/fabric/transitions.jsonl",
) as scheduler:
    result = await scheduler.submit(
        FabricJob(
            "issue-806",
            execute_slot,
            capability="cpu",
            resources=frozenset({"repo:simplicio-loop"}),
            mode="write",
        )
    )
    await result
```

## Verification and rollback

Run:

```console
python -m pytest -q tests/test_fabric_scheduler.py
```

The suite covers the 1/6/64 stress matrix, physical/capability ceilings,
producer backpressure, priority aging, read/write exclusion, failure isolation,
cancel storms, real subprocess reaping, and journal replay/tamper rejection.

Rollback is additive: stop constructing `AsyncFabricScheduler` and continue
using the pre-existing queue/supervisor entry points. Existing journals remain
readable and immutable. The installed Loop baseline is Python 3.11 because the
fabric uses native `asyncio.TaskGroup`. Package metadata now blocks incompatible
Python 3.8-3.10 resolution before execution.
