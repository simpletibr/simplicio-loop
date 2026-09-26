"""Hierarchical Prism scheduler and adaptive admission controller.

Logical capacity is independent from physical worker capacity.  A slot has a
minimum of ten tasks and no logical upper bound; physical admission remains
governed by observed worker/resource capacity.  This module never mutates
source, creates commits, or applies delivery effects itself.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from .hbp_ledger import canonical_sha256
from .prism_contracts import (
    MAX_PRISM_DEPTH,
    MIN_TASKS_PER_SLOT,
    AdmissionReceipt,
    SlotSupervisor,
    TaskOwnership,
    admit_task,
)

SCHEDULER_SCHEMA = "simplicio.prism-scheduler/v1"
DECISION_SCHEMA = "simplicio.prism-admission-decision/v1"
SNAPSHOT_SCHEMA = "simplicio.prism-scheduler-snapshot/v1"
TASK_KINDS = frozenset(
    {"implementation", "recovery", "validation", "review", "integration"}
)
TERMINAL = frozenset({"accepted", "failed", "blocked", "cancelled"})


class PrismSchedulerError(RuntimeError):
    """The scheduler cannot preserve bounded/lossless execution."""

    reason_code = "PRISM_SCHEDULER_ERROR"


def _positive(value: int, name: str, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PrismSchedulerError(f"{name} must be a positive integer")
    if maximum is not None and value > maximum:
        raise PrismSchedulerError(f"{name} exceeds {maximum}")
    return value


@dataclass(frozen=True)
class PrismPolicy:
    # Historical field names remain wire-compatible; the first is now the
    # minimum slot capacity and the second is an optional operator override.
    max_tasks_per_slot: int = MIN_TASKS_PER_SLOT
    max_active_slots: int | None = None
    global_worker_limit: int = 20
    max_depth: int = MAX_PRISM_DEPTH
    adaptive_concurrency: bool = True
    recovery_reserve: int = 1
    validation_reserve: int = 1

    def __post_init__(self) -> None:
        _positive(self.max_tasks_per_slot, "max_tasks_per_slot")
        if self.max_tasks_per_slot < MIN_TASKS_PER_SLOT:
            raise PrismSchedulerError(
                f"max_tasks_per_slot must be at least {MIN_TASKS_PER_SLOT}"
            )
        if self.max_active_slots is not None:
            _positive(self.max_active_slots, "max_active_slots")
        _positive(self.global_worker_limit, "global_worker_limit")
        _positive(self.max_depth, "max_depth", MAX_PRISM_DEPTH)
        if min(self.recovery_reserve, self.validation_reserve) < 0:
            raise PrismSchedulerError("reserved capacity cannot be negative")
        if self.recovery_reserve + self.validation_reserve >= self.global_worker_limit:
            raise PrismSchedulerError(
                "reserved capacity must leave an implementation worker"
            )


@dataclass(frozen=True)
class ResourceVector:
    workers: int = 1
    cpu_millis: int = 0
    rss_bytes: int = 0
    io_units: int = 0
    provider_requests: int = 0
    tokens: int = 0
    disk_bytes: int = 0
    model_slots: int = 0
    network_queue: int = 0
    context_tokens: int = 0
    evidence_bytes: int = 0

    def __post_init__(self) -> None:
        for name, value in dataclasses.asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PrismSchedulerError(f"resource {name} must be non-negative")

    def plus(self, other: ResourceVector) -> ResourceVector:
        return ResourceVector(
            **{
                name: getattr(self, name) + getattr(other, name)
                for name in dataclasses.asdict(self)
            }
        )

    def fits(self, limit: ResourceVector) -> tuple[bool, str]:
        for name in dataclasses.asdict(self):
            ceiling = getattr(limit, name)
            if ceiling and getattr(self, name) > ceiling:
                return False, name
        return True, ""


@dataclass(frozen=True)
class BudgetObservation:
    limit: ResourceVector
    measured: tuple[str, ...] = ()
    unavailable: tuple[str, ...] = ()
    null_reasons: Mapping[str, str] = field(default_factory=dict)
    provider_retry_after_ns: int | None = None
    observed_at_ns: int = 0
    device_workers: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        if (
            self.provider_retry_after_ns is not None
            and self.provider_retry_after_ns < 0
        ):
            raise PrismSchedulerError("provider_retry_after_ns cannot be negative")
        object.__setattr__(self, "measured", tuple(sorted(set(self.measured))))
        object.__setattr__(self, "unavailable", tuple(sorted(set(self.unavailable))))
        invalid = set(self.null_reasons) - set(self.unavailable)
        if invalid:
            raise PrismSchedulerError("null_reasons require unavailable metrics")
        for name, reason in self.null_reasons.items():
            if not str(reason).strip():
                raise PrismSchedulerError(f"empty null_reason for {name}")
        for device_id, workers in self.device_workers:
            if not device_id or workers < 1:
                raise PrismSchedulerError("invalid device worker capacity")


@dataclass(frozen=True)
class ScheduledTask:
    task_id: str
    slot_id: str
    ownership: TaskOwnership
    depends_on: tuple[str, ...] = ()
    hard_conflicts: tuple[str, ...] = ()
    soft_contention: tuple[str, ...] = ()
    exclusive_resources: tuple[str, ...] = ()
    priority: int = 0
    kind: str = "implementation"
    resources: ResourceVector = field(default_factory=ResourceVector)

    def __post_init__(self) -> None:
        if (
            self.task_id != self.ownership.task_id
            or self.slot_id != self.ownership.slot_id
        ):
            raise PrismSchedulerError("task identity does not match ownership")
        for name in (
            "depends_on",
            "hard_conflicts",
            "soft_contention",
            "exclusive_resources",
        ):
            object.__setattr__(
                self,
                name,
                tuple(
                    sorted(
                        {
                            str(value).strip()
                            for value in getattr(self, name)
                            if str(value).strip()
                        }
                    )
                ),
            )
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise PrismSchedulerError("priority must be an integer")
        if self.kind not in TASK_KINDS:
            raise PrismSchedulerError("unknown task kind")
        if self.resources.workers < 1:
            raise PrismSchedulerError("each active task consumes at least one worker")
        if self.task_id in self.depends_on or self.task_id in self.hard_conflicts:
            raise PrismSchedulerError("task cannot depend on or conflict with itself")


@dataclass(frozen=True)
class AdmissionDecision:
    task_id: str
    slot_id: str
    admitted: bool
    reason_code: str
    evidence: Mapping[str, Any]
    schema: str = DECISION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        payload = dataclasses.asdict(self)
        payload["decision_hash"] = canonical_sha256(payload)
        return payload


class AdmissionController:
    """Deterministic resource admission with explicit conservative fallback."""

    def __init__(
        self,
        policy: PrismPolicy,
        observation: BudgetObservation | None = None,
    ) -> None:
        self.policy = policy
        self.observation = observation or BudgetObservation(
            ResourceVector(workers=policy.global_worker_limit)
        )
        self._active: dict[str, ScheduledTask] = {}
        self._per_slot: dict[str, int] = {}
        self._exclusive: dict[str, str] = {}
        self._decisions: list[dict[str, Any]] = []

    def update(self, observation: BudgetObservation) -> None:
        self.observation = observation

    @property
    def active(self) -> Mapping[str, ScheduledTask]:
        return dict(self._active)

    def _usage(self) -> ResourceVector:
        usage = ResourceVector(workers=0)
        for task in self._active.values():
            usage = usage.plus(task.resources)
        return usage

    def decide(
        self, task: ScheduledTask, *, now_ns: int | None = None
    ) -> AdmissionDecision:
        now_ns = time.time_ns() if now_ns is None else int(now_ns)
        if task.task_id in self._active:
            raise PrismSchedulerError("task is already physically active")
        observation = self.observation
        if "workers" in observation.unavailable:
            return self._record(
                task,
                False,
                "PHYSICAL_CAPACITY_UNAVAILABLE",
                {
                    "unavailable": list(observation.unavailable),
                    "null_reasons": dict(observation.null_reasons),
                    "limit": dataclasses.asdict(observation.limit),
                },
            )
        if (
            observation.provider_retry_after_ns is not None
            and now_ns < observation.provider_retry_after_ns
            and task.resources.provider_requests
        ):
            return self._record(
                task,
                False,
                "PROVIDER_RETRY_AFTER",
                {
                    "retry_after_ns": observation.provider_retry_after_ns,
                },
            )
        if any(resource in self._exclusive for resource in task.exclusive_resources):
            return self._record(
                task,
                False,
                "EXCLUSIVE_RESOURCE_BUSY",
                {
                    "resources": list(task.exclusive_resources),
                },
            )

        limit = observation.limit
        if observation.unavailable:
            limit = replace(limit, workers=min(limit.workers, 1))
        implementation_active = sum(
            item.kind == "implementation" for item in self._active.values()
        )
        reserve = self.policy.recovery_reserve + self.policy.validation_reserve
        if task.kind == "implementation" and implementation_active >= max(
            1, limit.workers - reserve
        ):
            return self._record(
                task,
                False,
                "RESERVED_CAPACITY",
                {
                    "implementation_active": implementation_active,
                    "reserved_workers": reserve,
                },
            )

        requested = self._usage().plus(task.resources)
        fits, dimension = requested.fits(limit)
        if not fits:
            return self._record(
                task,
                False,
                f"{dimension.upper()}_PRESSURE",
                {
                    "usage": dataclasses.asdict(requested),
                    "limit": dataclasses.asdict(limit),
                },
            )
        reason = (
            "METRIC_UNAVAILABLE_CONSERVATIVE" if observation.unavailable else "ADMITTED"
        )
        return self._record(
            task,
            True,
            reason,
                {
                    "unavailable": list(observation.unavailable),
                    "null_reasons": dict(observation.null_reasons),
                    "limit": dataclasses.asdict(limit),
                    "device_workers": list(observation.device_workers),
                },
            )

    def _record(
        self,
        task: ScheduledTask,
        admitted: bool,
        reason: str,
        evidence: Mapping[str, Any],
    ) -> AdmissionDecision:
        decision = AdmissionDecision(
            task.task_id, task.slot_id, admitted, reason, dict(evidence)
        )
        self._decisions.append(decision.to_dict())
        return decision

    def acquire(self, task: ScheduledTask, decision: AdmissionDecision) -> None:
        if not decision.admitted or decision.task_id != task.task_id:
            raise PrismSchedulerError("only the matching admitted decision may acquire")
        if task.task_id in self._active:
            raise PrismSchedulerError("duplicate physical acquire")
        self._active[task.task_id] = task
        self._per_slot[task.slot_id] = self._per_slot.get(task.slot_id, 0) + 1
        for resource in task.exclusive_resources:
            self._exclusive[resource] = task.task_id

    def release(self, task_id: str) -> None:
        task = self._active.pop(task_id, None)
        if task is None:
            raise PrismSchedulerError("cannot release an inactive task")
        self._per_slot[task.slot_id] -= 1
        for resource in task.exclusive_resources:
            if self._exclusive.get(resource) == task_id:
                self._exclusive.pop(resource, None)

    def decisions(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._decisions]


class PrismScheduler:
    """Lossless hierarchical ready-set scheduler."""

    def __init__(
        self,
        policy: PrismPolicy | None = None,
        *,
        observation: BudgetObservation | None = None,
    ) -> None:
        self.policy = policy or PrismPolicy()
        self.controller = AdmissionController(self.policy, observation)
        self.slots: dict[str, SlotSupervisor] = {}
        self.children: dict[str, set[str]] = {}
        self.tasks: dict[str, ScheduledTask] = {}
        self.states: dict[str, str] = {}
        self.queued_reasons: dict[str, str] = {}
        self._served: dict[str, int] = {}
        # Monotonic submission order, independent of ``task_id`` spelling. Two
        # tasks tied on (served-count, priority, slot) must break the tie by
        # *when they were submitted*, not by comparing ``task_id`` as a raw
        # string -- "run-task-10" sorts before "run-task-2" lexicographically,
        # which silently reordered a same-lane wave of 10+ tasks (issue #1298).
        self._sequence: dict[str, int] = {}
        self._decisions: list[dict[str, Any]] = []
        self._timings: dict[str, dict[str, int]] = {}
        self._max_overlap = 0
        self._affected_ready_sets: set[str] = set()

    def register_slot(self, slot: SlotSupervisor) -> None:
        if slot.slot_id in self.slots:
            raise PrismSchedulerError("duplicate slot")
        if (
            self.policy.max_active_slots is not None
            and len(self.slots) >= self.policy.max_active_slots
        ):
            raise PrismSchedulerError("max_active_slots exceeded")
        if slot.capacity < self.policy.max_tasks_per_slot:
            raise PrismSchedulerError("slot capacity is below scheduler minimum")
        if slot.parent_slot_id and slot.parent_slot_id not in self.slots:
            raise PrismSchedulerError("parent slot must be registered first")
        self.slots[slot.slot_id] = slot
        if slot.parent_slot_id:
            self.children.setdefault(slot.parent_slot_id, set()).add(slot.slot_id)

    def submit(self, task: ScheduledTask) -> AdmissionReceipt:
        if task.task_id in self.tasks:
            raise PrismSchedulerError("duplicate task")
        slot = self.slots.get(task.slot_id)
        if slot is None:
            raise PrismSchedulerError("task references unknown slot")
        for dependency in task.depends_on:
            if dependency not in self.tasks:
                raise PrismSchedulerError("dependency must be submitted first")
        updated, receipt = admit_task(slot, task.ownership)
        self.tasks[task.task_id] = task
        self.states[task.task_id] = "queued"
        self._sequence[task.task_id] = len(self._sequence)
        if receipt.admitted:
            self.slots[slot.slot_id] = updated
            self.queued_reasons[task.task_id] = "READY_CHECK_PENDING"
        else:
            self.queued_reasons[task.task_id] = receipt.reason_code
        return receipt

    def apply_delta(self, task_ids: Sequence[str]) -> tuple[str, ...]:
        unknown = sorted(set(task_ids) - set(self.tasks))
        if unknown:
            raise PrismSchedulerError("delta references unknown tasks")
        affected = set(task_ids)
        for item in self.tasks.values():
            if set(item.depends_on) & set(task_ids):
                affected.add(item.task_id)
        self._affected_ready_sets.update(affected)
        return tuple(sorted(affected))

    def _ready(self, task: ScheduledTask) -> bool:
        if self.states.get(task.task_id) != "queued":
            return False
        if self.queued_reasons.get(task.task_id) == "SLOT_LOGICAL_CAPACITY":
            return False
        if any(
            self.states.get(dependency) != "accepted" for dependency in task.depends_on
        ):
            return False
        active_ids = set(self.controller.active)
        if set(task.hard_conflicts) & active_ids:
            return False
        for active in self.controller.active.values():
            if task.task_id in active.hard_conflicts:
                return False
        return True

    def ready_set(self) -> tuple[str, ...]:
        ready = [task for task in self.tasks.values() if self._ready(task)]
        ready.sort(
            key=lambda task: (
                self._served.get(task.slot_id, 0),
                -task.priority,
                task.slot_id,
                self._sequence.get(task.task_id, 0),
            )
        )
        return tuple(task.task_id for task in ready)

    def next_batch(self, *, now_ns: int | None = None) -> tuple[ScheduledTask, ...]:
        selected: list[ScheduledTask] = []
        for task_id in self.ready_set():
            task = self.tasks[task_id]
            if not self._ready(task):
                self.queued_reasons[task_id] = "HARD_CONFLICT_ACTIVE"
                continue
            decision = self.controller.decide(task, now_ns=now_ns)
            self._decisions.append(decision.to_dict())
            if not decision.admitted:
                self.queued_reasons[task_id] = decision.reason_code
                continue
            self.controller.acquire(task, decision)
            self.states[task_id] = "running"
            self.queued_reasons.pop(task_id, None)
            self._served[task.slot_id] = self._served.get(task.slot_id, 0) + 1
            selected.append(task)
        self._max_overlap = max(self._max_overlap, len(self.controller.active))
        return tuple(selected)

    def complete(
        self,
        task_id: str,
        state: str,
        *,
        owner_agent: str,
        fence: int,
    ) -> None:
        if state not in TERMINAL:
            raise PrismSchedulerError("completion state must be terminal")
        task = self.tasks.get(task_id)
        if task is None or self.states.get(task_id) != "running":
            raise PrismSchedulerError("task is not active")
        if task.ownership.owner_agent != owner_agent or task.ownership.fence != int(
            fence
        ):
            raise PrismSchedulerError("stale or non-owner completion")
        self.controller.release(task_id)
        self.states[task_id] = state

    def cancel_slot(self, slot_id: str) -> tuple[str, ...]:
        if slot_id not in self.slots:
            raise PrismSchedulerError("unknown slot")
        targets = {slot_id}
        frontier = [slot_id]
        while frontier:
            parent = frontier.pop()
            for child in self.children.get(parent, ()):
                if child not in targets:
                    targets.add(child)
                    frontier.append(child)
        cancelled: list[str] = []
        for task_id, task in self.tasks.items():
            if task.slot_id not in targets or self.states[task_id] in TERMINAL:
                continue
            if self.states[task_id] == "running":
                self.controller.release(task_id)
            self.states[task_id] = "cancelled"
            cancelled.append(task_id)
        return tuple(sorted(cancelled))

    async def execute(
        self,
        worker: Callable[[ScheduledTask], Awaitable[str]],
    ) -> dict[str, Any]:
        """Run external workers in bounded TaskGroups until convergence."""

        async def run_one(task: ScheduledTask) -> None:
            started = time.perf_counter_ns()
            self._timings[task.task_id] = {"started_ns": started}
            state = "failed"
            try:
                result = await worker(task)
                state = result if result in TERMINAL else "failed"
            except asyncio.CancelledError:
                state = "cancelled"
            except Exception:  # noqa: BLE001 - external worker failures become task receipts
                state = "failed"
            finally:
                self._timings[task.task_id]["finished_ns"] = time.perf_counter_ns()
                if self.states.get(task.task_id) == "running":
                    self.complete(
                        task.task_id,
                        state,
                        owner_agent=task.ownership.owner_agent,
                        fence=task.ownership.fence,
                    )

        while any(state not in TERMINAL for state in self.states.values()):
            batch = self.next_batch()
            if not batch:
                for task_id, state in tuple(self.states.items()):
                    if state == "queued":
                        self.states[task_id] = "blocked"
                        self.queued_reasons[task_id] = (
                            "UNSATISFIED_DEPENDENCY_OR_BUDGET"
                        )
                break
            async with asyncio.TaskGroup() as group:
                for task in batch:
                    group.create_task(run_one(task), name=f"prism-{task.task_id}")
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        payload = {
            "schema": SNAPSHOT_SCHEMA,
            "policy": dataclasses.asdict(self.policy),
            "slots": sorted(self.slots),
            "slot_records": [
                self.slots[slot_id].to_dict() for slot_id in sorted(self.slots)
            ],
            "task_records": [
                dataclasses.asdict(self.tasks[task_id]) for task_id in sorted(self.tasks)
            ],
            "states": dict(sorted(self.states.items())),
            "queued_reasons": dict(sorted(self.queued_reasons.items())),
            "active": sorted(self.controller.active),
            "decisions": list(self._decisions),
            "affected_ready_sets": sorted(self._affected_ready_sets),
            "metrics": {
                "logical_tasks": len(self.tasks),
                "logical_slots": len(self.slots),
                "max_temporal_overlap": self._max_overlap,
                "timings": dict(sorted(self._timings.items())),
            },
        }
        payload["digest"] = canonical_sha256(payload)
        return payload

    def restore_states(self, snapshot: Mapping[str, Any]) -> None:
        body = dict(snapshot)
        digest = body.pop("digest", None)
        if body.get("schema") != SNAPSHOT_SCHEMA or canonical_sha256(body) != digest:
            raise PrismSchedulerError("snapshot digest mismatch")
        states = body.get("states")
        if not isinstance(states, Mapping) or set(states) != set(self.tasks):
            raise PrismSchedulerError("snapshot task set mismatch")
        slot_records = body.get("slot_records")
        if not isinstance(slot_records, list) or {
            str(record.get("slot_id")) for record in slot_records
            if isinstance(record, Mapping)
        } != set(self.slots):
            raise PrismSchedulerError("snapshot slot hierarchy mismatch")
        task_records = body.get("task_records")
        if not isinstance(task_records, list) or len(task_records) != len(self.tasks):
            raise PrismSchedulerError("snapshot task records missing")
        expected_tasks = {
            task_id: dataclasses.asdict(task)
            for task_id, task in self.tasks.items()
        }
        actual_tasks = {
            str(record.get("task_id")): record
            for record in task_records
            if isinstance(record, Mapping)
        }
        if set(actual_tasks) != set(expected_tasks) or any(
            canonical_sha256(actual_tasks[task_id]) != canonical_sha256(expected_tasks[task_id])
            for task_id in expected_tasks
        ):
            raise PrismSchedulerError("snapshot task definition mismatch")
        if any(state == "running" for state in states.values()):
            raise PrismSchedulerError("running state requires lease reconciliation")
        self.states = {str(key): str(value) for key, value in states.items()}
        self.queued_reasons = {
            str(key): str(value)
            for key, value in dict(body.get("queued_reasons") or {}).items()
        }


__all__ = [
    "DECISION_SCHEMA",
    "SCHEDULER_SCHEMA",
    "SNAPSHOT_SCHEMA",
    "AdmissionController",
    "AdmissionDecision",
    "BudgetObservation",
    "PrismPolicy",
    "PrismScheduler",
    "PrismSchedulerError",
    "ResourceVector",
    "ScheduledTask",
]
