"""Async resident Fast daemon with bounded multiplexing and explicit lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
import hashlib
import json
import time
from typing import Any

PROTOCOL_SCHEMA = "simplicio.fast-daemon-request/v1"
RESPONSE_SCHEMA = "simplicio.fast-daemon-response/v1"
MAX_REQUEST_ID_BYTES = 256
MAX_SLOT_ID_BYTES = 256
MAX_OPERATION_BYTES = 128
MAX_PAYLOAD_BYTES = 256 * 1024
_FORBIDDEN_FIELDS = frozenset({"offset", "mmap_offset", "address", "pointer"})


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class DaemonError(RuntimeError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}")


@dataclass(frozen=True)
class DaemonRequest:
    request_id: str
    slot_id: str
    operation: str
    generation: int
    deadline_ns: int
    payload: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "DaemonRequest":
        if not isinstance(value, Mapping):
            raise DaemonError("protocol_request_invalid")
        if value.get("schema") != PROTOCOL_SCHEMA:
            raise DaemonError("protocol_schema_invalid")
        required = ("request_id", "slot_id", "operation", "generation", "deadline_ns")
        if any(value.get(key) in (None, "") for key in required):
            raise DaemonError("protocol_field_missing")
        request_id = value.get("request_id")
        slot_id = value.get("slot_id")
        operation = value.get("operation")
        generation = value.get("generation")
        deadline_ns = value.get("deadline_ns")
        if (
            not isinstance(request_id, str)
            or not request_id.strip()
            or len(request_id.encode("utf-8")) > MAX_REQUEST_ID_BYTES
            or not isinstance(slot_id, str)
            or not slot_id.strip()
            or len(slot_id.encode("utf-8")) > MAX_SLOT_ID_BYTES
            or not isinstance(operation, str)
            or not operation.strip()
            or len(operation.encode("utf-8")) > MAX_OPERATION_BYTES
            or isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation < 0
            or isinstance(deadline_ns, bool)
            or not isinstance(deadline_ns, int)
            or deadline_ns < 1
        ):
            raise DaemonError("protocol_field_invalid")
        payload = value.get("payload", {})
        if not isinstance(payload, Mapping):
            raise DaemonError("protocol_payload_invalid")
        if _contains_forbidden_field(payload):
            raise DaemonError("protocol_exposes_offset")
        try:
            payload_bytes = len(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8"))
        except (TypeError, ValueError) as error:
            raise DaemonError("protocol_payload_invalid") from error
        if payload_bytes > MAX_PAYLOAD_BYTES:
            raise DaemonError("protocol_payload_too_large")
        return cls(
            request_id=request_id,
            slot_id=slot_id,
            operation=operation,
            generation=generation,
            deadline_ns=deadline_ns,
            payload=dict(payload),
        )


def _contains_forbidden_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        return bool(_FORBIDDEN_FIELDS.intersection(value)) or any(
            _contains_forbidden_field(item) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_field(item) for item in value)
    return False


class ResidentFastDaemon:
    """Owns resident generation pins; Loop remains scheduling/completion authority."""

    def __init__(
        self,
        handler: Callable[[DaemonRequest], Awaitable[Mapping[str, Any]]],
        *,
        max_inflight: int = 20,
        queue_capacity: int = 64,
        generation_opener: Callable[[int], Awaitable[Any]] | None = None,
        generation_closer: Callable[[Any], Awaitable[None]] | None = None,
        backend: str = "python",
        rust_reason: str | None = "RUST_UNAVAILABLE",
    ) -> None:
        if max_inflight < 1 or queue_capacity < 1:
            raise ValueError("bounds must be positive")
        self._handler = handler
        self._max_inflight = max_inflight
        self._queue: asyncio.Queue[tuple[DaemonRequest, asyncio.Future]] = (
            asyncio.Queue(queue_capacity)
        )
        self._generation_opener = generation_opener
        self._generation_closer = generation_closer
        self._backend = backend
        self._rust_reason = rust_reason
        self._pins: dict[int, Any] = {}
        self._opening: dict[int, asyncio.Task] = {}
        self._workers: list[asyncio.Task] = []
        self._active: dict[str, asyncio.Task] = {}
        self._terminal: dict[str, dict[str, Any]] = {}
        self._state = "STOPPED"
        self._epoch = 0
        self._accepted = 0
        self._completed = 0
        self._cancelled = 0

    @property
    def state(self) -> str:
        return self._state

    async def start(self) -> Mapping[str, Any]:
        if self._state not in {"STOPPED", "CRASHED"}:
            return self.health()
        self._epoch += 1
        self._state = "STARTING"
        self._workers = [
            asyncio.create_task(self._worker(), name=f"fast-resident-{i}")
            for i in range(self._max_inflight)
        ]
        self._state = "READY"
        return self.health()

    async def _pin(self, generation: int) -> Any:
        if generation in self._pins:
            return self._pins[generation]
        if self._generation_opener is None:
            self._pins[generation] = generation
            return generation
        task = self._opening.get(generation)
        if task is None:
            task = asyncio.create_task(self._generation_opener(generation))
            self._opening[generation] = task
        try:
            pin = await task
            self._pins[generation] = pin
            return pin
        finally:
            self._opening.pop(generation, None)

    async def submit(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._state != "READY":
            raise DaemonError("daemon_not_ready", self._state)
        request = DaemonRequest.parse(value)
        previous = self._terminal.get(request.request_id)
        if previous is not None:
            return dict(previous, replay=True)
        if request.request_id in self._active:
            raise DaemonError("request_already_active")
        if time.time_ns() >= request.deadline_ns:
            raise DaemonError("deadline_expired")
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        try:
            self._queue.put_nowait((request, future))
        except asyncio.QueueFull as exc:
            raise DaemonError("backpressure", "queue_capacity") from exc
        self._accepted += 1
        timeout = max(0.0, (request.deadline_ns - time.time_ns()) / 1_000_000_000)
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout)
        except asyncio.TimeoutError as exc:
            future.cancel()
            await self.cancel(request.request_id)
            raise DaemonError("deadline_expired") from exc

    async def _worker(self) -> None:
        while True:
            request, future = await self._queue.get()
            if future.cancelled():
                self._queue.task_done()
                continue
            task = asyncio.current_task()
            assert task is not None
            self._active[request.request_id] = task
            started = time.perf_counter_ns()
            try:
                await self._pin(request.generation)
                result = await self._handler(request)
                try:
                    result_payload = dict(result)
                    json.dumps(
                        result_payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                        allow_nan=False,
                    )
                except (TypeError, ValueError) as error:
                    raise DaemonError("protocol_result_invalid") from error
                unsigned = {
                    "schema": RESPONSE_SCHEMA,
                    "request_id": request.request_id,
                    "slot_id": request.slot_id,
                    "generation": request.generation,
                    "status": "COMPLETED",
                    "result": result_payload,
                    "daemon_epoch": self._epoch,
                    "backend": self._backend,
                    "backend_null_reason": self._rust_reason,
                    "latency_ns": time.perf_counter_ns() - started,
                    "completion_authority": "LOOP_ONLY",
                    "local_llm": False,
                }
                response = dict(unsigned, receipt_digest=_digest(unsigned))
                self._terminal[request.request_id] = response
                self._completed += 1
                if not future.done():
                    future.set_result(response)
            except asyncio.CancelledError:
                self._cancelled += 1
                if not future.done():
                    future.set_exception(DaemonError("request_cancelled"))
                raise
            except Exception as exc:
                if not future.done():
                    future.set_exception(exc)
            finally:
                self._active.pop(request.request_id, None)
                self._queue.task_done()

    async def cancel(self, request_id: str) -> bool:
        task = self._active.get(request_id)
        if task is not None:
            task.cancel()
            return True
        # A queued future is marked cancelled; workers skip it without invoking handler.
        for request, future in tuple(
            self._queue._queue
        ):  # bounded private queue, same loop
            if request.request_id == request_id and not future.done():
                future.set_exception(DaemonError("request_cancelled"))
                return True
        return False

    async def shutdown(self, *, drain: bool = True) -> Mapping[str, Any]:
        if self._state == "STOPPED":
            return self.health()
        self._state = "DRAINING"
        if drain:
            await self._queue.join()
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        for pin in tuple(self._pins.values()):
            if self._generation_closer is not None:
                await self._generation_closer(pin)
        self._pins.clear()
        self._state = "STOPPED"
        return self.health()

    async def crash(self) -> None:
        self._state = "CRASHED"
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        # No terminal response is fabricated for interrupted requests.
        self._active.clear()

    def health(self) -> dict[str, Any]:
        return {
            "schema": "simplicio.fast-daemon-health/v1",
            "state": self._state,
            "ready": self._state == "READY",
            "epoch": self._epoch,
            "backend": self._backend,
            "rust_null_reason": self._rust_reason,
            "capabilities": [
                "resident_snapshot",
                "bounded_multiplex",
                "cancel",
                "single_flight",
            ],
            "queue_depth": self._queue.qsize(),
            "queue_capacity": self._queue.maxsize,
            "inflight": len(self._active),
            "max_inflight": self._max_inflight,
            "pinned_generations": sorted(self._pins),
            "accepted": self._accepted,
            "completed": self._completed,
            "cancelled": self._cancelled,
            "local_llm": False,
        }


def make_request(
    request_id: str,
    slot_id: str,
    *,
    generation: int = 1,
    operation: str = "query",
    timeout_seconds: float = 5,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": PROTOCOL_SCHEMA,
        "request_id": request_id,
        "slot_id": slot_id,
        "operation": operation,
        "generation": generation,
        "deadline_ns": time.time_ns() + int(timeout_seconds * 1_000_000_000),
        "payload": dict(payload or {}),
    }
