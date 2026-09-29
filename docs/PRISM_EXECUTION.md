# Prism execution

Prism introduces a causally validated hierarchy with unbounded logical fan-out:

```text
Goal
└── PrismExecution (no logical slot ceiling)
    ├── SlotSupervisor (minimum 10 logical tasks; no upper ceiling)
    │   ├── TaskOwnership (one owner, lease, attempt, fence)
    │   └── child SlotSupervisor
    └── independent completion oracle
```

Logical capacity is not process count. A slot defaults to ten tasks and can
declare more; adaptive budgets admit only the physically safe overlap observed
on the host. CPU, memory, disk, I/O, provider, model, network, device, context,
evidence and exclusive-resource measurements govern physical execution, never
the logical number of slots.

## Valid construction

```python
from simplicio_loop.prism_contracts import (
    PrismExecution, SlotSupervisor, TaskOwnership, admit_task
)

prism = PrismExecution(
    goal_id="goal-1",
    owner_agent="root",
    policy_hash="a" * 64,
    config_hash="b" * 64,
    source_generation="git-sha",
    reducer_ref="prism-reducer",
)
slot = SlotSupervisor(prism.prism_id, "slot-supervisor")
owner = TaskOwnership(
    "task-1", slot.slot_id, 1, "implementation-agent", "lease-1", 1,
    "git-sha", ("implementation",), ("running", "accepted", "failed")
)
slot, receipt = admit_task(slot, owner)
assert receipt.reason_code == "ADMITTED"
```

Capacity below ten is rejected; capacity above ten is valid and there is no
logical overflow slot. A transition from a different owner or stale fence raises
`PrismContractError`.

## Failure semantics

- Unknown schema or extra JSON schema field: rejected; authority is not widened.
- Missing owner, duplicate owner, orphan parent, cycle or depth >4: rejected.
- Missing metric: conservative bound plus `null_reason`.
- Provider 429: `PROVIDER_RETRY_AFTER`, followed by automatic admission only
  after relief.
- Device loss: fenced reassignment or `DEVICE_LOST_RECOVERY_REQUIRED`; no
  duplicate execution.

The schemas and cross-language fixtures ship under
`simplicio_loop/_contracts/prism/v1`. `hbp-golden.json` freezes exact bytes for
cross-language parity; `conformance-cases.json` freezes adversarial decisions.
