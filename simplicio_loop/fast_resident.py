"""Run-scoped resident Fast service with a bounded Python fallback.

The service owns one warmed semantic generation for a repository/configuration.
Slots receive semantic results only; snapshot paths and internal offsets never
cross this boundary.
"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import inspect
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Protocol

from .fast_integration import FastConfig, FastIntegrationError, FastLoopIntegration

SCHEMA = "simplicio.loop-fast-resident/v1"
RECEIPT_SCHEMA = "simplicio.loop-fast-resident-receipt/v1"
_INTERNAL_KEYS = frozenset({"offset", "offsets", "byte_offset", "mmap_offset", "snapshot"})


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


async def _to_thread(function: Callable[..., Any], *args: Any) -> Any:
    """Python 3.8-compatible equivalent of ``asyncio.to_thread``."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(function, *args))


class FastServiceError(RuntimeError):
    """The resident service cannot safely satisfy a request."""


class FastServiceCrashed(FastServiceError):
    """The selected backend crashed before confirming a request."""


class Lifecycle(str, Enum):
    STARTING = "starting"
    READY = "ready"
    DRAINING = "draining"
    STOPPED = "stopped"
    CRASHED = "crashed"


class ResidentBackend(Protocol):
    engine: str

    async def start(self, task: str) -> Mapping[str, Any]: ...
    async def query(self, query: str, *, max_results: int) -> Mapping[str, Any]: ...
    async def close(self) -> None: ...


def _contains_internal(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(str(key).lower() in _INTERNAL_KEYS or _contains_internal(item)
                   for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_internal(item) for item in value)
    return False


def _semantic_result(payload: Mapping[str, Any], *, generation: str,
                     engine: str) -> dict[str, Any]:
    context = payload.get("context")
    rows = context if isinstance(context, list) else payload.get("results", [])
    if not isinstance(rows, list):
        rows = []
    safe: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        item = {key: value for key, value in row.items()
                if str(key).lower() not in _INTERNAL_KEYS}
        if _contains_internal(item):
            raise FastServiceError("Fast response exposed an internal snapshot offset")
        safe.append(item)
    result = {
        "schema": SCHEMA,
        "status": "READY",
        "generation": generation,
        "engine": engine,
        "results": safe,
    }
    result["result_hash"] = _hash(result)
    return result


class FastIntegrationBackend:
    """Async boundary over the installed Fast integration."""

    def __init__(self, integration: FastLoopIntegration) -> None:
        self.integration = integration
        self.engine = "unknown"
        self.generation = ""

    async def start(self, task: str) -> Mapping[str, Any]:
        prepared = await _to_thread(self.integration.prepare, task)
        if prepared.get("status") != "READY":
            raise FastServiceError(str(prepared.get("reason") or "Fast is not ready"))
        probe = self.integration.probe()
        self.engine = str(probe.get("selected_engine") or "python")
        self.generation = str(prepared.get("generation") or "")
        if not self.generation:
            raise FastServiceError("Fast omitted its generation")
        return {"generation": self.generation, "engine": self.engine,
                "prepared_receipt_hash": prepared.get("plan_hash")}

    async def query(self, query: str, *, max_results: int) -> Mapping[str, Any]:
        try:
            payload = await _to_thread(self.integration.understand, query)
        except FastIntegrationError as exc:
            raise FastServiceCrashed(str(exc)) from exc
        return _semantic_result(payload, generation=self.generation, engine=self.engine)

    async def close(self) -> None:
        return None


class PythonMemoryBackend:
    """Deterministic stdlib fallback that keeps one lexical index in memory."""

    engine = "python"

    def __init__(self, root: Path, *, max_file_bytes: int = 128_000) -> None:
        self.root = root
        self.max_file_bytes = max_file_bytes
        self._documents: tuple[tuple[str, str], ...] = ()
        self.generation = ""

    async def start(self, task: str) -> Mapping[str, Any]:
        del task
        documents: list[tuple[str, str]] = []
        ignored = {".git", ".simplicio-loop", "__pycache__", ".venv", "node_modules"}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or ignored.intersection(path.parts):
                continue
            try:
                if path.stat().st_size > self.max_file_bytes:
                    continue
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            documents.append((path.relative_to(self.root).as_posix(), content))
        self._documents = tuple(documents)
        identity = [(path, hashlib.sha256(text.encode("utf-8")).hexdigest())
                    for path, text in self._documents]
        self.generation = _hash(identity)
        return {"generation": self.generation, "engine": self.engine,
                "document_count": len(self._documents)}

    async def query(self, query: str, *, max_results: int) -> Mapping[str, Any]:
        terms = tuple(sorted({term.lower() for term in query.split() if term.strip()}))
        ranked: list[tuple[int, str, str]] = []
        for path, content in self._documents:
            haystack = (path + "\n" + content).lower()
            score = sum(haystack.count(term) for term in terms)
            if score:
                ranked.append((score, path, content[:2_000]))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        payload = {"results": [
            {"path": path, "score": score, "content": content}
            for score, path, content in ranked[:max_results]
        ]}
        return _semantic_result(payload, generation=self.generation, engine=self.engine)

    async def close(self) -> None:
        self._documents = ()


BackendFactory = Callable[[], ResidentBackend | Awaitable[ResidentBackend]]


@dataclass(frozen=True)
class ServiceKey:
    root: str
    config_hash: str


class FastResidentService:
    """One lifecycle and generation shared by all slots in a run."""

    def __init__(self, root: Path, backend_factory: BackendFactory, *,
                 fallback_factory: BackendFactory | None = None,
                 timeout_seconds: float = 30.0) -> None:
        self.root = root.resolve()
        self._backend_factory = backend_factory
        self._fallback_factory = fallback_factory or (lambda: PythonMemoryBackend(self.root))
        self.timeout_seconds = timeout_seconds
        self.lifecycle = Lifecycle.STOPPED
        self.backend: ResidentBackend | None = None
        self.generation = ""
        self.engine = ""
        self._start_lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Task[Mapping[str, Any]]] = {}
        self._confirmed: set[str] = set()
        self._task = ""
        self.metrics = {
            "cold_starts": 0, "warm_reuses": 0, "rebuilds": 0,
            "fallbacks": 0, "reconnects": 0, "timeouts": 0,
            "cancellations": 0, "queries": 0,
        }

    async def _new_backend(self, factory: BackendFactory) -> ResidentBackend:
        value = factory()
        return await value if inspect.isawaitable(value) else value

    async def start(self, task: str) -> dict[str, Any]:
        async with self._start_lock:
            if self.lifecycle == Lifecycle.READY:
                self.metrics["warm_reuses"] += 1
                return self.receipt("WARM")
            if self.lifecycle == Lifecycle.DRAINING:
                raise FastServiceError("service is draining")
            rebuilding = self.lifecycle == Lifecycle.CRASHED
            self.lifecycle = Lifecycle.STARTING
            self._task = task
            try:
                backend = await self._new_backend(self._backend_factory)
                started = await asyncio.wait_for(backend.start(task), self.timeout_seconds)
            except Exception:
                if "backend" in locals():
                    await backend.close()
                backend = await self._new_backend(self._fallback_factory)
                started = await asyncio.wait_for(backend.start(task), self.timeout_seconds)
                self.metrics["fallbacks"] += 1
            self.backend = backend
            self.generation = str(started.get("generation") or "")
            self.engine = str(started.get("engine") or backend.engine)
            if not self.generation:
                self.lifecycle = Lifecycle.CRASHED
                raise FastServiceError("resident backend omitted its generation")
            self.metrics["rebuilds" if rebuilding else "cold_starts"] += 1
            self.lifecycle = Lifecycle.READY
            return self.receipt("REBUILT" if rebuilding else "COLD")

    async def _execute(self, query: str, max_results: int) -> Mapping[str, Any]:
        if self.backend is None:
            raise FastServiceCrashed("resident backend is absent")
        return await self.backend.query(query, max_results=max_results)

    async def query(self, request_id: str, query: str, *,
                    max_results: int = 20) -> dict[str, Any]:
        if self.lifecycle != Lifecycle.READY:
            await self.start(self._task or query)
        if request_id in self._confirmed:
            raise FastServiceError("request_id was already confirmed")
        if request_id in self._inflight:
            result = await asyncio.shield(self._inflight[request_id])
            return dict(result)
        task = asyncio.create_task(self._execute(query, max_results))
        self._inflight[request_id] = task
        try:
            try:
                result = await asyncio.wait_for(asyncio.shield(task), self.timeout_seconds)
            except asyncio.TimeoutError:
                task.cancel()
                self.metrics["timeouts"] += 1
                raise
            except FastServiceCrashed:
                self.lifecycle = Lifecycle.CRASHED
                self.metrics["reconnects"] += 1
                await self.start(self._task or query)
                result = await asyncio.wait_for(self._execute(query, max_results), self.timeout_seconds)
            payload = dict(result)
            if _contains_internal(payload):
                raise FastServiceError("query response exposed an internal snapshot offset")
            self._confirmed.add(request_id)
            self.metrics["queries"] += 1
            payload["request_id"] = request_id
            payload["confirmed"] = True
            return payload
        except asyncio.CancelledError:
            task.cancel()
            self.metrics["cancellations"] += 1
            raise
        finally:
            self._inflight.pop(request_id, None)

    async def drain(self) -> dict[str, Any]:
        if self.lifecycle == Lifecycle.STOPPED:
            return self.receipt("STOPPED")
        self.lifecycle = Lifecycle.DRAINING
        if self._inflight:
            await asyncio.gather(*self._inflight.values(), return_exceptions=True)
        if self.backend is not None:
            await self.backend.close()
        self.backend = None
        self.lifecycle = Lifecycle.STOPPED
        return self.receipt("STOPPED")

    def receipt(self, status: str) -> dict[str, Any]:
        payload = {
            "schema": RECEIPT_SCHEMA,
            "status": status,
            "lifecycle": self.lifecycle.value,
            "root_hash": _hash(str(self.root)),
            "generation": self.generation or None,
            "engine": self.engine or None,
            "metrics": dict(self.metrics),
            "observability": {
                "rss_bytes": None,
                "rss_reason": "not measured by lifecycle contract; benchmark lane required",
                "latency_ms": None,
                "latency_reason": "not measured by lifecycle contract; benchmark lane required",
            },
            "internal_offsets_exposed": False,
        }
        payload["receipt_hash"] = _hash(payload)
        return payload


class FastServiceRegistry:
    """Run-owned registry: one service per resolved repo and Fast config."""

    def __init__(self) -> None:
        self._services: dict[ServiceKey, FastResidentService] = {}
        self._locks: dict[ServiceKey, asyncio.Lock] = {}

    async def acquire(self, root: str | Path, *, task: str,
                      config: FastConfig | None = None,
                      backend_factory: BackendFactory | None = None,
                      fallback_factory: BackendFactory | None = None,
                      timeout_seconds: float = 30.0) -> FastResidentService:
        resolved = Path(root).resolve()
        selected = config or FastConfig.from_env()
        key = ServiceKey(str(resolved), selected.digest())
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            service = self._services.get(key)
            if service is None:
                factory = backend_factory or (
                    lambda: FastIntegrationBackend(FastLoopIntegration(resolved, config=selected))
                )
                service = FastResidentService(
                    resolved, factory, fallback_factory=fallback_factory,
                    timeout_seconds=timeout_seconds,
                )
                self._services[key] = service
            await service.start(task)
            return service

    async def drain(self) -> list[dict[str, Any]]:
        receipts = await asyncio.gather(*(service.drain() for service in self._services.values()))
        return list(receipts)

    def status(self) -> list[dict[str, Any]]:
        return [service.receipt("STATUS") for service in self._services.values()]


__all__ = [
    "FastIntegrationBackend", "FastResidentService", "FastServiceCrashed",
    "FastServiceError", "FastServiceRegistry", "Lifecycle",
    "PythonMemoryBackend", "RECEIPT_SCHEMA", "SCHEMA",
]
