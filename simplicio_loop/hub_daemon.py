"""Singleton Hub lock and versioned in-process IPC contract."""

import json
import hashlib
import asyncio
import os
import socket
import signal
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Set, Tuple
import uuid

from .hub_queue_retry import HubRetryQueue, QueueRetryError
from .hub_scheduler import (
    FairScheduler, QuotaExceededError, ScheduledJob, SchedulerError, SchedulerPolicy,
)
from .process_enforcement import ProcessRegistry
from .process_supervisor import ProcessSpec, ProcessSpecError
from .process_supervisor import backend_name, run_sync
from .hub_governor import RESOURCE_NAMES, ResourceGovernor, ResourceLimits, ResourceRequest
from .hub_agent_executor import HubAgentExecutor, HubAgentError, parse_request
from .hub_service import ClaimedJob, HubService
from .hub_worker_store import HubWorkerError, HubWorkerStore
from .mapper_operations import MapperOperationsAdapter
from .map_service import MapServiceRegistry, RepositoryIdentity
from .map_service_single_flight import SingleFlightMapStore
from .map_service_watchers import MapWatcherManager
from .runtime_bridge import RUNTIME_CALL_SCHEMA, RuntimeBridge, RuntimeBridgeError


IPC_SCHEMA = "simplicio.hub-ipc/v1"
IPC_VERSION = 1
INTERACTIVE_SCHEMA = "simplicio.hub-interactive/v1"
INTERACTIVE_EVENT_SCHEMA = "simplicio.loop-hub-interactive-event/v1"
INTERACTIVE_JOURNAL_PREFIX = "simplicio.loop.hub-interactive:"
CODE_HUB_CLIENT_SCHEMA = "simplicio.loop-hub-client/v1"
CODE_HUB_PROTOCOL = "simplicio.loop-hub/v1"
METHODS = frozenset(
    (
        "register", "handshake", "attach", "replay", "submit", "claim", "heartbeat", "progress", "cancel", "resume", "result", "report",
        "execute", "ping", "claim_next", "scheduler_status", "scheduler_configure",
        # #503/#504/#505/#506 IPC wiring: expose the composed HubService (durable queue +
        # fair scheduler + resource governor) over the same envelope/dispatch contract as
        # the pre-existing in-memory job verbs above, rather than a second protocol.
        "hub_submit", "hub_claim", "hub_complete", "hub_fail", "hub_status",
        "hub_admit", "hub_admission",
        "hub_agent_capabilities", "hub_agent_claim", "hub_agent_status",
        "hub_agent_heartbeat", "hub_agent_progress", "hub_agent_send",
        "hub_agent_collect", "hub_agent_cancel",
        "worker_delegate", "worker_status", "worker_cancel", "worker_deliver", "runtime_execute", "runtime_call",
        # #512/#513 IPC wiring: expose the map service (registry + single-flight store +
        # watcher manager) the same way. Deliberately in-memory only, no persistence
        # layer (unlike hub_submit's durable queue) - a daemon restart starts clean; see
        # test_hub_daemon_map_ipc.py for the honest restart-boundary test.
        "map_register", "map_watch", "map_emit", "map_flush", "map_status", "map_gc",
    )
)


class HubError(RuntimeError):
    """Base Hub error."""


class HubAlreadyRunning(HubError):
    """Raised when another live process owns the singleton lock."""


class HubProtocolError(HubError):
    """Raised for invalid or unknown IPC envelopes."""


class HubBackpressureError(HubProtocolError):
    """Raised when a scheduler quota rejects a submission."""

    def __init__(self, quota_error: QuotaExceededError) -> None:
        self.signal = quota_error.to_backpressure_signal()
        super().__init__(str(quota_error))


class InteractiveStore:
    """Durable session journal projected from the Mapper operations journal."""

    def __init__(self, path: str, *, operations: Any | None = None) -> None:
        self.path = str(Path(path).expanduser().absolute())
        self._operations = operations or MapperOperationsAdapter(self.path)
        self._journal_id = INTERACTIVE_JOURNAL_PREFIX + self.path
        self._lock = threading.RLock()
        self._operations.initialize()

    def close(self) -> None:
        """Retain the old lifecycle hook; Mapper owns the underlying store."""

    @staticmethod
    def _last_seq(replay: Mapping[str, Any]) -> int:
        events = replay.get("events") or []
        if events:
            return int(events[-1]["seq"])
        compaction = replay.get("compaction")
        return int(compaction["through_seq"]) if compaction else 0

    def _replay(self) -> dict[str, Any]:
        replay = self._operations.replay(self._journal_id)
        if not replay.get("valid", False):
            raise HubProtocolError("interactive journal is invalid")
        return replay

    @staticmethod
    def _state(replay: Mapping[str, Any]) -> dict[str, Any]:
        state: dict[str, Any] = {"sessions": {}, "events": {}, "requests": {}}
        for journal_event in replay.get("events", []):
            payload = journal_event.get("payload")
            if not isinstance(payload, Mapping) or payload.get("schema") != INTERACTIVE_EVENT_SCHEMA:
                raise HubProtocolError("interactive journal contains an unknown event")
            operation = payload.get("operation")
            session_id = str(payload.get("session_id", ""))
            if operation == "session_attached":
                state["sessions"][session_id] = str(payload["client_id"])
            elif operation == "request_applied":
                event = dict(payload["event"])
                event["cursor"] = int(journal_event["seq"])
                state["events"].setdefault(session_id, []).append(event)
                state["requests"][(session_id, str(event["request_id"]))] = event
            else:
                raise HubProtocolError("interactive journal contains an unknown operation")
        return state

    @staticmethod
    def _is_conflict(error: BaseException) -> bool:
        return "JOURNAL_CONFLICT" in str(error) or getattr(error, "reason_code", "") == "JOURNAL_CONFLICT"

    def _append(self, replay: Mapping[str, Any], event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return self._operations.append_event(
                self._journal_id,
                event_type,
                {"schema": INTERACTIVE_EVENT_SCHEMA, **dict(payload)},
                expected_seq=self._last_seq(replay),
            )
        except Exception as error:
            if self._is_conflict(error):
                raise HubProtocolError("interactive journal changed concurrently") from error
            raise HubProtocolError("interactive journal append failed: " + str(error)) from error

    def attach(self, session_id: str, client_id: str) -> None:
        with self._lock:
            replay = self._replay()
            state = self._state(replay)
            owner = state["sessions"].get(session_id)
            if owner is not None and owner != client_id:
                raise HubProtocolError("session is owned by another client")
            if owner is None:
                self._append(replay, "hub-interactive.session-attached", {
                    "operation": "session_attached", "session_id": session_id,
                    "client_id": client_id, "created": time.time(),
                })

    def replay(self, session_id: str, cursor: int) -> Dict[str, Any]:
        if cursor < 0:
            raise HubProtocolError("cursor must be non-negative")
        with self._lock:
            state = self._state(self._replay())
            events = [
                {"cursor": event["cursor"], "request_id": event["request_id"],
                 "method": event["method"], "response": event["response"]}
                for event in state["events"].get(session_id, []) if event["cursor"] > cursor
            ]
        return {"events": events, "next_cursor": events[-1]["cursor"] if events else cursor}

    def apply(self, session_id: str, request_id: str, method: str, payload: Dict[str, Any], operation) -> Dict[str, Any]:
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self._lock:
            replay = self._replay()
            state = self._state(replay)
            existing = state["requests"].get((session_id, request_id))
            if existing is not None:
                if existing["method"] != method or existing["digest"] != digest:
                    raise HubProtocolError("conflicting idempotency request_id reuse")
                response = dict(existing["response"])
                response.update({"replayed": True, "cursor": existing["cursor"]})
                return response
            response = operation()
            base_response = dict(response)
            receipt = self._append(replay, "hub-interactive.request-applied", {
                "operation": "request_applied", "session_id": session_id,
                "event": {
                    "cursor": 0, "request_id": request_id, "method": method,
                    "digest": digest, "response": base_response, "created": time.time(),
                },
            })
            cursor = int(receipt["seq"])
            response.update({"replayed": False, "cursor": cursor})
            return response


def _pid_alive(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return pid == os.getpid()
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


class HubLock:
    """Exclusive PID lock with deterministic stale-lock reclamation."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._owned = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                descriptor = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump({"pid": os.getpid(), "schema": IPC_SCHEMA}, stream)
                self._owned = True
                return
            except FileExistsError:
                try:
                    payload = json.loads(self.path.read_text(encoding="utf-8"))
                    pid = int(payload.get("pid", 0))
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    pid = 0
                if _pid_alive(pid):
                    raise HubAlreadyRunning("Hub singleton is already owned")
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    continue

    def release(self) -> None:
        if not self._owned:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self._owned = False

    def __enter__(self) -> "HubLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()


@dataclass(frozen=True)
class HubEnvelope:
    """Versioned request envelope; payload is opaque to transport."""

    request_id: str
    method: str
    payload: Dict[str, Any]
    version: int = IPC_VERSION
    schema: str = IPC_SCHEMA

    def encode(self) -> str:
        if not self.request_id or self.method not in METHODS:
            raise HubProtocolError("request_id and known method are required")
        return json.dumps({
            "schema": self.schema,
            "version": self.version,
            "request_id": self.request_id,
            "method": self.method,
            "payload": self.payload,
        }, sort_keys=True)

    @classmethod
    def decode(cls, raw: str) -> "HubEnvelope":
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HubProtocolError("invalid JSON envelope") from exc
        if value.get("schema") != IPC_SCHEMA or value.get("version") != IPC_VERSION:
            raise HubProtocolError("unsupported IPC schema/version")
        if value.get("method") not in METHODS or not value.get("request_id"):
            raise HubProtocolError("invalid request envelope")
        payload = value.get("payload")
        if not isinstance(payload, dict):
            raise HubProtocolError("payload must be an object")
        return cls(str(value["request_id"]), str(value["method"]), dict(payload))


class HubDaemon:
    """In-process lifecycle coordinator behind a singleton lock."""

    def __init__(
        self,
        lock_path: str,
        queue_path: Optional[str] = None,
        scheduler: Optional[FairScheduler] = None,
        *,
        resource_limits: Optional[ResourceLimits] = None,
        process_registry: Optional[ProcessRegistry] = None,
        agent_executor: Optional[Any] = None,
        runtime_bridge: Optional[RuntimeBridge] = None,
    ) -> None:
        self.lock = HubLock(lock_path)
        self.started = False
        self.clients: Set[str] = set()
        self.jobs: Dict[str, Dict[str, Any]] = {}
        # Every ResourceLimits field defaults to 0, and ResourceGovernor treats a 0 limit
        # as "unbounded" (falsy) - so a HubDaemon constructed the same way as before this
        # change gets a HubService with no resource budget enforced by default, matching
        # prior behavior exactly unless the caller opts in with real limits.
        self._queue_path = queue_path or (lock_path + ".hub-queue.db")
        self._resource_limits = resource_limits or ResourceLimits()
        self.scheduler = scheduler if scheduler is not None else FairScheduler()
        self.process_registry = process_registry or ProcessRegistry()
        self.queue: Optional[HubRetryQueue] = None
        self._queue_lock = threading.RLock()
        self.service: Optional[HubService] = None
        self._claims: Dict[str, ClaimedJob] = {}
        # The #638 executor is injected at this boundary.  The daemon owns the
        # lifecycle; the coordinator-side client only speaks these IPC verbs.
        self.agent_executor = agent_executor
        # Runtime is a separately versioned effect authority. The Hub owns
        # only its lazy process lifecycle and transport; Code never starts it.
        self.runtime_bridge = runtime_bridge or RuntimeBridge()
        self.hub_agent: Optional[HubAgentExecutor] = None
        self.worker_store: Optional[HubWorkerStore] = None
        self._agent_jobs: Dict[str, Dict[str, Any]] = {}
        # #512/#513: registry/store/watchers are pure in-memory (unlike the durable
        # queue above) - rebuilt fresh every start(), never persisted across stop().
        self.map_registry: Optional[MapServiceRegistry] = None
        self.map_store: Optional[SingleFlightMapStore] = None
        self.map_watchers: Optional[MapWatcherManager] = None
        self._map_watch_tokens: Dict[str, str] = {}
        self.interactive: Optional[InteractiveStore] = None
        self.epoch = ""

    def start(self) -> None:
        if self.started:
            return
        self.lock.acquire()
        queue = HubRetryQueue(self._queue_path)
        self.queue = queue
        self.interactive = InteractiveStore(self._queue_path + ".interactive.db")
        self.epoch = uuid.uuid4().hex
        governor = ResourceGovernor(self._resource_limits)
        manifest = queue.scheduler_manifest()
        if manifest is not None:
            try:
                self.scheduler.configure_policy(SchedulerPolicy(
                    mode=str(manifest.get("mode") or ""),
                    version=str(manifest.get("version") or ""),
                    previous_version=str(manifest.get("previous_version") or ""),
                    canary_percent=int(manifest.get("canary_percent", 0)),
                ))
            except (SchedulerError, TypeError, ValueError) as exc:
                queue.close()
                self.queue = None
                raise HubError("persisted scheduler policy is invalid: %s" % exc) from exc
        self.service = HubService(queue, self.scheduler, governor)
        # The Hub owns one durable executor.  Coordinator clients only use IPC;
        # direct callers receive the same authority for local conformance tests.
        self.hub_agent = HubAgentExecutor(self._queue_path + ".agent.db", governor)
        self.worker_store = HubWorkerStore(self._queue_path + ".workers.db")
        # #503-506 restart persistence: the durable queue never lost still-queued
        # jobs across this restart - re-admit their real scheduling metadata into
        # the freshly built (empty) FairScheduler now, rather than leaving them
        # durably present but invisible to fairness ordering until re-submitted.
        self.service.rehydrate_scheduler()
        self.map_registry = MapServiceRegistry()
        self.map_store = SingleFlightMapStore(self.map_registry)
        self.map_watchers = MapWatcherManager(self.map_registry, self.map_store)
        self.started = True

    def stop(self) -> None:
        # An active agent is not redispatched after a Hub epoch ends.  Preserve
        # its handle and make the uncertainty explicit for reconnect/collect.
        for job in self._agent_jobs.values():
            if job.get("state") == "running":
                job["state"] = "recovery_unknown"
        self.jobs.clear()
        self.clients.clear()
        self._claims.clear()
        if self.hub_agent is not None:
            self.hub_agent.close()
            self.hub_agent = None
        if self.runtime_bridge is not None:
            self.runtime_bridge.close()
        if self.worker_store is not None:
            self.worker_store.close()
            self.worker_store = None
        if self.queue is not None:
            self.queue.close()
            self.queue = None
        if self.interactive is not None:
            self.interactive.close()
            self.interactive = None
        self.service = None
        if self.map_watchers is not None:
            self.map_watchers.close()
        self.map_registry = None
        self.map_store = None
        self.map_watchers = None
        self._map_watch_tokens.clear()
        self.started = False
        self.lock.release()

    @staticmethod
    def _agent_handle_id(handle: Any) -> str:
        if isinstance(handle, str) and handle:
            return handle
        if not isinstance(handle, dict):
            raise HubProtocolError("agent handle must be an object")
        value = handle.get("handle_id") or handle.get("lease_id") or handle.get("job_id")
        if not value:
            raise HubProtocolError("agent handle id is required")
        return str(value)

    def _agent_job(self, envelope: HubEnvelope) -> Dict[str, Any]:
        handle = envelope.payload.get("handle")
        job_id = self._agent_handle_id(handle)
        job = self._agent_jobs.get(job_id)
        if job is None and self.hub_agent is not None:
            try:
                execution = self.hub_agent.status(job_id)
            except HubAgentError:
                execution = None
            if execution is not None:
                job = {
                    "client_id": "", "worker_id": "", "idempotency_key": "",
                    "handle": {"handle_id": job_id, "lease_id": job_id, "job_id": job_id,
                                "generation": 1, "fence": execution["fence"]},
                    "state": execution["state"], "progress": 0.0,
                    "heartbeat_at": execution.get("heartbeat_at"),
                    "stage_input": None, "result": execution.get("result"),
                    "execution": True, "executor_handle": job_id,
                }
                self._agent_jobs[job_id] = job
        if job is None:
            raise HubProtocolError("unknown hub agent handle")
        supplied_fence = str((handle or {}).get("fence") or "") if isinstance(handle, dict) else ""
        if not supplied_fence:
            supplied_fence = str(envelope.payload.get("fence") or "")
        if supplied_fence and supplied_fence != str(job["handle"].get("fence")):
            error = HubProtocolError("stale fence for hub agent handle")
            error.reason_code = "stale_fence"
            raise error
        supplied_generation = (handle or {}).get("generation")
        try:
            generation_mismatch = supplied_generation is not None and int(supplied_generation) != int(job["handle"].get("generation", 0))
        except (TypeError, ValueError):
            generation_mismatch = True
        if generation_mismatch:
            error = HubProtocolError("stale generation for hub agent handle")
            error.reason_code = "stale_fence"
            raise error
        return job

    def _handle_agent_ipc(self, envelope: HubEnvelope) -> Dict[str, Any]:
        """Serve the versioned agent lifecycle without exposing legacy execute."""
        payload = envelope.payload
        if envelope.method == "hub_agent_capabilities":
            return {"ok": True, "schema": "simplicio.hub-agent-capabilities/v1", "capabilities": ["hub-agent-process/v1"]}
        if envelope.method == "hub_agent_claim":
            client_id = str(payload.get("client_id") or "")
            worker_id = str(payload.get("worker_id") or "")
            idempotency_key = str(payload.get("idempotency_key") or "")
            if not client_id or not worker_id or not idempotency_key:
                raise HubProtocolError("client_id, worker_id and idempotency_key are required")
            for existing in self._agent_jobs.values():
                if existing.get("idempotency_key") == idempotency_key and existing.get("client_id") == client_id:
                    return {"ok": True, "handle": dict(existing["handle"]), "replayed": True}
            digest = hashlib.sha256(f"{client_id}:{idempotency_key}".encode("utf-8")).hexdigest()
            job_id = "hub-agent-" + digest[:24]
            handle = {
                "schema": "simplicio.hub-agent-handle/v1",
                "job_id": job_id,
                "lease_id": job_id,
                "handle_id": job_id,
                "generation": 1,
                "fence": "fence-" + digest[24:40],
                "idempotency_key": idempotency_key,
                "client_id": client_id,
                "worker_id": worker_id,
            }
            process_spec = payload.get("process_spec")
            if process_spec is not None:
                if self.hub_agent is None or not isinstance(process_spec, dict):
                    raise HubProtocolError("Hub agent executor is unavailable")
                try:
                    spec = ProcessSpec(
                        argv=tuple(process_spec.get("argv", ())),
                        cwd=process_spec.get("cwd"),
                        cwd_allowlist=tuple(process_spec.get("cwd_allowlist", ())),
                        env=dict(process_spec.get("env", {})),
                        env_allowlist=tuple(process_spec.get("env_allowlist", ())),
                        timeout_seconds=process_spec.get("timeout_seconds", 30.0),
                        max_output_bytes=int(process_spec.get("max_output_bytes", 65536)),
                        priority=int(process_spec.get("priority", 0)),
                        idempotency_key=idempotency_key,
                        shell=bool(process_spec.get("shell", False)),
                    )
                    execution = self.hub_agent.claim(
                        spec, parse_request(dict(payload.get("request") or {})),
                        idempotency_key=idempotency_key,
                    )
                except (HubAgentError, TypeError, ValueError) as exc:
                    raise HubProtocolError("hub agent claim blocked: %s" % exc) from exc
                handle = {
                    "schema": "simplicio.hub-agent-handle/v1",
                    "job_id": execution["handle"], "lease_id": execution["handle"],
                    "handle_id": execution["handle"], "generation": 1,
                    "fence": execution["fence"], "idempotency_key": idempotency_key,
                    "client_id": client_id, "worker_id": worker_id,
                }
            storage_id = str(handle["handle_id"])
            self._agent_jobs[storage_id] = {
                "client_id": client_id, "worker_id": worker_id, "idempotency_key": idempotency_key,
                "handle": handle, "state": "ready", "progress": 0.0,
                "heartbeat_at": time.time(), "stage_input": None, "result": None,
                "request": dict(payload),
                "executor_handle": execution["handle"] if process_spec is not None else None,
                "execution": process_spec is not None,
            }
            return {"ok": True, "handle": dict(handle), "replayed": False}
        if envelope.method == "hub_agent_status":
            job = self._agent_job(envelope)
            if job.get("execution") and self.hub_agent is not None:
                execution = self.hub_agent.status(job["handle"]["handle_id"])
                job["state"] = execution["state"]
                job["result"] = execution.get("result")
                if execution.get("fence") is not None:
                    job["handle"]["fence"] = execution["fence"]
                return {"ok": True, "execution": execution}
            return {"ok": True, "status": {"state": job["state"], "status": job["state"],
                                              "progress": job["progress"], "heartbeat_at": job["heartbeat_at"],
                                              "handle": dict(job["handle"])}}
        if envelope.method == "hub_agent_heartbeat":
            job = self._agent_job(envelope)
            job["heartbeat_at"] = time.time()
            return {"ok": True, "heartbeat_at": job["heartbeat_at"]}
        if envelope.method == "hub_agent_progress":
            job = self._agent_job(envelope)
            progress = float(payload.get("progress", -1))
            if not 0 <= progress <= 100:
                raise HubProtocolError("progress must be between 0 and 100")
            job["progress"] = progress
            job["heartbeat_at"] = time.time()
            return {"ok": True, "progress": progress}
        if envelope.method == "hub_agent_send":
            job = self._agent_job(envelope)
            if job["state"] not in ("ready", "running"):
                raise HubProtocolError("hub agent is not sendable")
            stage_input = payload.get("stage_input")
            if not isinstance(stage_input, dict):
                raise HubProtocolError("stage_input must be an object")
            job["stage_input"] = dict(stage_input)
            job["state"] = "running"
            job["heartbeat_at"] = time.time()
            if job.get("executor_handle") and self.hub_agent is not None:
                try:
                    execution = self.hub_agent.send(job["executor_handle"], int(job["handle"]["fence"]))
                except (HubAgentError, TypeError, ValueError) as exc:
                    raise HubProtocolError("hub agent send blocked: %s" % exc) from exc
                job["state"] = execution["state"]
                job["result"] = execution.get("result")
                if execution.get("fence") is not None:
                    job["handle"]["fence"] = execution["fence"]
                return {"ok": True, "execution": execution, "handle": dict(job["handle"])}
            if self.agent_executor is not None:
                try:
                    outcome = self.agent_executor({"job": dict(job), "stage_input": dict(stage_input)})
                    if outcome is not None:
                        job["result"] = dict(outcome) if isinstance(outcome, dict) else {"output": outcome}
                        verdict = str((job["result"].get("receipt") or {}).get("verdict") or "")
                        job["state"] = str(job["result"].get("status") or ("passed" if verdict == "pass" else "failed"))
                except Exception as exc:
                    job["state"] = "failed"
                    job["result"] = {"output": None, "receipt": None,
                                      "process_result": {"error_code": "agent_executor_error", "error": str(exc)}}
            return {"ok": True, "state": job["state"], "handle": dict(job["handle"])}
        if envelope.method == "hub_agent_collect":
            job = self._agent_job(envelope)
            if job.get("execution") and self.hub_agent is not None:
                try:
                    execution = self.hub_agent.collect(job["handle"]["handle_id"])
                except HubAgentError as exc:
                    if "not terminal" in str(exc):
                        return {"ok": True, "execution": self.hub_agent.status(job["handle"]["handle_id"])}
                    raise HubProtocolError(str(exc)) from exc
                if execution.get("fence") is not None:
                    job["handle"]["fence"] = execution["fence"]
                return {"ok": True, "execution": execution, "handle": dict(job["handle"])}
            if job["state"] not in ("passed", "failed", "blocked", "cancelled", "timed_out", "recovery_unknown"):
                return {"ok": True, "state": job["state"], "result": None}
            return {"ok": True, "state": job["state"], "result": dict(job.get("result") or {}),
                    "handle": dict(job["handle"])}
        if envelope.method == "hub_agent_cancel":
            job = self._agent_job(envelope)
            if job.get("executor_handle") and self.hub_agent is not None:
                try:
                    execution = self.hub_agent.cancel(job["executor_handle"], int(job["handle"]["fence"]))
                except (HubAgentError, TypeError, ValueError) as exc:
                    raise HubProtocolError("hub agent cancel blocked: %s" % exc) from exc
                job["state"] = execution["state"]
                job["result"] = execution.get("result")
                if execution.get("fence") is not None:
                    job["handle"]["fence"] = execution["fence"]
                return {"ok": True, "execution": execution, "handle": dict(job["handle"])}
            if job["state"] not in ("passed", "failed", "blocked", "cancelled", "timed_out", "recovery_unknown"):
                job["state"] = "cancelled"
                job["result"] = {"output": None, "receipt": None,
                                  "process_result": {"cancelled": True, "error_code": str(payload.get("reason") or "cancelled")}}
            return {"ok": True, "state": job["state"], "handle": dict(job["handle"])}
        raise HubProtocolError("unknown hub agent method")

    def handle(self, envelope: HubEnvelope) -> Dict[str, Any]:
        if not self.started:
            raise HubError("Hub is not started")
        if envelope.method == "handshake":
            requested = envelope.payload.get("schemas", [INTERACTIVE_SCHEMA])
            if not isinstance(requested, list) or INTERACTIVE_SCHEMA not in requested:
                raise HubProtocolError("unsupported interactive schema/version")
            client_id = str(envelope.payload.get("client_id") or "")
            if not client_id:
                raise HubProtocolError("client_id is required")
            return {"ok": True, "schema": INTERACTIVE_SCHEMA, "version": 1,
                    "epoch": self.epoch, "capabilities": ["attach", "replay", "idempotent-lifecycle",
                    "fair-queue", "shared-runtime-map"]}
        if envelope.method in {"attach", "replay"}:
            assert self.interactive is not None
            client_id = str(envelope.payload.get("client_id") or "")
            session_id = str(envelope.payload.get("session_id") or "")
            if not client_id or not session_id:
                raise HubProtocolError("client_id and session_id are required")
            supplied_epoch = str(envelope.payload.get("epoch") or "")
            if supplied_epoch and supplied_epoch != self.epoch:
                # Reconnect after restart is allowed only when the client explicitly
                # acknowledges the new handshake instead of silently reusing handles.
                raise HubProtocolError("stale daemon epoch; handshake again")
            self.interactive.attach(session_id, client_id)
            delta = self.interactive.replay(session_id, int(envelope.payload.get("cursor", 0)))
            return {"ok": True, "schema": INTERACTIVE_SCHEMA, "epoch": self.epoch,
                    "session_id": session_id,
                    "runtime_handle": {"schema": "simplicio.runtime-handle/v1", "id": session_id,
                                       "epoch": self.epoch},
                    "map_handle": {"schema": "simplicio.map-handle/v1", "id": session_id,
                                   "epoch": self.epoch}, **delta}
        if envelope.method in {"submit", "cancel", "resume"} and envelope.payload.get("session_id"):
            assert self.interactive is not None
            session_id = str(envelope.payload["session_id"])
            client_id = str(envelope.payload.get("client_id") or "")
            self.interactive.attach(session_id, client_id)
            payload = dict(envelope.payload)
            payload.pop("session_id", None)
            if envelope.method == "resume":
                delegated_method = "resume"
            else:
                delegated_method = envelope.method
            def operation() -> Dict[str, Any]:
                if delegated_method == "resume":
                    job_id = str(payload.get("job_id") or "")
                    task_id = self.queue.find_task_id(job_id)
                    if task_id is None:
                        raise HubProtocolError("unknown job")
                    job = dict(self.queue.get_row(task_id)["payload"])
                    if job.get("state") not in {"cancelled", "failed", "blocked"}:
                        raise HubProtocolError("job is not resumable")
                    job["state"] = "queued"
                    job["progress"] = 0
                    self.queue.update_payload(task_id, job)
                    self.scheduler.enqueue(ScheduledJob(task_id=job_id,
                        client_id=str(job.get("client_id") or client_id)))
                    return {"ok": True, "job": job}
                return self.handle(HubEnvelope(envelope.request_id + ":apply", delegated_method, payload))
            return self.interactive.apply(session_id, envelope.request_id, envelope.method,
                                          envelope.payload, operation)
        if envelope.method == "ping":
            return {
                "ok": True, "started": self.started, "clients": len(self.clients),
                "jobs": self.queue.count() if self.queue is not None else 0,
            }
        if envelope.method == "scheduler_status":
            return {"ok": True, "scheduler": self.scheduler.status()}
        if envelope.method == "scheduler_configure":
            try:
                policy = SchedulerPolicy(
                    mode=str(envelope.payload.get("mode") or ""),
                    version=str(envelope.payload.get("version") or ""),
                    previous_version=str(envelope.payload.get("previous_version") or ""),
                    canary_percent=int(envelope.payload.get("canary_percent", 0)),
                )
                receipt = self.scheduler.configure_policy(policy)
                self.queue.set_scheduler_manifest(policy.to_manifest())
            except (SchedulerError, QueueRetryError, TypeError, ValueError) as exc:
                raise HubProtocolError("scheduler configuration rejected: %s" % exc) from exc
            return {"ok": True, "receipt": receipt}
        if envelope.method == "claim_next":
            worker_id = str(envelope.payload.get("client_id") or "worker")
            with self._queue_lock:
                return {"ok": True, "job": self._claim_next_locked(worker_id)}
        if envelope.method == "hub_submit":
            payload = envelope.payload.get("payload")
            if not isinstance(payload, dict):
                raise HubProtocolError("payload must be an object")
            idempotency_key = str(envelope.payload.get("idempotency_key") or "")
            client_id = str(envelope.payload.get("client_id") or "")
            if not idempotency_key or not client_id:
                raise HubProtocolError("idempotency_key and client_id are required")
            task_id = self.service.submit(
                payload,
                idempotency_key=idempotency_key,
                client_id=client_id,
                workspace_id=str(envelope.payload.get("workspace_id") or "default"),
                weight=int(envelope.payload.get("weight", 1)),
                cost=int(envelope.payload.get("cost", 1)),
                max_attempts=int(envelope.payload.get("max_attempts", 3)),
            )
            return {"ok": True, "task_id": task_id}
        if envelope.method == "hub_claim":
            worker_id = str(envelope.payload.get("worker_id") or "")
            if not worker_id:
                raise HubProtocolError("worker_id is required")
            raw_request = envelope.payload.get("request") or {}
            if not isinstance(raw_request, dict) or set(raw_request) - set(RESOURCE_NAMES):
                raise HubProtocolError("request must contain only known resource fields")
            request = ResourceRequest(**{name: int(raw_request.get(name, 0)) for name in RESOURCE_NAMES})
            claimed = self.service.claim(
                worker_id, request,
                ttl=float(envelope.payload.get("ttl", 30.0)),
                max_candidates=int(envelope.payload.get("max_candidates", 8)),
            )
            if claimed is None:
                return {"ok": True, "claimed": None}
            # RetryLease/ResourceLease are kept server-side, keyed by task_id, rather than
            # round-tripped over the wire - the client only needs task_id to complete/fail.
            self._claims[claimed.task_id] = claimed
            return {
                "ok": True,
                "claimed": {
                    "task_id": claimed.task_id, "client_id": claimed.client_id,
                    "workspace_id": claimed.workspace_id, "payload": claimed.payload,
                },
            }
        if envelope.method == "hub_complete":
            task_id = str(envelope.payload.get("task_id") or "")
            claimed = self._claims.pop(task_id, None)
            if claimed is None:
                raise HubProtocolError("no active claim for task_id")
            self.service.complete(claimed)
            return {"ok": True, "task_id": task_id}
        if envelope.method == "hub_fail":
            task_id = str(envelope.payload.get("task_id") or "")
            claimed = self._claims.pop(task_id, None)
            if claimed is None:
                raise HubProtocolError("no active claim for task_id")
            outcome = self.service.fail(
                claimed,
                error_code=str(envelope.payload.get("error_code") or "unknown"),
                backoff=float(envelope.payload.get("backoff", 0.0)),
            )
            return {"ok": True, "task_id": task_id, "outcome": outcome}
        if envelope.method == "hub_status":
            return {"ok": True, "status": self.service.status()}
        if envelope.method == "hub_admit":
            job = envelope.payload.get("job")
            if not isinstance(job, dict):
                raise HubProtocolError("job projection must be an object")
            try:
                with self._queue_lock:
                    receipt = self.service.admit_held(
                        job,
                        idempotency_key=envelope.payload.get("idempotency_key"),
                        input_digest=envelope.payload.get("input_digest"),
                        client_id=envelope.payload.get("client_id"),
                        workspace_id=envelope.payload.get("workspace_id", "default"),
                        weight=envelope.payload.get("weight", 1),
                        cost=envelope.payload.get("cost", 1),
                    )
            except (QueueRetryError, TypeError, ValueError) as exc:
                raise HubProtocolError("hub_admit blocked: %s" % exc) from exc
            return {"ok": True, "admission": receipt}
        if envelope.method == "hub_admission":
            task_id = str(envelope.payload.get("task_id") or "")
            idempotency_key = str(envelope.payload.get("idempotency_key") or "")
            try:
                receipt = self.service.admission(
                    task_id=task_id, idempotency_key=idempotency_key,
                )
            except QueueRetryError as exc:
                raise HubProtocolError("hub_admission blocked: %s" % exc) from exc
            return {"ok": True, "admission": receipt}
        if envelope.method.startswith("worker_"):
            if self.worker_store is None:
                raise HubError("worker store is not started")
            try:
                operation = getattr(self.worker_store, envelope.method.removeprefix("worker_"))
                return {"ok": True, envelope.method.removeprefix("worker_"): operation(envelope.payload)}
            except HubWorkerError as exc:
                raise HubProtocolError(str(exc)) from exc
        if envelope.method.startswith("hub_agent_"):
            return self._handle_agent_ipc(envelope)
        if envelope.method == "map_register":
            fields = {
                name: envelope.payload.get(name)
                for name in (
                    "repository", "canonical_root", "default_branch", "worktree_root",
                    "base_sha", "dirty", "dirty_fingerprint", "mapper_config",
                )
                if envelope.payload.get(name) is not None
            }
            try:
                identity = RepositoryIdentity(**fields)
            except TypeError as exc:
                raise HubProtocolError("invalid map_register payload: %s" % exc) from exc
            try:
                identity_key = self.map_registry.register(identity)
            except Exception as exc:  # MapServiceError subclasses
                raise HubProtocolError("map_register failed: %s" % exc) from exc
            return {"ok": True, "identity_key": identity_key}
        if envelope.method == "map_watch":
            identity_key = str(envelope.payload.get("identity_key") or "")
            if not identity_key:
                raise HubProtocolError("identity_key is required")
            try:
                token = self.map_watchers.watch(
                    identity_key, lambda _event: None,
                    debounce_seconds=float(envelope.payload.get("debounce_seconds", 0.05)),
                )
            except Exception as exc:
                raise HubProtocolError("map_watch failed: %s" % exc) from exc
            self._map_watch_tokens[identity_key] = token
            return {"ok": True, "token": token}
        if envelope.method == "map_emit":
            identity_key = str(envelope.payload.get("identity_key") or "")
            paths = envelope.payload.get("paths") or []
            if not identity_key or not isinstance(paths, list):
                raise HubProtocolError("identity_key and a paths list are required")
            try:
                self.map_watchers.emit(identity_key, paths)
            except Exception as exc:
                raise HubProtocolError("map_emit failed: %s" % exc) from exc
            return {"ok": True}
        if envelope.method == "map_flush":
            fired = self.map_watchers.flush(force=bool(envelope.payload.get("force", False)))
            return {"ok": True, "fired": fired}
        if envelope.method == "map_status":
            return {"ok": True, "status": self.map_watchers.status()}
        if envelope.method == "map_gc":
            return {"ok": True, "removed": self.map_watchers.gc()}
        if envelope.method == "register":
            client_id = str(envelope.payload.get("client_id") or "")
            if not client_id:
                raise HubProtocolError("client_id is required")
            self.clients.add(client_id)
            return {"ok": True, "client_id": client_id, "state": "registered"}
        # Legacy job verbs are backed by the same durable queue and scheduler as
        # the composed HubService. This keeps the old IPC contract while removing
        # the split in-memory/durable state that caused the merge conflict.
        if envelope.method == "execute":
            raw_spec = envelope.payload.get("process_spec")
            if not isinstance(raw_spec, dict):
                raise HubProtocolError("process_spec must be an object")
            allowed = {
                "argv", "cwd", "cwd_allowlist", "env", "env_allowlist",
                "timeout_seconds", "max_output_bytes", "priority",
                "idempotency_key", "shell",
            }
            unknown = sorted(set(raw_spec) - allowed - {"schema", "spec_hash"})
            if unknown:
                raise HubProtocolError("unknown ProcessSpec fields: " + ", ".join(unknown))
            if raw_spec.get("schema") not in (None, "simplicio.process-spec/v1"):
                raise HubProtocolError("unsupported ProcessSpec schema")
            try:
                spec = ProcessSpec(
                    argv=tuple(raw_spec.get("argv", ())),
                    cwd=raw_spec.get("cwd"),
                    cwd_allowlist=tuple(raw_spec.get("cwd_allowlist", ())),
                    env=dict(raw_spec.get("env", {})),
                    env_allowlist=tuple(raw_spec.get("env_allowlist", ())),
                    timeout_seconds=raw_spec.get("timeout_seconds", 30.0),
                    max_output_bytes=int(raw_spec.get("max_output_bytes", 65536)),
                    priority=int(raw_spec.get("priority", 0)),
                    idempotency_key=str(raw_spec.get("idempotency_key", "")),
                    shell=bool(raw_spec.get("shell", False)),
                )
            except (TypeError, ValueError, ProcessSpecError) as exc:
                raise HubProtocolError(f"invalid ProcessSpec: {exc}") from exc
            registered: Dict[str, int] = {}

            def on_spawned(process: Any) -> None:
                registered["pid"] = process.pid
                self.process_registry.register(
                    process.pid,
                    lease_id=spec.idempotency_key or f"hub-execute-{envelope.request_id}",
                    spec_hash=spec.spec_hash,
                    argv=spec.argv,
                )

            lease_id = spec.idempotency_key or f"hub-execute-{envelope.request_id}"
            try:
                result = run_sync(spec, on_spawned=on_spawned)
            except (OSError, RuntimeError, asyncio.CancelledError) as exc:
                raise HubError(f"supervisor execution failed: {exc}") from exc
            finally:
                if "pid" in registered:
                    self.process_registry.unregister(registered["pid"])
            return {
                "ok": True, "backend": backend_name(), "result": result.to_dict(),
                "lease_id": lease_id,
            }
        if envelope.method == "cancel":
            lease_id = str(envelope.payload.get("lease_id") or "")
            process_cancel = self.process_registry.terminate(lease_id) if lease_id else None
            job_id = str(envelope.payload.get("job_id") or "")
            if not job_id:
                if process_cancel is None:
                    raise HubProtocolError("job_id or lease_id is required")
                return {"ok": True, "process": process_cancel}
            with self._queue_lock:
                task_id = self.queue.find_task_id(job_id)
                if task_id is None:
                    raise HubProtocolError("unknown job")
                row = self.queue.get_row(task_id)
                job = dict(row["payload"])
                job["state"] = "cancelled"
                self.scheduler.cancel(job_id)
                self.queue.update_payload(task_id, job)
            response = {"ok": True, "job": dict(job)}
            if process_cancel is not None:
                response["process"] = process_cancel
            return response
        job_id = str(envelope.payload.get("job_id") or "")
        if not job_id:
            raise HubProtocolError("job_id is required")
        with self._queue_lock:
            if envelope.method == "submit":
                if self.queue.find_task_id(job_id) is not None:
                    raise HubProtocolError("job already exists")
                metadata = envelope.payload.get("metadata", {})
                if not isinstance(metadata, dict):
                    raise HubProtocolError("metadata must be an object")
                client_id = str(envelope.payload.get("client_id") or "")
                job = {
                    "job_id": job_id, "client_id": client_id, "state": "queued",
                    "progress": 0, "result": None,
                }
                try:
                    self.scheduler.enqueue(ScheduledJob(
                        task_id=job_id, client_id=client_id,
                        weight=int(envelope.payload.get("weight", 1)),
                        cost=int(envelope.payload.get("cost", 1)),
                        workspace_id=str(envelope.payload.get("workspace_id") or "default"),
                        priority=str(envelope.payload.get("priority") or "background"),
                    ))
                except QuotaExceededError as exc:
                    raise HubBackpressureError(exc) from exc
                except SchedulerError as exc:
                    raise HubProtocolError(str(exc)) from exc
                try:
                    self.queue.submit(
                        job, idempotency_key=job_id,
                        client_id=client_id,
                        workspace_id=str(envelope.payload.get("workspace_id") or "default"),
                        weight=int(envelope.payload.get("weight", 1)),
                        cost=int(envelope.payload.get("cost", 1)),
                    )
                except Exception:
                    self.scheduler.cancel(job_id)
                    raise
                return {"ok": True, "job": dict(job)}
            task_id = self.queue.find_task_id(job_id)
            if task_id is None:
                raise HubProtocolError("unknown job")
            row = self.queue.get_row(task_id)
            job = dict(row["payload"])
            if envelope.method == "claim":
                if job["state"] != "queued":
                    raise HubProtocolError("job is not claimable")
                job["state"] = "claimed"
            elif envelope.method == "heartbeat":
                if job["state"] not in ("claimed", "running"):
                    raise HubProtocolError("job has no active lease")
            elif envelope.method == "progress":
                progress = int(envelope.payload.get("progress", -1))
                if not 0 <= progress <= 100:
                    raise HubProtocolError("progress must be between 0 and 100")
                job["progress"] = progress
                job["state"] = "running"
            elif envelope.method == "result":
                job["result"] = envelope.payload.get("result")
                job["state"] = "completed"
                try:
                    self.scheduler.complete(job_id)
                except SchedulerError:
                    pass
            elif envelope.method == "report":
                return {"ok": True, "job": dict(job), "clients": sorted(self.clients)}
            self.queue.update_payload(task_id, job)
            return {"ok": True, "job": dict(job)}
        if envelope.method == "register":
            client_id = str(envelope.payload.get("client_id") or "")
            if not client_id:
                raise HubProtocolError("client_id is required")
            self.clients.add(client_id)
            return {"ok": True, "client_id": client_id, "state": "registered"}
        if envelope.method == "execute":
            raw_spec = envelope.payload.get("process_spec")
            if not isinstance(raw_spec, dict):
                raise HubProtocolError("process_spec must be an object")
            allowed = {
                "argv", "cwd", "cwd_allowlist", "env", "env_allowlist",
                "timeout_seconds", "max_output_bytes", "priority",
                "idempotency_key", "shell",
            }
            unknown = sorted(set(raw_spec) - allowed - {"schema", "spec_hash"})
            if unknown:
                raise HubProtocolError("unknown ProcessSpec fields: " + ", ".join(unknown))
            if raw_spec.get("schema") not in (None, "simplicio.process-spec/v1"):
                raise HubProtocolError("unsupported ProcessSpec schema")
            try:
                spec = ProcessSpec(
                    argv=tuple(raw_spec.get("argv", ())),
                    cwd=raw_spec.get("cwd"),
                    cwd_allowlist=tuple(raw_spec.get("cwd_allowlist", ())),
                    env=dict(raw_spec.get("env", {})),
                    env_allowlist=tuple(raw_spec.get("env_allowlist", ())),
                    timeout_seconds=raw_spec.get("timeout_seconds", 30.0),
                    max_output_bytes=int(raw_spec.get("max_output_bytes", 65536)),
                    priority=int(raw_spec.get("priority", 0)),
                    idempotency_key=str(raw_spec.get("idempotency_key", "")),
                    shell=bool(raw_spec.get("shell", False)),
                )
            except (TypeError, ValueError, ProcessSpecError) as exc:
                raise HubProtocolError(f"invalid ProcessSpec: {exc}") from exc
            try:
                result = run_sync(spec)
            except (OSError, RuntimeError, asyncio.CancelledError) as exc:
                raise HubError(f"supervisor execution failed: {exc}") from exc
            return {"ok": True, "backend": backend_name(), "result": result.to_dict()}
        job_id = str(envelope.payload.get("job_id") or "")
        if not job_id:
            raise HubProtocolError("job_id is required")
        if envelope.method == "submit":
            if job_id in self.jobs:
                raise HubProtocolError("job already exists")
            self.jobs[job_id] = {
                "job_id": job_id,
                "client_id": envelope.payload.get("client_id"),
                "state": "queued",
                "progress": 0,
                "result": None,
            }
            return {"ok": True, "job": dict(self.jobs[job_id])}
        job = self.jobs.get(job_id)
        if job is None:
            raise HubProtocolError("unknown job")
        if envelope.method == "claim":
            if job["state"] != "queued":
                raise HubProtocolError("job is not claimable")
            job["state"] = "claimed"
        elif envelope.method == "heartbeat":
            if job["state"] not in ("claimed", "running"):
                raise HubProtocolError("job has no active lease")
        elif envelope.method == "progress":
            progress = int(envelope.payload.get("progress", -1))
            if not 0 <= progress <= 100:
                raise HubProtocolError("progress must be between 0 and 100")
            job["progress"] = progress
            job["state"] = "running"
        elif envelope.method == "cancel":
            job["state"] = "cancelled"
        elif envelope.method == "result":
            job["result"] = envelope.payload.get("result")
            job["state"] = "completed"
        elif envelope.method == "report":
            return {"ok": True, "job": dict(job), "clients": sorted(self.clients)}
        return {"ok": True, "job": dict(job)}
    def _claim_next_locked(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """Claim the next scheduler-selected durable job, skipping stale entries."""
        for _ in range(4096):
            scheduled = self.scheduler.next()
            if scheduled is None:
                return None
            task_id = self.queue.find_task_id(scheduled.task_id)
            if task_id is None:
                self._retire_scheduler_entry(scheduled.task_id)
                continue
            row = self.queue.get_row(task_id)
            job = dict(row["payload"])
            if job.get("state") != "queued":
                self._retire_scheduler_entry(scheduled.task_id)
                continue
            job["state"] = "claimed"
            self.queue.update_payload(task_id, job)
            return job
        return None

    def _retire_scheduler_entry(self, task_id: str) -> None:
        try:
            self.scheduler.complete(task_id)
        except SchedulerError:
            pass


class HubClient:
    """Small typed client facade for tests and future IPC transports."""

    def __init__(self, daemon: HubDaemon, client_id: str) -> None:
        self.daemon = daemon
        self.client_id = client_id

    def request(self, request_id: str, method: str, **payload: Any) -> Dict[str, Any]:
        payload.setdefault("client_id", self.client_id)
        return self.daemon.handle(HubEnvelope(request_id, method, payload))


def default_transport() -> str:
    return "named-pipe" if os.name == "nt" else "unix"


def default_endpoint(root: Optional[str] = None) -> str:
    if os.name == "nt":
        suffix = "default" if not root else hashlib.sha256(os.path.abspath(root).encode("utf-8")).hexdigest()[:12]
        return r"\\.\pipe\simplicio-loop-hub-%s" % suffix
    short_temp_root = "/tmp" if os.path.isdir("/tmp") else tempfile.gettempdir()
    if root:
        # AF_UNIX paths are capped at a small platform-dependent length.  A
        # pytest/temp workspace path can exceed it, so keep the endpoint short
        # while retaining per-root isolation.
        digest = hashlib.sha256(os.path.abspath(root).encode("utf-8")).hexdigest()[:16]
        return str(Path(short_temp_root) / ("simplicio-loop-hub-%s.sock" % digest))
    return str(Path(short_temp_root) / "simplicio-loop-hub.sock")


def _tcp_address(endpoint: str) -> Tuple[str, int]:
    address = str(endpoint).removeprefix("tcp://")
    try:
        host, raw_port = address.rsplit(":", 1)
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise HubError("invalid TCP Hub endpoint") from exc
    if host not in {"127.0.0.1", "localhost"} or not 1 <= port <= 65535:
        raise HubError("TCP Hub endpoint must use loopback and a valid port")
    return host, port


def _pipe_listener(endpoint: str):
    from multiprocessing.connection import Listener
    return Listener(endpoint, family="AF_PIPE")


def _pipe_client(endpoint: str):
    from multiprocessing.connection import Client
    return Client(endpoint, family="AF_PIPE")


def _recv_line(conn: socket.socket) -> str:
    chunks = []
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    return b"".join(chunks).decode("utf-8").strip()


class HubSocketServer:
    """Local IPC transport for HubDaemon: TCP/Unix sockets or a Windows named pipe.

    TCP uses the same newline-delimited JSON protocol as Unix sockets and is
    available on every host, including Windows builds where asyncio does not
    expose ``start_unix_server``. Named pipes remain the native Windows option
    for callers that need it.
    """

    _DISPATCH_TIMEOUT_SECONDS = 5.0

    def __init__(self, daemon: HubDaemon, socket_path: str, transport: Optional[str] = None) -> None:
        self.daemon = daemon
        self.socket_path = Path(socket_path)
        self.endpoint = socket_path
        self.transport = transport or default_transport()
        if self.transport not in {"unix", "named-pipe", "tcp"}:
            raise ValueError("transport must be unix, named-pipe, or tcp")
        if self.transport == "tcp":
            _tcp_address(self.endpoint)
        self._listener = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        # Unix (asyncio) transport state.
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._async_server: Optional[asyncio.base_events.Server] = None
        self._connections: Set[asyncio.Task] = set()
        self._code_workflows: Dict[str, str] = {}
        self._code_sessions: Dict[str, str] = {}

    def start(self) -> None:
        if self._running:
            return
        if self.transport == "named-pipe":
            if os.name != "nt":
                raise RuntimeError("named-pipe transport requires Windows")
            self._listener = _pipe_listener(self.endpoint)
            self._running = True
            self._thread = threading.Thread(target=self._serve_forever_named_pipe, daemon=True)
            self._thread.start()
            return
        if self.transport == "unix":
            self.socket_path.parent.mkdir(parents=True, exist_ok=True)
            if self.socket_path.exists():
                self.socket_path.unlink()
        elif self.transport != "tcp":
            raise ValueError("unsupported socket transport")
        self._running = True
        ready = threading.Event()
        error: Dict[str, BaseException] = {}
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, args=(ready, error), daemon=True)
        self._thread.start()
        ready.wait(timeout=10)
        if "exc" in error:
            self._running = False
            raise error["exc"]
        if self.transport == "unix":
            os.chmod(str(self.socket_path), 0o600)

    def _run_loop(self, ready: threading.Event, error: Dict[str, BaseException]) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            if self.transport == "tcp":
                host, port = _tcp_address(self.endpoint)
                self._async_server = self._loop.run_until_complete(
                    asyncio.start_server(self._handle_conn_async, host, port)
                )
            elif hasattr(asyncio, "start_unix_server"):
                self._async_server = self._loop.run_until_complete(
                    asyncio.start_unix_server(self._handle_conn_async, path=str(self.socket_path))
                )
            else:
                unix_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                unix_listener.bind(str(self.socket_path))
                unix_listener.listen(socket.SOMAXCONN)
                unix_listener.setblocking(False)
                self._async_server = self._loop.run_until_complete(
                    asyncio.start_server(self._handle_conn_async, sock=unix_listener)
                )
        except (OSError, ValueError, AttributeError) as exc:
            error["exc"] = exc
            ready.set()
            return
        ready.set()
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    async def _handle_conn_async(self, reader: "asyncio.StreamReader", writer: "asyncio.StreamWriter") -> None:
        task = asyncio.current_task()
        if task is not None:
            self._connections.add(task)
        try:
            while True:
                try:
                    raw_line = await asyncio.wait_for(reader.readline(), timeout=self._DISPATCH_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    return
                if not raw_line:
                    return
                raw = raw_line.decode("utf-8").strip()
                if not raw:
                    continue
                response = self._dispatch(raw)
                writer.write((json.dumps(response) + "\n").encode("utf-8"))
                await writer.drain()
        except (OSError, ConnectionError):
            return
        finally:
            if task is not None:
                self._connections.discard(task)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    def _serve_forever_named_pipe(self) -> None:
        while self._running:
            try:
                conn = self._listener.accept()
            except OSError:
                break
            threading.Thread(target=self._handle_conn_named_pipe, args=(conn,), daemon=True).start()

    def _handle_conn_named_pipe(self, conn) -> None:
        try:
            raw = conn.recv_bytes().decode("utf-8")
            response = self._dispatch(raw)
            conn.send_bytes(json.dumps(response).encode("utf-8"))
        except (OSError, EOFError):
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _dispatch(self, raw: str) -> Dict[str, Any]:
        try:
            candidate = json.loads(raw)
        except json.JSONDecodeError:
            candidate = None
        if isinstance(candidate, dict) and candidate.get("schema") == CODE_HUB_CLIENT_SCHEMA:
            return self._dispatch_code(candidate)
        try:
            return self.daemon.handle(HubEnvelope.decode(raw))
        except HubError as exc:
            response = {"ok": False, "error": str(exc)}
            if getattr(exc, "reason_code", None):
                response["reason_code"] = exc.reason_code
            return response

    def _dispatch_code(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Serve Code's transport-only client contract on the same Hub socket.

        The wire is intentionally kept at the external boundary. All mutable
        queue/session work is delegated to ``HubDaemon.handle`` so Code never
        becomes a second scheduler or Runtime/Mapper owner.
        """
        request_id = request.get("id")
        method = request.get("method")
        payload = request.get("payload")
        response: Dict[str, Any] = {"schema": CODE_HUB_CLIENT_SCHEMA, "id": request_id, "ok": True}
        try:
            if not isinstance(request_id, int) or request_id < 1:
                raise HubProtocolError("Code Hub request id must be a positive integer")
            if not isinstance(method, str) or method not in {"handshake", "attach", "submit", "progress", "cancel", "resume", "runtime_execute", "runtime_call", "worker_delegate", "worker_status", "worker_cancel", "worker_deliver"}:
                raise HubProtocolError("unsupported Code Hub method")
            if not isinstance(payload, dict):
                raise HubProtocolError("Code Hub payload must be an object")
            if method.startswith("worker_"):
                result = self.daemon.handle(HubEnvelope(str(request_id), method, payload))
                response["result"] = result[method.removeprefix("worker_")]
                return response
            if method == "runtime_execute":
                workspace = str(payload.get("workspace") or "")
                argv = payload.get("argv")
                if not isinstance(argv, list) or any(not isinstance(item, str) for item in argv):
                    raise HubProtocolError("runtime_execute argv must be a string list")
                try:
                    result = self.daemon.runtime_bridge.execute(
                        workspace,
                        argv,
                        cwd=str(payload.get("cwd") or "."),
                        env=payload.get("env") if isinstance(payload.get("env"), dict) else {},
                        timeout_ms=int(payload.get("timeout_ms") or 120_000),
                        max_output_bytes=int(payload.get("max_output_bytes") or 4 * 1024 * 1024),
                        idempotency_key=str(payload.get("idempotency_key") or ""),
                    )
                except (RuntimeBridgeError, TypeError, ValueError) as exc:
                    raise HubProtocolError("Runtime effect rejected: %s" % exc) from exc
                response["result"] = {
                    "schema": "simplicio.loop-runtime-execution/v1",
                    "workspace": workspace,
                    "result": result,
                }
                return response
            if method == "runtime_call":
                workspace = str(payload.get("workspace") or "")
                tool = str(payload.get("tool") or "")
                arguments = payload.get("arguments")
                if not isinstance(arguments, dict):
                    raise HubProtocolError("runtime_call arguments must be an object")
                try:
                    result = self.daemon.runtime_bridge.runtime_call(
                        workspace,
                        tool,
                        arguments,
                        cwd=str(payload.get("cwd") or "."),
                        timeout_ms=int(payload.get("timeout_ms") or 120_000),
                        idempotency_key=str(payload.get("idempotency_key") or ""),
                    )
                except (RuntimeBridgeError, TypeError, ValueError) as exc:
                    raise HubProtocolError("Runtime call rejected: %s" % exc) from exc
                response["result"] = {
                    "schema": RUNTIME_CALL_SCHEMA,
                    "workspace": workspace,
                    "tool": tool,
                    "result": result,
                }
                return response
            if method == "handshake":
                if payload.get("schema") != CODE_HUB_CLIENT_SCHEMA or payload.get("protocol") != CODE_HUB_PROTOCOL:
                    raise HubProtocolError("unsupported Code Hub handshake schema/protocol")
                client_id = str(payload.get("client_id") or "")
                workspace_id = str(payload.get("workspace_id") or "")
                session_id = str(payload.get("session_id") or "")
                if not client_id or not workspace_id or not session_id:
                    raise HubProtocolError("Code Hub handshake requires client, workspace, and session IDs")
                self._code_sessions[session_id] = client_id
                process_id = str(os.getpid())
                response["result"] = {
                    "schema": CODE_HUB_CLIENT_SCHEMA,
                    "protocol": CODE_HUB_PROTOCOL,
                    "hub_id": "loop-hub:" + self.daemon.epoch,
                    "ready": True,
                    "agent": {"agent_id": "loop-agent:" + process_id,
                               "protocol": "simplicio.agent/v1", "ready": True},
                    "services": [
                        {"name": name, "owner": "loop-hub",
                         "process_id": f"loop-hub:{process_id}:{name}"}
                        for name in ("runtime", "mapper", "scheduler", "inference")
                    ],
                    "resources": {
                        "runtime": {"id": "runtime:" + self.daemon.epoch, "capacity": 1, "used": 0},
                        "mapper": {"id": "mapper:" + self.daemon.epoch, "capacity": 1, "used": 0},
                        "inference": {"id": "inference:" + self.daemon.epoch, "capacity": 1, "used": 0},
                        "max_active_inference": 1, "interactive_reserved": 1,
                    },
                    "queue": {"interactive_capacity": 1, "background_capacity": 1,
                              "max_pending_interactive": 8},
                    "local_scheduler": False,
                }
                return response
            if method == "attach":
                if payload.get("schema") != CODE_HUB_CLIENT_SCHEMA or payload.get("protocol") != CODE_HUB_PROTOCOL:
                    raise HubProtocolError("unsupported Code Hub attach schema/protocol")
                session_id = str(payload.get("session_id") or "")
                client_id = str(payload.get("client_id") or "")
                if not session_id or not client_id:
                    raise HubProtocolError("Code Hub attach requires client and session IDs")
                self._code_sessions[session_id] = client_id
                self.daemon.handle(HubEnvelope(str(request_id), "attach", {
                    "client_id": client_id, "session_id": session_id,
                    "epoch": self.daemon.epoch, "cursor": 0,
                }))
                response["result"] = {"schema": CODE_HUB_CLIENT_SCHEMA, "protocol": CODE_HUB_PROTOCOL,
                                       "hub_id": "loop-hub:" + self.daemon.epoch,
                                       "session_id": session_id, "accepted": True, "replay_from": []}
                return response
            session_id = str(payload.get("session_id") or "")
            if method == "submit" and not session_id:
                raise HubProtocolError("Code Hub operation requires a session ID")
            workflow_id = str(payload.get("workflow_id") or payload.get("idempotency_key") or "")
            if not session_id and workflow_id:
                session_id = self._code_workflows.get(workflow_id, "")
            client_id = str(payload.get("client_id") or self._code_sessions.get(session_id, "code"))
            if method == "submit":
                workflow_id = str(payload.get("idempotency_key") or "")
                if not workflow_id:
                    raise HubProtocolError("Code Hub submit requires an idempotency key")
                operation = {
                    "client_id": client_id, "session_id": session_id, "job_id": workflow_id,
                    "workspace_id": payload.get("workspace_id") or "default", "priority": "interactive",
                    "weight": 1, "cost": int(payload.get("budget_tokens") or 1),
                    "metadata": {"goal_id": payload.get("goal_id"), "turn_id": payload.get("turn_id"),
                                 "payload": payload.get("payload")},
                }
                result = self.daemon.handle(HubEnvelope(workflow_id, "submit", operation))
                self._code_workflows[workflow_id] = session_id
                response["result"] = {"schema": CODE_HUB_CLIENT_SCHEMA, "workflow_id": workflow_id,
                                       "state": "queued", "queue_position": 1, "retry_after_ms": None,
                                       "receipt_id": "admission:" + workflow_id}
                return response
            if not workflow_id:
                raise HubProtocolError("Code Hub operation requires a workflow ID")
            if method in {"cancel", "resume"}:
                operation = {"client_id": client_id,
                             "session_id": session_id or self._code_workflows.get(workflow_id, ""),
                             "job_id": workflow_id,
                             "reason": payload.get("reason", "Code request")}
                result = self.daemon.handle(HubEnvelope(str(payload.get("idempotency_key") or request_id), method, operation))
                state = str((result.get("job") or {}).get("state") or ("cancelled" if method == "cancel" else "queued"))
                response["result"] = {"schema": CODE_HUB_CLIENT_SCHEMA, "workflow_id": workflow_id,
                                       "receipt_id": f"{method}:{workflow_id}", "state": state}
                return response
            report = self.daemon.handle(HubEnvelope(str(request_id), "report", {"job_id": workflow_id}))
            job = report.get("job") or {}
            state = str(job.get("state") or "queued")
            terminal = state in {"cancelled", "completed", "failed", "blocked"}
            event_type = {"cancelled": "cancelled", "completed": "completed", "failed": "failed"}.get(state, "queued")
            event: Dict[str, Any] = {"type": event_type, "sequence": 0}
            if event_type == "cancelled":
                event["receipt_id"] = "cancel:" + workflow_id
            elif event_type == "completed":
                event["receipt_id"] = "complete:" + workflow_id
            elif event_type == "failed":
                event["message"] = "Hub job failed"
                event["receipt_id"] = "failed:" + workflow_id
            else:
                event["position"] = 1
            response["result"] = {"workflow_id": workflow_id, "next_sequence": 1,
                                   "events": [] if int(payload.get("after_sequence", 0)) >= 1 else [event],
                                   "terminal": terminal}
            return response
        except HubError as exc:
            response["ok"] = False
            response["error"] = str(exc)
            return response

    def shutdown(self) -> None:
        if self._running:
            self._running = False
            if self.transport == "named-pipe":
                if self._listener is not None:
                    try:
                        self._listener.close()
                    except OSError:
                        pass
                    self._listener = None
                if self._thread is not None:
                    self._thread.join(timeout=2)
                    self._thread = None
            else:
                if self._loop is not None and self._async_server is not None:
                    asyncio.run_coroutine_threadsafe(self._shutdown_async(), self._loop).result(timeout=5)
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(self._loop.stop)
                if self._thread is not None:
                    self._thread.join(timeout=5)
                    self._thread = None
                self._loop = None
                self._async_server = None
        if self.transport == "unix":
            try:
                self.socket_path.unlink()
            except FileNotFoundError:
                pass

    async def _shutdown_async(self) -> None:
        assert self._async_server is not None
        self._async_server.close()
        await self._async_server.wait_closed()
        pending = list(self._connections)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    stop = shutdown


class HubSocketClient:
    """Standalone client for HubSocketServer; usable with no daemon in-process."""

    def __init__(self, socket_path: str, timeout: float = 5.0, transport: Optional[str] = None) -> None:
        self.socket_path = socket_path
        self.timeout = timeout
        self.endpoint = socket_path
        self.transport = transport or default_transport()
        if self.transport not in {"unix", "named-pipe", "tcp"}:
            raise ValueError("transport must be unix, named-pipe, or tcp")

    def request(self, request_id: str, method: str, **payload: Any) -> Dict[str, Any]:
        return self.request_raw(HubEnvelope(request_id, method, payload).encode())

    def request_raw(self, raw: str) -> Dict[str, Any]:
        if self.transport == "named-pipe":
            conn = _pipe_client(self.endpoint)
            try:
                conn.send_bytes(raw.encode("utf-8"))
                raw = conn.recv_bytes().decode("utf-8")
            finally:
                conn.close()
        elif self.transport == "tcp":
            host, port = _tcp_address(self.endpoint)
            with socket.create_connection((host, port), timeout=self.timeout) as sock:
                sock.sendall((raw + "\n").encode("utf-8"))
                raw = _recv_line(sock)
        else:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(self.socket_path)
                sock.sendall((raw + "\n").encode("utf-8"))
                raw = _recv_line(sock)
        if not raw:
            raise HubError("no response from Hub daemon")
        return json.loads(raw)


def doctor(lock_path: str, socket_path: str, transport: Optional[str] = None) -> Dict[str, Any]:
    """Report whether a live daemon owns the lock and answers on the socket."""
    lock_file = Path(lock_path)
    result: Dict[str, Any] = {
        "lock_exists": lock_file.exists(),
        "lock_pid_alive": False,
        "socket_exists": (transport or default_transport()) in {"named-pipe", "tcp"} or Path(socket_path).exists(),
        "socket_reachable": False,
    }
    if lock_file.exists():
        try:
            payload = json.loads(lock_file.read_text(encoding="utf-8"))
            pid = int(payload.get("pid", 0))
            result["pid"] = pid
            result["lock_pid_alive"] = _pid_alive(pid)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    if result["socket_exists"]:
        try:
            client = HubSocketClient(socket_path, timeout=1.0, transport=transport)
            response = client.request("doctor", "ping")
            result["socket_reachable"] = bool(response.get("ok"))
        except (OSError, HubError, json.JSONDecodeError):
            result["socket_reachable"] = False
    return result


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="simplicio-hub",
        description="run or inspect the local Loop Hub daemon",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="start the local Hub daemon")
    serve.add_argument("--lock", default=str(Path(tempfile.gettempdir()) / "simplicio-loop-hub.lock"))
    serve.add_argument("--endpoint", default=default_endpoint())
    serve.add_argument("--transport", choices=("unix", "named-pipe", "tcp"), default=default_transport())
    serve.add_argument("--shutdown-file", default=None)
    check = sub.add_parser("doctor", help="check Hub lock and endpoint reachability")
    check.add_argument("--lock", default=str(Path(tempfile.gettempdir()) / "simplicio-loop-hub.lock"))
    check.add_argument("--endpoint", default=default_endpoint())
    check.add_argument("--transport", choices=("unix", "named-pipe", "tcp"), default=default_transport())
    args = parser.parse_args(argv)
    if args.command == "doctor":
        print(json.dumps(doctor(args.lock, args.endpoint, args.transport), sort_keys=True))
        return 0
    shutdown_requested = threading.Event()

    def _handle_shutdown(_signum, _frame):
        shutdown_requested.set()

    for _signal in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
        if _signal is not None:
            signal.signal(_signal, _handle_shutdown)

    daemon = HubDaemon(args.lock)
    server = HubSocketServer(daemon, args.endpoint, args.transport)
    try:
        daemon.start()
        server.start()
        print(json.dumps({"ready": True, "endpoint": args.endpoint, "transport": args.transport}), flush=True)
        while not shutdown_requested.wait(0.1):
            if args.shutdown_file and Path(args.shutdown_file).exists():
                break
    except KeyboardInterrupt:
        return 0
    finally:
        server.shutdown()
        daemon.stop()
    return 0
