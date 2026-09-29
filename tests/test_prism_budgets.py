from __future__ import annotations

import dataclasses

import pytest

from simplicio_loop.prism_budgets import (
    AdaptiveBudgetGovernor,
    BudgetSample,
    DeviceCapacity,
    DeviceLeaseLedger,
    PrismBudgetError,
    throughput_receipt,
)
from simplicio_loop.prism_contracts import PrismExecution, SlotSupervisor, TaskOwnership
from simplicio_loop.prism_scheduler import (
    AdmissionController,
    BudgetObservation,
    PrismPolicy,
    PrismScheduler,
    PrismSchedulerError,
    ResourceVector,
    ScheduledTask,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def scheduled(task_id: str, slot_id: str, priority: int = 0) -> ScheduledTask:
    ownership = TaskOwnership(
        task_id,
        slot_id,
        1,
        f"agent-{task_id}",
        f"lease-{task_id}",
        1,
        "generation",
        ("implementation",),
        ("accepted", "blocked", "cancelled", "failed", "ready", "running"),
    )
    return ScheduledTask(task_id, slot_id, ownership, priority=priority)


def slots(count: int) -> list[SlotSupervisor]:
    prism = PrismExecution(
        "goal",
        "root",
        SHA_A,
        SHA_B,
        "generation",
        "reducer",
    )
    return [
        SlotSupervisor(prism.prism_id, f"supervisor-{index}") for index in range(count)
    ]


def test_unknown_metrics_are_conservative_and_explain_nulls():
    policy = PrismPolicy(
        global_worker_limit=20,
        recovery_reserve=0,
        validation_reserve=0,
    )
    observation = BudgetSample(
        workers=20,
        cpu_millis=4_000,
        null_reasons={"rss_bytes": "platform_counter_unavailable"},
    ).observation(policy)
    assert observation.limit.workers == 20
    assert observation.limit.rss_bytes == 1
    assert observation.null_reasons["rss_bytes"] == "platform_counter_unavailable"
    controller = AdmissionController(policy, observation)
    slot = slots(1)[0]
    task = dataclasses.replace(
        scheduled("heavy", slot.slot_id),
        resources=ResourceVector(rss_bytes=2),
    )
    decision = controller.decide(task)
    assert decision.reason_code == "RSS_BYTES_PRESSURE"
    assert decision.evidence["limit"]["rss_bytes"] == 1


def test_pressure_is_immediate_and_relief_uses_hysteresis():
    policy = PrismPolicy(global_worker_limit=20)
    governor = AdaptiveBudgetGovernor(policy, relief_samples=2)
    assert governor.observe(BudgetSample(workers=20)).limit.workers == 20
    assert governor.observe(BudgetSample(workers=4)).limit.workers == 4
    assert governor.status()["events"][-1]["reason_code"] == "PRESSURE_APPLIED"
    assert governor.observe(BudgetSample(workers=20)).limit.workers == 4
    assert governor.status()["events"][-1]["reason_code"] == "RELIEF_HYSTERESIS"
    assert governor.observe(BudgetSample(workers=20)).limit.workers == 20
    assert governor.status()["events"][-1]["reason_code"] == "RELIEF_APPLIED"


@pytest.mark.parametrize("physical_cap", [4, 20, 50, 200])
def test_twenty_by_ten_logical_never_exceeds_physical_cap(physical_cap):
    policy = PrismPolicy(
        global_worker_limit=physical_cap,
        recovery_reserve=0,
        validation_reserve=0,
    )
    scheduler = PrismScheduler(
        policy,
        observation=BudgetObservation(ResourceVector(workers=physical_cap)),
    )
    all_slots = slots(20)
    for slot in all_slots:
        scheduler.register_slot(slot)
        for index in range(10):
            scheduler.submit(scheduled(f"{slot.slot_id}-{index}", slot.slot_id))
    batch = scheduler.next_batch()
    assert len(scheduler.tasks) == 200
    assert len(batch) == min(physical_cap, 200)
    assert len(scheduler.controller.active) <= physical_cap


def test_fair_share_prevents_priority_starvation_between_slots():
    scheduler = PrismScheduler(
        PrismPolicy(
            global_worker_limit=1,
            recovery_reserve=0,
            validation_reserve=0,
        )
    )
    high, low = slots(2)
    scheduler.register_slot(high)
    scheduler.register_slot(low)
    for index in range(3):
        scheduler.submit(scheduled(f"high-{index}", high.slot_id, priority=100))
        scheduler.submit(scheduled(f"low-{index}", low.slot_id, priority=0))

    order: list[str] = []
    for _ in range(6):
        current = scheduler.next_batch()[0]
        order.append(current.slot_id)
        scheduler.complete(
            current.task_id,
            "accepted",
            owner_agent=current.ownership.owner_agent,
            fence=current.ownership.fence,
        )
    assert order[:2] == [high.slot_id, low.slot_id]
    assert order.count(high.slot_id) == order.count(low.slot_id) == 3


def test_provider_retry_exclusive_and_reserved_capacity_remain_bounded():
    policy = PrismPolicy(
        global_worker_limit=3,
        recovery_reserve=1,
        validation_reserve=1,
    )
    slot = slots(1)[0]
    provider = dataclasses.replace(
        scheduled("provider", slot.slot_id),
        resources=ResourceVector(provider_requests=1),
    )
    controller = AdmissionController(
        policy,
        BudgetObservation(
            ResourceVector(workers=3, provider_requests=3),
            provider_retry_after_ns=100,
        ),
    )
    assert controller.decide(provider, now_ns=99).reason_code == "PROVIDER_RETRY_AFTER"
    accepted = controller.decide(provider, now_ns=100)
    controller.acquire(provider, accepted)
    assert (
        controller.decide(scheduled("implementation", slot.slot_id)).reason_code
        == "RESERVED_CAPACITY"
    )


def test_device_loss_increments_fence_without_duplicate_work():
    devices = [
        DeviceCapacity("a", 1, capabilities=("code",)),
        DeviceCapacity("b", 1, capabilities=("code",)),
    ]
    ledger = DeviceLeaseLedger(devices)
    original = ledger.assign("task", "code")
    action = ledger.disconnect(original.device_id)[0]
    replacement = ledger.leases["task"]
    assert replacement.device_id != original.device_id
    assert replacement.fence == original.fence + 1
    assert action["work_duplicated"] is False
    with pytest.raises(PrismBudgetError, match="STALE"):
        ledger.assert_current(original)
    ledger.assert_current(replacement)


def test_device_loss_without_target_requires_recovery_not_reexecution():
    ledger = DeviceLeaseLedger([DeviceCapacity("only", 1, capabilities=("code",))])
    ledger.assign("task", "code")
    action = ledger.disconnect("only")[0]
    assert action["reason_code"] == "DEVICE_LOST_RECOVERY_REQUIRED"
    assert action["to_device"] is None
    assert ledger.leases["task"].fence == 1


def test_throughput_receipt_never_invents_cost_or_token_metrics():
    receipt = throughput_receipt(
        verified_tasks=10,
        elapsed_ns=2_000_000_000,
        token_count=None,
        cost_units=None,
    )
    assert receipt["throughput_tasks_per_second_milli"] == 5_000
    assert receipt["tokens_per_verified_task_milli"] is None
    assert receipt["cost_units_per_verified_task_milli"] is None
    assert set(receipt["null_reasons"]) == {
        "tokens_per_verified_task_milli",
        "cost_units_per_verified_task_milli",
    }


def test_budget_contracts_reject_invalid_values():
    for factory in (
        lambda: DeviceCapacity("", 1),
        lambda: DeviceCapacity("a", 0),
        lambda: BudgetSample(workers=-1),
        lambda: BudgetSample(workers=None, null_reasons={"workers": ""}),
        lambda: BudgetSample(null_reasons={"invented": "missing"}),
        lambda: AdaptiveBudgetGovernor(PrismPolicy(), relief_samples=0),
        lambda: DeviceLeaseLedger(
            [DeviceCapacity("a", 1), DeviceCapacity("a", 1)]
        ),
    ):
        with pytest.raises(PrismBudgetError):
            factory()
    with pytest.raises(PrismBudgetError, match="CAPABILITY"):
        DeviceLeaseLedger([DeviceCapacity("a", 1)]).assign("task", "code")
    with pytest.raises(PrismSchedulerError):
        BudgetObservation(
            ResourceVector(),
            null_reasons={"rss_bytes": "missing"},
        )
