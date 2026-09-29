from __future__ import annotations

import asyncio
import dataclasses

import pytest

from simplicio_loop.hbp_ledger import canonical_sha256
from simplicio_loop.prism_contracts import (
    PrismExecution,
    SlotSupervisor,
    TaskOwnership,
)
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


def hierarchy(slot_count=1, capacity=10):
    root = PrismExecution(
        goal_id="g",
        owner_agent="root",
        policy_hash=SHA_A,
        config_hash=SHA_B,
        source_generation="gen",
        reducer_ref="reducer",
    )
    slots = [
        SlotSupervisor(
            root.prism_id,
            f"supervisor-{index}",
            capacity=capacity,
        )
        for index in range(slot_count)
    ]
    return root, slots


def task(
    task_id,
    slot_id,
    *,
    depends=(),
    conflicts=(),
    exclusive=(),
    kind="implementation",
    priority=0,
    resources=None,
):
    owner = TaskOwnership(
        task_id,
        slot_id,
        1,
        f"agent-{task_id}",
        f"lease-{task_id}",
        1,
        "gen",
        ("implementation",),
        ("accepted", "blocked", "cancelled", "failed", "ready", "running"),
    )
    return ScheduledTask(
        task_id,
        slot_id,
        owner,
        depends_on=depends,
        hard_conflicts=conflicts,
        exclusive_resources=exclusive,
        kind=kind,
        priority=priority,
        resources=resources or ResourceVector(),
    )


def test_slot_admission_never_exceeds_ten_and_queues_eleventh():
    _, slots = hierarchy()
    scheduler = PrismScheduler()
    scheduler.register_slot(slots[0])
    receipts = [
        scheduler.submit(task(f"t-{index}", slots[0].slot_id)) for index in range(11)
    ]
    assert sum(item.admitted for item in receipts) == 10
    assert receipts[-1].reason_code == "SLOT_LOGICAL_CAPACITY"
    assert scheduler.queued_reasons["t-10"] == "SLOT_LOGICAL_CAPACITY"


def test_ready_set_admits_in_submission_order_not_lexicographic_task_id():
    """Regression (issue #1298 wave10 smoke): a wave of same-lane (single-file,
    overlapping edit-plan path) tasks is dispatched one at a time via repeated
    ``next_batch()`` calls, since only one worker may touch that shared file at
    once. Ten or more such tasks are named ``<run>-task-<N>`` -- ``ready_set()``
    used ``task.task_id`` as its final sort tiebreaker, which orders those ids
    lexicographically ("...-task-10" sorts before "...-task-2"), admitting task
    10 second instead of tenth and applying its cumulative find/replace edit
    plan against the wrong intermediate file state (``plan_find_not_found``).
    Submission order must be preserved regardless of how many digits the
    trailing index has.
    """
    _, slots = hierarchy()
    scheduler = PrismScheduler(
        PrismPolicy(global_worker_limit=1, recovery_reserve=0, validation_reserve=0)
    )
    scheduler.register_slot(slots[0])
    task_ids = [f"run-abc-task-{index}" for index in range(1, 11)]
    for task_id in task_ids:
        scheduler.submit(task(task_id, slots[0].slot_id))

    admitted_order: list[str] = []
    for _ in range(len(task_ids)):
        batch = scheduler.next_batch()
        assert len(batch) == 1
        admitted = batch[0]
        admitted_order.append(admitted.task_id)
        scheduler.complete(
            admitted.task_id, "accepted",
            owner_agent=admitted.ownership.owner_agent, fence=1,
        )
    assert admitted_order == task_ids


def test_dependencies_conflicts_and_exclusive_resources_serialize_only_affected_group():
    _, slots = hierarchy()
    scheduler = PrismScheduler(
        PrismPolicy(global_worker_limit=6, recovery_reserve=1, validation_reserve=1)
    )
    scheduler.register_slot(slots[0])
    scheduler.submit(task("a", slots[0].slot_id, conflicts=("b",)))
    scheduler.submit(task("b", slots[0].slot_id, conflicts=("a",)))
    scheduler.submit(task("c", slots[0].slot_id, exclusive=("build",)))
    scheduler.submit(task("d", slots[0].slot_id, exclusive=("build",)))
    scheduler.submit(task("e", slots[0].slot_id, depends=("a",)))
    first = scheduler.next_batch()
    assert {item.task_id for item in first} == {"a", "c"}
    for item in first:
        scheduler.complete(
            item.task_id,
            "accepted",
            owner_agent=item.ownership.owner_agent,
            fence=1,
        )
    second = scheduler.next_batch()
    assert {item.task_id for item in second} == {"b", "d", "e"}


def test_global_budget_and_conservative_missing_metric_never_oversubscribe():
    _, slots = hierarchy()
    observation = BudgetObservation(
        ResourceVector(workers=4, cpu_millis=2000),
        unavailable=("rss_bytes",),
    )
    scheduler = PrismScheduler(
        PrismPolicy(global_worker_limit=4, recovery_reserve=0, validation_reserve=0),
        observation=observation,
    )
    scheduler.register_slot(slots[0])
    for index in range(4):
        scheduler.submit(task(f"t-{index}", slots[0].slot_id))
    batch = scheduler.next_batch()
    assert len(batch) == 1
    assert scheduler.snapshot()["metrics"]["max_temporal_overlap"] == 1
    assert any(
        row["reason_code"] == "METRIC_UNAVAILABLE_CONSERVATIVE"
        for row in scheduler.snapshot()["decisions"]
    )


def test_provider_retry_after_pressure_and_reserved_capacity_have_reasons():
    policy = PrismPolicy(
        global_worker_limit=3, recovery_reserve=1, validation_reserve=1
    )
    _, slots = hierarchy()
    controller = AdmissionController(
        policy,
        BudgetObservation(
            ResourceVector(workers=3, provider_requests=10),
            provider_retry_after_ns=100,
        ),
    )
    provider = task(
        "provider",
        slots[0].slot_id,
        resources=ResourceVector(provider_requests=1),
    )
    assert controller.decide(provider, now_ns=50).reason_code == "PROVIDER_RETRY_AFTER"
    admitted = controller.decide(provider, now_ns=101)
    assert admitted.admitted
    controller.acquire(provider, admitted)
    implementation = task("impl", slots[0].slot_id)
    assert (
        controller.decide(implementation, now_ns=101).reason_code == "RESERVED_CAPACITY"
    )
    controller.release("provider")


def test_async_execution_has_real_overlap_and_no_lost_tasks():
    async def scenario():
        _, slots = hierarchy()
        scheduler = PrismScheduler(
            PrismPolicy(global_worker_limit=6, recovery_reserve=1, validation_reserve=1)
        )
        scheduler.register_slot(slots[0])
        for index in range(10):
            scheduler.submit(task(f"t-{index}", slots[0].slot_id))
        active = 0
        max_active = 0

        async def worker(_item):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.002)
            active -= 1
            return "accepted"

        receipt = await scheduler.execute(worker)
        assert set(receipt["states"].values()) == {"accepted"}
        assert max_active == 4
        assert receipt["metrics"]["max_temporal_overlap"] == 4
        assert len(receipt["metrics"]["timings"]) == 10

    asyncio.run(scenario())


def test_cancel_parent_slot_cancels_children_and_snapshot_replay_is_bounded():
    root, slots = hierarchy()
    parent = slots[0]
    child = SlotSupervisor(
        root.prism_id,
        "child-supervisor",
        parent_slot_id=parent.slot_id,
    )
    scheduler = PrismScheduler()
    scheduler.register_slot(parent)
    scheduler.register_slot(child)
    scheduler.submit(task("a", parent.slot_id))
    scheduler.submit(task("b", child.slot_id))
    assert scheduler.cancel_slot(parent.slot_id) == ("a", "b")
    snapshot = scheduler.snapshot()

    restored = PrismScheduler()
    restored.register_slot(parent)
    restored.register_slot(child)
    restored.submit(task("a", parent.slot_id))
    restored.submit(task("b", child.slot_id))
    restored.restore_states(snapshot)
    assert restored.states == {"a": "cancelled", "b": "cancelled"}
    with pytest.raises(PrismSchedulerError, match="digest"):
        restored.restore_states(snapshot | {"digest": "bad"})


def test_scheduler_validation_and_delta_boundaries():
    with pytest.raises(PrismSchedulerError):
        PrismPolicy(global_worker_limit=2)
    with pytest.raises(PrismSchedulerError):
        ResourceVector(workers=-1)
    root, slots = hierarchy()
    scheduler = PrismScheduler()
    scheduler.register_slot(slots[0])
    scheduler.submit(task("a", slots[0].slot_id))
    scheduler.submit(task("b", slots[0].slot_id, depends=("a",)))
    assert scheduler.apply_delta(("a",)) == ("a", "b")
    with pytest.raises(PrismSchedulerError):
        scheduler.apply_delta(("missing",))
    active = scheduler.next_batch()[0]
    with pytest.raises(PrismSchedulerError, match="non-owner"):
        scheduler.complete("a", "accepted", owner_agent="wrong", fence=1)
    scheduler.complete(
        "a",
        "accepted",
        owner_agent=active.ownership.owner_agent,
        fence=active.ownership.fence,
    )
    assert root.prism_id


def test_policy_resource_task_and_observation_validation_boundaries():
    for kwargs in (
        {"max_tasks_per_slot": 0},
        {"recovery_reserve": -1},
    ):
        with pytest.raises(PrismSchedulerError):
            PrismPolicy(**kwargs)
    assert PrismPolicy(max_tasks_per_slot=100, max_active_slots=None, global_worker_limit=1000)
    with pytest.raises(PrismSchedulerError):
        ResourceVector(workers=True)
    assert ResourceVector(workers=2, cpu_millis=3).plus(
        ResourceVector(workers=1, cpu_millis=4)
    ) == ResourceVector(workers=3, cpu_millis=7)
    assert ResourceVector(workers=2).fits(ResourceVector(workers=1)) == (
        False,
        "workers",
    )
    with pytest.raises(PrismSchedulerError):
        BudgetObservation(ResourceVector(), provider_retry_after_ns=-1)

    _, slots = hierarchy()
    valid = task("a", slots[0].slot_id)
    for changes in (
        {"task_id": "other"},
        {"priority": True},
        {"kind": "unknown"},
        {"resources": ResourceVector(workers=0)},
        {"depends_on": ("a",)},
        {"hard_conflicts": ("a",)},
    ):
        with pytest.raises(PrismSchedulerError):
            dataclasses.replace(valid, **changes)


def test_controller_all_denial_and_lifecycle_paths():
    _, slots = hierarchy()
    policy = PrismPolicy(
        global_worker_limit=4, recovery_reserve=0, validation_reserve=0
    )
    controller = AdmissionController(
        policy,
        BudgetObservation(ResourceVector(workers=4, cpu_millis=1)),
    )
    heavy = task(
        "heavy",
        slots[0].slot_id,
        resources=ResourceVector(cpu_millis=2),
    )
    assert controller.decide(heavy).reason_code == "CPU_MILLIS_PRESSURE"
    controller.update(BudgetObservation(ResourceVector(workers=4, cpu_millis=10)))
    exclusive = task("a", slots[0].slot_id, exclusive=("build",))
    decision = controller.decide(exclusive)
    controller.acquire(exclusive, decision)
    assert (
        controller.decide(task("b", slots[0].slot_id, exclusive=("build",))).reason_code
        == "EXCLUSIVE_RESOURCE_BUSY"
    )
    with pytest.raises(PrismSchedulerError, match="already"):
        controller.decide(exclusive)
    with pytest.raises(PrismSchedulerError, match="matching"):
        controller.acquire(heavy, decision)
    with pytest.raises(PrismSchedulerError, match="duplicate"):
        controller.acquire(exclusive, decision)
    controller.release("a")
    with pytest.raises(PrismSchedulerError, match="inactive"):
        controller.release("a")
    assert controller.decisions()


def test_slot_and_submission_validation_boundaries():
    root, slots = hierarchy(slot_count=2)
    one_slot = PrismScheduler(PrismPolicy(max_active_slots=1, global_worker_limit=3))
    one_slot.register_slot(slots[0])
    with pytest.raises(PrismSchedulerError, match="duplicate"):
        one_slot.register_slot(slots[0])
    with pytest.raises(PrismSchedulerError, match="max_active"):
        one_slot.register_slot(slots[1])

    parent_missing = SlotSupervisor(
        root.prism_id,
        "child",
        parent_slot_id="slot:missing",
    )
    with pytest.raises(PrismSchedulerError, match="parent slot"):
        PrismScheduler().register_slot(parent_missing)

    strict = PrismScheduler(PrismPolicy(max_tasks_per_slot=11, global_worker_limit=3))
    with pytest.raises(PrismSchedulerError, match="capacity"):
        strict.register_slot(slots[0])

    scheduler = PrismScheduler()
    scheduler.register_slot(slots[0])
    with pytest.raises(PrismSchedulerError, match="unknown slot"):
        scheduler.submit(task("x", slots[1].slot_id))
    with pytest.raises(PrismSchedulerError, match="dependency"):
        scheduler.submit(task("x", slots[0].slot_id, depends=("missing",)))
    scheduler.submit(task("x", slots[0].slot_id))
    with pytest.raises(PrismSchedulerError, match="duplicate task"):
        scheduler.submit(task("x", slots[0].slot_id))
    with pytest.raises(PrismSchedulerError, match="unknown slot"):
        scheduler.cancel_slot("missing")


def test_execute_failure_invalid_verdict_and_blocked_dependency_are_receipted():
    async def scenario():
        _, slots = hierarchy()
        scheduler = PrismScheduler(
            PrismPolicy(global_worker_limit=4, recovery_reserve=0, validation_reserve=0)
        )
        scheduler.register_slot(slots[0])
        scheduler.submit(task("raises", slots[0].slot_id))
        scheduler.submit(task("invalid", slots[0].slot_id))
        scheduler.submit(task("dependent", slots[0].slot_id, depends=("raises",)))

        async def worker(item):
            if item.task_id == "raises":
                raise RuntimeError("boom")
            return "not-a-terminal-verdict"

        result = await scheduler.execute(worker)
        assert result["states"] == {
            "dependent": "blocked",
            "invalid": "failed",
            "raises": "failed",
        }
        assert (
            result["queued_reasons"]["dependent"] == "UNSATISFIED_DEPENDENCY_OR_BUDGET"
        )

    asyncio.run(scenario())


def test_cancel_running_task_and_restore_rejects_task_set_or_running():
    _, slots = hierarchy()
    scheduler = PrismScheduler()
    scheduler.register_slot(slots[0])
    scheduler.submit(task("a", slots[0].slot_id))
    scheduler.next_batch()
    assert scheduler.cancel_slot(slots[0].slot_id) == ("a",)
    snapshot = scheduler.snapshot()

    missing = PrismScheduler()
    missing.register_slot(slots[0])
    with pytest.raises(PrismSchedulerError, match="task set"):
        missing.restore_states(snapshot)
    running = dict(snapshot)
    running["states"] = {"a": "running"}
    body = dict(running)
    body.pop("digest")
    running["digest"] = canonical_sha256(body)
    with pytest.raises(PrismSchedulerError, match="lease reconciliation"):
        scheduler.restore_states(running)
