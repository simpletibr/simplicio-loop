"""Bounded asyncio execution fabric for logical Loop slots.

The fabric deliberately separates logical work from physical capacity.  A
bounded admission queue applies producer backpressure, while the dispatcher
uses structured concurrency and resource-aware admission to keep reads
parallel and conflicting mutations exclusive.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Mapping, Optional

from .error_truncation import truncate_error_with_cause

FABRIC_SCHEMA = "simplicio.fabric-scheduler/v1"
JOURNAL_SCHEMA = "simplicio.fabric-transition/v1"
TERMINAL_STATES = frozenset(("succeeded", "failed", "cancelled"))
WRITE_MODES = frozenset(("write", "build", "release"))
VALID_STATES = frozenset(
    ("queued", "ready", "running", "draining", "succeeded", "failed", "cancelled")
)


class FabricClosed(RuntimeError):
    """The fabric no longer accepts work."""


class DuplicateJob(ValueError):
    """A job id must be unique for one scheduler journal."""


class ReplayError(ValueError):
    """A transition journal is invalid or has an incomplete hash chain."""


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class FabricJob:
    job_id: str
    run: Callable[[], Awaitable[Any]]
    capability: str = "default"
    resources: frozenset[str] = field(default_factory=frozenset)
    mode: str = "read"
    priority: int = 0
    timeout_seconds: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.job_id.strip() or not self.capability.strip():
            raise ValueError("job_id and capability are required")
        if self.mode not in {"read", "write", "build", "release"}:
            raise ValueError("unsupported job mode")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise ValueError("priority must be an integer")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        object.__setattr__(self, "resources", frozenset(str(item) for item in self.resources))


@dataclass
class _Pending:
    job: FabricJob
    future: "asyncio.Future[Any]"
    sequence: int
    enqueued_at: float


class TransitionJournal:
    """Append-only, fsync'd JSONL transition journal with a SHA-256 chain."""

    def __init__(self, path: Optional[str]) -> None:
        self.path = Path(path) if path else None
        self._rows: List[Dict[str, Any]] = self.replay() if self.path else []

    def replay(self) -> List[Dict[str, Any]]:
        if self.path is None or not self.path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        previous = ""
        for number, raw in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except ValueError as exc:
                raise ReplayError("invalid JSON at transition %d" % number) from exc
            body = dict(row)
            recorded_hash = body.pop("hash", None)
            if (
                row.get("schema") != JOURNAL_SCHEMA
                or row.get("sequence") != len(rows) + 1
                or row.get("prev_hash", "") != previous
                or row.get("state") not in VALID_STATES
                or recorded_hash != _digest(body)
            ):
                raise ReplayError("invalid transition chain at line %d" % number)
            previous = str(recorded_hash)
            rows.append(row)
        return rows

    def append(self, job_id: str, state: str, **detail: Any) -> Dict[str, Any]:
        if state not in VALID_STATES:
            raise ValueError("invalid fabric state")
        body: Dict[str, Any] = {
            "schema": JOURNAL_SCHEMA,
            "sequence": len(self._rows) + 1,
            "prev_hash": self._rows[-1]["hash"] if self._rows else "",
            "job_id": job_id,
            "state": state,
            "observed_at_ns": time.time_ns(),
            "detail": detail,
        }
        body["hash"] = _digest(body)
        self._rows.append(body)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(body, ensure_ascii=False, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        return dict(body)

    def terminal(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for row in self._rows:
            if row["state"] in TERMINAL_STATES:
                result[row["job_id"]] = row["state"]
        return result

    @property
    def rows(self) -> List[Dict[str, Any]]:
        return [dict(row) for row in self._rows]


class AsyncFabricScheduler:
    """Structured-concurrency scheduler with bounded, event-driven admission."""

    def __init__(
        self,
        *,
        max_running: int,
        queue_capacity: int,
        capability_limits: Optional[Mapping[str, int]] = None,
        capability_queue_limits: Optional[Mapping[str, int]] = None,
        resource_queue_limits: Optional[Mapping[str, int]] = None,
        aging_seconds: float = 1.0,
        journal_path: Optional[str] = None,
    ) -> None:
        if max_running < 1 or queue_capacity < 1 or aging_seconds <= 0:
            raise ValueError("capacity and aging_seconds must be positive")
        limits = dict(capability_limits or {})
        queue_limits = dict(capability_queue_limits or {})
        resource_limits = dict(resource_queue_limits or {})
        if any(value < 1 for value in (*limits.values(), *queue_limits.values(), *resource_limits.values())):
            raise ValueError("capability/resource limits must be positive")
        self.max_running = max_running
        self.queue_capacity = queue_capacity
        self.capability_limits = limits
        self.capability_queue_limits = queue_limits
        self.resource_queue_limits = resource_limits
        self.aging_seconds = aging_seconds
        self.journal = TransitionJournal(journal_path)
        self._condition = asyncio.Condition()
        self._pending: List[_Pending] = []
        self._running: Dict[str, asyncio.Task[Any]] = {}
        self._running_jobs: Dict[str, FabricJob] = {}
        self._capability_running: Dict[str, int] = {}
        self._states: Dict[str, str] = self.journal.terminal()
        self._sequence = 0
        self._accepting = True
        self._stop = False
        self._started = False
        self._task_group: Any = None
        self._dispatcher: Optional[asyncio.Task[Any]] = None
        self._max_observed_running = 0
        self._producer_waits = 0
        self._starvation_promotions = 0

    async def __aenter__(self) -> "AsyncFabricScheduler":
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.shutdown(cancel=exc is not None)

    async def start(self) -> None:
        if self._started:
            return
        if not hasattr(asyncio, "TaskGroup"):
            raise RuntimeError("AsyncFabricScheduler requires Python 3.11+ asyncio.TaskGroup")
        self._started = True
        self._task_group = asyncio.TaskGroup()
        await self._task_group.__aenter__()
        self._dispatcher = self._task_group.create_task(
            self._dispatch_loop(), name="simplicio-fabric-dispatcher"
        )

    async def submit(self, job: FabricJob) -> "asyncio.Future[Any]":
        if not self._started:
            await self.start()
        loop = asyncio.get_running_loop()
        async with self._condition:
            if not self._accepting:
                raise FabricClosed("scheduler is draining")
            if job.job_id in self._states or any(item.job.job_id == job.job_id for item in self._pending):
                raise DuplicateJob(job.job_id)
            while self._admission_full(job):
                self._producer_waits += 1
                await self._condition.wait()
                if not self._accepting:
                    raise FabricClosed("scheduler is draining")
            future: "asyncio.Future[Any]" = loop.create_future()
            self._sequence += 1
            self._pending.append(_Pending(job, future, self._sequence, time.monotonic()))
            self._states[job.job_id] = "queued"
            self.journal.append(
                job.job_id,
                "queued",
                capability=job.capability,
                mode=job.mode,
                resources=sorted(job.resources),
                priority=job.priority,
            )
            self._condition.notify_all()
            return future

    def _admission_full(self, job: FabricJob) -> bool:
        if len(self._pending) >= self.queue_capacity:
            return True
        capability_limit = self.capability_queue_limits.get(job.capability)
        if capability_limit is not None:
            capability_depth = sum(
                item.job.capability == job.capability for item in self._pending
            )
            if capability_depth >= capability_limit:
                return True
        for resource in job.resources:
            resource_limit = self.resource_queue_limits.get(resource)
            if resource_limit is None:
                continue
            resource_depth = sum(
                resource in item.job.resources for item in self._pending
            )
            if resource_depth >= resource_limit:
                return True
        return False

    def _resources_available(self, candidate: FabricJob) -> bool:
        for running in self._running_jobs.values():
            overlap = candidate.resources.intersection(running.resources)
            if not overlap:
                continue
            if candidate.mode in WRITE_MODES or running.mode in WRITE_MODES:
                return False
        if candidate.mode == "release" and self._running_jobs:
            return False
        if any(job.mode == "release" for job in self._running_jobs.values()):
            return False
        return True

    def _capacity_available(self, job: FabricJob) -> bool:
        if len(self._running) >= self.max_running:
            return False
        limit = self.capability_limits.get(job.capability, self.max_running)
        return self._capability_running.get(job.capability, 0) < limit

    def _choose(self) -> Optional[_Pending]:
        now = time.monotonic()
        candidates = [
            item
            for item in self._pending
            if self._capacity_available(item.job) and self._resources_available(item.job)
        ]
        if not candidates:
            return None

        def rank(item: _Pending) -> tuple[int, int]:
            age_steps = int((now - item.enqueued_at) / self.aging_seconds)
            return (item.job.priority + age_steps, -item.sequence)

        chosen = max(candidates, key=rank)
        if int((now - chosen.enqueued_at) / self.aging_seconds) > 0:
            self._starvation_promotions += 1
        return chosen

    async def _dispatch_loop(self) -> None:
        while True:
            async with self._condition:
                chosen = self._choose()
                while chosen is None:
                    if self._stop and not self._pending and not self._running:
                        return
                    await self._condition.wait()
                    chosen = self._choose()
                self._pending.remove(chosen)
                self._states[chosen.job.job_id] = "ready"
                self.journal.append(chosen.job.job_id, "ready")
                task = self._task_group.create_task(
                    self._execute(chosen), name="simplicio-fabric-" + chosen.job.job_id
                )
                self._running[chosen.job.job_id] = task
                self._running_jobs[chosen.job.job_id] = chosen.job
                self._capability_running[chosen.job.capability] = (
                    self._capability_running.get(chosen.job.capability, 0) + 1
                )
                self._max_observed_running = max(
                    self._max_observed_running, len(self._running)
                )
                self._condition.notify_all()

    async def _execute(self, item: _Pending) -> None:
        job = item.job
        self._states[job.job_id] = "running"
        self.journal.append(job.job_id, "running")
        try:
            awaitable = job.run()
            if job.timeout_seconds is None:
                result = await awaitable
            else:
                result = await asyncio.wait_for(awaitable, timeout=job.timeout_seconds)
        except asyncio.CancelledError:
            self._states[job.job_id] = "cancelled"
            self.journal.append(job.job_id, "cancelled", reason="cancelled")
            if not item.future.done():
                item.future.cancel()
        except asyncio.TimeoutError as exc:
            self._states[job.job_id] = "failed"
            self.journal.append(job.job_id, "failed", reason="timeout")
            if not item.future.done():
                item.future.set_exception(exc)
        except Exception as exc:
            self._states[job.job_id] = "failed"
            self.journal.append(
                job.job_id, "failed", reason=type(exc).__name__, message=truncate_error_with_cause(str(exc))
            )
            if not item.future.done():
                item.future.set_exception(exc)
        else:
            # Process adapters intentionally translate task cancellation and
            # deadline expiry into typed results after reaping the child.  Do
            # not misclassify those supervised outcomes as successful merely
            # because the coroutine returned normally.
            if getattr(result, "cancelled", False):
                self._states[job.job_id] = "cancelled"
                self.journal.append(job.job_id, "cancelled", reason="child_cancelled")
                if not item.future.done():
                    item.future.cancel()
            elif getattr(result, "timed_out", False):
                self._states[job.job_id] = "failed"
                self.journal.append(job.job_id, "failed", reason="child_timeout")
                if not item.future.done():
                    item.future.set_exception(asyncio.TimeoutError())
            else:
                self._states[job.job_id] = "succeeded"
                self.journal.append(job.job_id, "succeeded")
                if not item.future.done():
                    item.future.set_result(result)
        finally:
            async with self._condition:
                self._running.pop(job.job_id, None)
                self._running_jobs.pop(job.job_id, None)
                remaining = self._capability_running.get(job.capability, 1) - 1
                if remaining:
                    self._capability_running[job.capability] = remaining
                else:
                    self._capability_running.pop(job.capability, None)
                self._condition.notify_all()

    async def cancel(self, job_id: str) -> bool:
        async with self._condition:
            for item in list(self._pending):
                if item.job.job_id == job_id:
                    self._pending.remove(item)
                    self._states[job_id] = "cancelled"
                    self.journal.append(job_id, "cancelled", reason="cancelled_before_run")
                    item.future.cancel()
                    self._condition.notify_all()
                    return True
            task = self._running.get(job_id)
            if task is None:
                return False
            task.cancel()
            return True

    async def shutdown(self, *, cancel: bool = False) -> Dict[str, Any]:
        if not self._started:
            return self.status()
        async with self._condition:
            self._accepting = False
            for item in list(self._pending):
                self._states[item.job.job_id] = "draining"
                self.journal.append(item.job.job_id, "draining")
            for job_id in list(self._running):
                self._states[job_id] = "draining"
                self.journal.append(job_id, "draining")
            if cancel:
                for item in list(self._pending):
                    self._pending.remove(item)
                    self._states[item.job.job_id] = "cancelled"
                    self.journal.append(item.job.job_id, "cancelled", reason="shutdown")
                    item.future.cancel()
                for task in self._running.values():
                    task.cancel()
            self._stop = True
            self._condition.notify_all()
        await self._task_group.__aexit__(None, None, None)
        self._started = False
        return self.status()

    def status(self) -> Dict[str, Any]:
        terminal = {key: value for key, value in self._states.items() if value in TERMINAL_STATES}
        return {
            "schema": FABRIC_SCHEMA,
            "accepting": self._accepting,
            "queue_capacity": self.queue_capacity,
            "capability_queue_limits": dict(self.capability_queue_limits),
            "resource_queue_limits": dict(self.resource_queue_limits),
            "queued": len(self._pending),
            "running": len(self._running),
            "max_running": self.max_running,
            "max_observed_running": self._max_observed_running,
            "producer_waits": self._producer_waits,
            "starvation_promotions": self._starvation_promotions,
            "capability_running": dict(self._capability_running),
            "states": dict(self._states),
            "terminal": terminal,
            "journal_events": len(self.journal.rows),
        }


def replay_terminal(path: str) -> Dict[str, str]:
    """Validate a persisted journal and reconstruct terminal job outcomes."""

    return TransitionJournal(path).terminal()


__all__ = [
    "AsyncFabricScheduler",
    "DuplicateJob",
    "FabricClosed",
    "FabricJob",
    "ReplayError",
    "TransitionJournal",
    "replay_terminal",
]
