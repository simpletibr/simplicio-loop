"""Shared queue coordination with durable leases and fencing.

``SQLiteRemoteQueue`` is the compatibility facade for the
``simplicio.queue/v1`` contract.  Its durable task and lease state is owned by
MapperStore; deployments that need a network service use the same atomic
methods through :class:`RemoteQueue`.
The module intentionally has no fail-open path: an unavailable store raises
and callers must hand off rather than mutate a task.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import ipaddress
import ssl
import time
import urllib.error
import urllib.request
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence

from .agent_contract import validate_identity
from .receipt_verifier import canonical_content_hash
from .secure_transport import SecureTransportError, TrustedEndpoint
from .secure_transport import request_json as _secure_request_json

try:  # pragma: no cover - installed package without scripts namespace
    from scripts.distributed_trust_policy import check_endpoint as _check_endpoint
except ImportError:  # pragma: no cover
    _check_endpoint = None

try:  # pragma: no cover - installed package without scripts namespace
    from scripts.security_audit_log import append_event as _audit_append
except ImportError:  # pragma: no cover
    _audit_append = None


SCHEMA = "simplicio.queue/v1"


class _QueueHTTPServer(ThreadingHTTPServer):
    """Loopback queue server sized for the documented concurrent claim lane."""

    daemon_threads = True
    request_queue_size = 128


class QueueConflict(RuntimeError):
    """The caller lost a lease or presented an old fencing token."""


class QueueUnavailable(RuntimeError):
    """The queue could not be reached; mutation must pause and hand off."""


@dataclass(frozen=True)
class Lease:
    task_id: str
    agent_id: str
    lease_id: str
    fencing_token: int | str
    expires_at: float
    idempotency_key: str
    identity: Optional[Dict[str, Any]] = None
    capabilities: tuple[str, ...] = ()
    cancelled: bool = False
    # MapperStore operations use an opaque attempt id in addition to the
    # legacy queue lease id; legacy transports leave it empty.
    attempt_id: str = ""


class RemoteQueue(Protocol):
    def pull(self, agent_id: str, *, capabilities: Optional[Sequence[str]] = None,
             limit: int = 20) -> List[Dict[str, Any]]: ...

    def claim(self, task_id: str, agent_id: str, *, idempotency_key: str,
              ttl: float = 60.0, identity: Optional[Mapping[str, Any]] = None,
              capabilities: Optional[Sequence[str]] = None) -> Lease: ...

    def heartbeat(self, lease: Lease, *, ttl: float = 60.0) -> Lease: ...

    def complete(self, lease: Lease, *, receipt_ref: str,
                 receipt: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]: ...

    def assert_active(self, lease: Lease) -> None: ...

    def request_cancel(self, task_id: str, *, reason: str = "cancelled") -> Dict[str, Any]: ...


def _lease_from_json(value: Mapping[str, Any]) -> Lease:
    """Decode the wire representation without trusting client-controlled fields."""
    fencing_token = value["fencing_token"]
    if isinstance(fencing_token, bool) or not isinstance(fencing_token, (int, str)):
        raise ValueError("fencing_token must be an integer or opaque string")
    if isinstance(fencing_token, str) and not fencing_token.strip():
        raise ValueError("fencing_token must not be empty")
    return Lease(str(value["task_id"]), str(value["agent_id"]), str(value["lease_id"]),
                 fencing_token, float(value["expires_at"]),
                 str(value["idempotency_key"]), value.get("identity"),
                 tuple(value.get("capabilities") or ()), bool(value.get("cancelled", False)),
                 str(value.get("attempt_id") or ""))


def _lease_json(lease: Lease) -> Dict[str, Any]:
    return {"task_id": lease.task_id, "agent_id": lease.agent_id, "lease_id": lease.lease_id,
            "fencing_token": lease.fencing_token, "expires_at": lease.expires_at,
            "idempotency_key": lease.idempotency_key, "identity": lease.identity,
            "capabilities": list(lease.capabilities), "cancelled": lease.cancelled,
            "attempt_id": lease.attempt_id}


def build_completion_receipt(*, task_id: str, agent_id: str, fencing_token: int | str, receipt_ref: str,
                             extra: Optional[Mapping[str, Any]] = None,
                             now: Optional[float] = None) -> Dict[str, Any]:
    """Build the wire receipt a caller passes as ``RemoteQueue.complete(..., receipt=...)``.

    This is what makes server-side verification of issue #286 step 9 real rather than
    aspirational: the queue independently recomputes ``receipt_sha`` over this exact payload
    (:data:`simplicio_loop.receipt_verifier.QUEUE_RECEIPT_SCHEMA`) and cross-checks
    ``task_id``/``agent_id``/``fencing_token`` against the *active* lease before ever marking a
    task ``completed`` -- a forged or stale receipt for the wrong task/attempt/fence is rejected
    even if the presenting client insists it is legitimate.
    """
    body: Dict[str, Any] = {
        "schema": "simplicio.queue-receipt/v1",
        "task_id": str(task_id),
        "agent_id": str(agent_id),
        "fencing_token": int(fencing_token) if isinstance(fencing_token, int) else str(fencing_token),
        "receipt_ref": str(receipt_ref),
        "measured_at": _now() if now is None else float(now),
    }
    if extra:
        body["detail"] = json.loads(json.dumps(dict(extra), default=str))
    body["receipt_sha"] = canonical_content_hash(body)
    return body


class HTTPRemoteQueue:
    """Network client for ``simplicio.queue/v1``.

    The client has no local mutation fallback: DNS, timeout, non-JSON, and 5xx
    failures become :class:`QueueUnavailable`, so callers must pause and hand
    off rather than mutating a checkout while disconnected.
    """

    def __init__(self, base_url: str, *, token: Optional[str] = None, timeout: float = 5.0,
                 environment_id: Optional[str] = None, policy: Optional[Mapping[str, Any]] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._require_secure_transport()
        # #289: when the caller resolved a trust-policy environment for this queue
        # (see `runner._resolve_trusted_queue_url`), every request below is forced
        # through `secure_transport.request_json`, which performs its own DNS
        # resolution/TLS handshake and calls `check_endpoint()` with the
        # *measured* certificate fingerprint before sending anything -- the
        # connect-time enforcement `check_endpoint()` previously lacked.
        self._trusted_endpoint: Optional[TrustedEndpoint] = None
        if environment_id and policy is not None:
            if _check_endpoint is None:
                raise QueueUnavailable(
                    "distributed trust policy module unavailable; cannot enforce connect-time checks"
                )
            self._trusted_endpoint = TrustedEndpoint(
                environment_id=environment_id, policy=policy, check_endpoint=_check_endpoint,
            )

    def _require_secure_transport(self) -> None:
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("queue URL must use http or https")
        if not parsed.hostname:
            raise ValueError("queue URL must include a host")
        if parsed.scheme != "https" and not _is_loopback_host(parsed.hostname):
            raise QueueUnavailable("TLS is required for non-loopback queue URLs")

    def _request(self, method: str, path: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        self._require_secure_transport()
        body = json.dumps(payload or {}, sort_keys=True).encode("utf-8")
        headers = {"Content-Type": "application/json",
                   **({"Authorization": "Bearer " + self.token} if self.token else {})}
        url = self.base_url + "/v1/queue" + path

        if self._trusted_endpoint is not None:
            try:
                result = _secure_request_json(
                    method, url, body=body, headers=headers, timeout=self.timeout,
                    endpoint=self._trusted_endpoint,
                )
            except SecureTransportError as exc:
                raise QueueUnavailable("connect-time trust check failed: %s" % exc) from exc
            status = result.pop("_status", 200)
            if status == 200:
                return result
            message = str(result.get("error") or "queue request failed")
            if status == 409:
                raise QueueConflict(message)
            if status == 404:
                raise KeyError(message)
            if status in (400, 401):
                raise ValueError(message)
            raise QueueUnavailable(message)

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:  # noqa: S310
                raw = response.read()
                result = json.loads(raw.decode("utf-8"))
                if not isinstance(result, dict):
                    raise ValueError("queue response must be an object")
                return result
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8"))
            except Exception:
                detail = {}
            message = str(detail.get("error") or exc.reason or "queue request failed")
            if exc.code == 409:
                raise QueueConflict(message) from exc
            if exc.code in (400, 401, 404):
                raise (KeyError(message) if exc.code == 404 else ValueError(message)) from exc
            raise QueueUnavailable(message) from exc
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise QueueUnavailable("queue unavailable: %s" % exc) from exc

    async def _request_async(self, method: str, path: str, payload: Optional[Mapping[str, Any]] = None,
                             *, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Run the blocking ``urlopen``/secure-transport call in a worker thread.

        This is the async escape hatch for the hot polling loop (``pull``/``claim``/
        ``heartbeat``/``complete``) so a remote worker's asyncio event loop is never
        stalled for the duration of a real network round trip. ``timeout`` bounds the
        *async* wait independently of ``self.timeout`` (the socket-level timeout inside
        ``_request``): if the deadline elapses first, the awaiting caller gets control
        back immediately with :class:`QueueUnavailable` -- the underlying OS thread is
        asked to cancel and, since ``urlopen`` does not cooperatively check for
        cancellation, keeps running until its own socket timeout independently, exactly
        like a detached child process a caller stopped waiting on.
        """
        loop = asyncio.get_running_loop()
        deadline = self.timeout if timeout is None else timeout
        future = loop.run_in_executor(None, self._request, method, path, payload)
        try:
            return await asyncio.wait_for(future, timeout=deadline)
        except asyncio.TimeoutError as exc:
            future.cancel()
            raise QueueUnavailable(
                "queue request exceeded async deadline of %ss" % deadline
            ) from exc
        except asyncio.CancelledError:
            future.cancel()
            raise

    def enqueue(self, task_id: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self._request("POST", "/enqueue", {"task_id": task_id, "payload": payload or {}})

    async def enqueue_async(self, task_id: str, payload: Optional[Dict[str, Any]] = None,
                            *, timeout: Optional[float] = None) -> None:
        await self._request_async("POST", "/enqueue", {"task_id": task_id, "payload": payload or {}},
                                  timeout=timeout)

    def claim(self, task_id: str, agent_id: str, *, idempotency_key: str,
              ttl: float = 60.0, identity: Optional[Mapping[str, Any]] = None,
              capabilities: Optional[Sequence[str]] = None) -> Lease:
        result = self._request("POST", "/claim", {"task_id": task_id, "agent_id": agent_id,
            "idempotency_key": idempotency_key, "ttl": ttl, "identity": identity,
            "capabilities": list(capabilities) if capabilities is not None else None})
        return _lease_from_json(result["lease"])

    async def claim_async(self, task_id: str, agent_id: str, *, idempotency_key: str,
                          ttl: float = 60.0, identity: Optional[Mapping[str, Any]] = None,
                          capabilities: Optional[Sequence[str]] = None,
                          timeout: Optional[float] = None) -> Lease:
        result = await self._request_async("POST", "/claim", {"task_id": task_id, "agent_id": agent_id,
            "idempotency_key": idempotency_key, "ttl": ttl, "identity": identity,
            "capabilities": list(capabilities) if capabilities is not None else None}, timeout=timeout)
        return _lease_from_json(result["lease"])

    def heartbeat(self, lease: Lease, *, ttl: float = 60.0) -> Lease:
        result = self._request("POST", "/heartbeat", {"lease": _lease_json(lease), "ttl": ttl})
        return _lease_from_json(result["lease"])

    async def heartbeat_async(self, lease: Lease, *, ttl: float = 60.0,
                              timeout: Optional[float] = None) -> Lease:
        result = await self._request_async("POST", "/heartbeat", {"lease": _lease_json(lease), "ttl": ttl},
                                           timeout=timeout)
        return _lease_from_json(result["lease"])

    def complete(self, lease: Lease, *, receipt_ref: str,
                receipt: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"lease": _lease_json(lease), "receipt_ref": receipt_ref}
        if receipt is not None:
            payload["receipt"] = dict(receipt)
        return self._request("POST", "/complete", payload)

    async def complete_async(self, lease: Lease, *, receipt_ref: str,
                             receipt: Optional[Mapping[str, Any]] = None,
                             timeout: Optional[float] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"lease": _lease_json(lease), "receipt_ref": receipt_ref}
        if receipt is not None:
            payload["receipt"] = dict(receipt)
        return await self._request_async("POST", "/complete", payload, timeout=timeout)

    def pull(self, agent_id: str, *, capabilities: Optional[Sequence[str]] = None,
             limit: int = 20) -> List[Dict[str, Any]]:
        """Discover ready, capability-matching work without claiming it.

        Only summaries of tasks this worker is eligible for are returned; the
        server never serializes the full payload/context of a task this
        worker cannot or should not see.
        """
        result = self._request("POST", "/pull", {"agent_id": agent_id,
            "capabilities": list(capabilities or ()), "limit": int(limit)})
        return list(result["tasks"])

    async def pull_async(self, agent_id: str, *, capabilities: Optional[Sequence[str]] = None,
                         limit: int = 20, timeout: Optional[float] = None) -> List[Dict[str, Any]]:
        """Async counterpart of :meth:`pull` -- see :meth:`_request_async`."""
        result = await self._request_async("POST", "/pull", {"agent_id": agent_id,
            "capabilities": list(capabilities or ()), "limit": int(limit)}, timeout=timeout)
        return list(result["tasks"])

    def assert_active(self, lease: Lease) -> None:
        self._request("POST", "/assert-active", {"lease": _lease_json(lease)})

    def request_cancel(self, task_id: str, *, reason: str = "cancelled") -> Dict[str, Any]:
        """Ask the current claimant to stop cooperatively (checked on its next heartbeat)."""
        return self._request("POST", "/cancel", {"task_id": task_id, "reason": reason})

    def release(self, lease: Lease, *, reason: str = "handoff") -> Dict[str, Any]:
        return self._request("POST", "/release", {"lease": _lease_json(lease), "reason": reason})

    def events(self, *, after: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        return self._request("POST", "/events", {"after": after, "limit": limit})["events"]

    def task(self, task_id: str) -> Dict[str, Any]:
        return self._request("POST", "/task", {"task_id": task_id})


def _now() -> float:
    return time.time()


def _lease_id(task_id: str, agent_id: str, key: str) -> str:
    return hashlib.sha256((task_id + "\0" + agent_id + "\0" + key).encode()).hexdigest()[:32]


class SQLiteRemoteQueue:
    """Compatibility facade backed by MapperStore operations.

    The historical name is retained for callers that have not switched to
    :class:`MapperRemoteQueue`. It creates no Loop-owned queue tables: task,
    lease, fence, completion and cancellation authority all live in MapperStore.
    """

    _SLOT_ID = "remote-queue-compat"
    _SLOT_CAPACITY = 1024
    _EVENT_SCHEMA = "simplicio.loop.remote-queue-event/v1"

    def __init__(
        self,
        path: str,
        *,
        busy_timeout: float = 10.0,
        receipt_max_age_seconds: Optional[float] = None,
    ) -> None:
        self.path = os.path.abspath(path)
        self.busy_timeout = busy_timeout
        self.receipt_max_age_seconds = receipt_max_age_seconds
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        try:
            from .mapper_remote_queue import MapperRemoteQueue

            self._mapper = MapperRemoteQueue(
                self.path, auto_create=True, slot_id=self._SLOT_ID
            )
            self._mapper.initialize()
            self._mapper.operations.register_slot(self._SLOT_ID, self._SLOT_CAPACITY)
        except Exception as exc:
            if isinstance(exc, (QueueConflict, QueueUnavailable, ValueError)):
                raise
            raise QueueUnavailable("MapperStore queue unavailable: %s" % exc) from exc
        self._run_id = "simplicio.loop.remote-queue-events:" + self.path

    @staticmethod
    def _lease_from_payload(payload: Mapping[str, Any]) -> Lease:
        value = payload["lease"]
        return _lease_from_json(value)

    def _events_raw(self) -> list[dict[str, Any]]:
        replay = self._mapper.operations.replay(self._run_id)
        if not replay.get("valid", False):
            raise QueueUnavailable("remote queue event journal is invalid")
        return list(replay.get("events") or [])

    def _emit(self, kind: str, *, lease: Lease | None = None,
              task_id: str | None = None, agent_id: str = "system",
              payload: Mapping[str, Any] | None = None) -> None:
        body: dict[str, Any] = {
            "schema": self._EVENT_SCHEMA,
            "task_id": task_id or (lease.task_id if lease else ""),
            "agent_id": lease.agent_id if lease else agent_id,
            "fencing_token": lease.fencing_token if lease else None,
            "payload": dict(payload or {}),
        }
        if lease is not None:
            body["lease"] = _lease_json(lease)
        try:
            self._mapper.operations.append_event(self._run_id, kind, body)
        except Exception as exc:
            raise QueueUnavailable("remote queue event append failed: %s" % exc) from exc

    def _active_idempotent_claim(self, task_id: str, idempotency_key: str) -> Lease | None:
        for event in reversed(self._events_raw()):
            payload = event.get("payload") or {}
            if payload.get("schema") != self._EVENT_SCHEMA:
                continue
            if payload.get("task_id") != task_id:
                continue
            lease_payload = payload.get("lease") or {}
            if lease_payload.get("idempotency_key") != idempotency_key:
                continue
            if event.get("event_type") in {"released", "completed"}:
                return None
            if event.get("event_type") == "claimed":
                lease = self._lease_from_payload(payload)
                return lease if lease.expires_at > _now() else None
        return None

    def _current_lease(self, task_id: str) -> Lease | None:
        for event in reversed(self._events_raw()):
            payload = event.get("payload") or {}
            if payload.get("schema") != self._EVENT_SCHEMA or payload.get("task_id") != task_id:
                continue
            if event.get("event_type") == "claimed":
                lease = self._lease_from_payload(payload)
                return lease if lease.expires_at > _now() else None
            if event.get("event_type") in {"released", "completed"}:
                return None
        return None

    def _cancelled_for(self, lease: Lease) -> bool:
        for event in reversed(self._events_raw()):
            payload = event.get("payload") or {}
            if payload.get("schema") != self._EVENT_SCHEMA or payload.get("task_id") != lease.task_id:
                continue
            if str(payload.get("fencing_token")) != str(lease.fencing_token):
                continue
            kind = event.get("event_type")
            if kind == "cancel_requested":
                return True
            if kind in {"claimed", "released", "completed"}:
                return False
        return False

    def enqueue(self, task_id: str, payload: Optional[Dict[str, Any]] = None) -> None:
        task_id = str(task_id).strip()
        if not task_id:
            raise ValueError("task_id is required")
        self._mapper.enqueue(task_id, payload or {}, idempotency_key=f"loop:remote:{task_id}")
        self._emit("enqueued", task_id=task_id, payload=payload or {})

    def pull(self, agent_id: str, *, capabilities: Optional[Sequence[str]] = None,
             limit: int = 20) -> List[Dict[str, Any]]:
        return self._mapper.pull(agent_id, capabilities=capabilities, limit=limit)

    def claim(self, task_id: str, agent_id: str, *, idempotency_key: str,
              ttl: float = 60.0, identity: Optional[Mapping[str, Any]] = None,
              capabilities: Optional[Sequence[str]] = None) -> Lease:
        if ttl <= 0 or not agent_id or not idempotency_key:
            raise ValueError("agent_id, idempotency_key and positive ttl are required")
        if identity is not None:
            normalized = validate_identity(identity, capabilities=capabilities)
            if normalized["agent_id"] != agent_id:
                raise QueueConflict("agent_id does not match distributed identity")
            identity = normalized
        for event in self._events_raw():
            payload = event.get("payload") or {}
            lease_payload = payload.get("lease") or {}
            if lease_payload.get("idempotency_key") == idempotency_key and payload.get("task_id") != task_id:
                raise QueueConflict("idempotency key already belongs to another task")
        existing = self._active_idempotent_claim(task_id, idempotency_key)
        if existing is not None:
            return existing
        self._mapper.operations.reclaim_expired()
        lease = self._mapper.claim(
            task_id, agent_id, idempotency_key=idempotency_key, ttl=ttl,
            identity=identity, capabilities=capabilities,
        )
        self._emit("claimed", lease=lease, payload={"expires_at": lease.expires_at})
        return lease

    def heartbeat(self, lease: Lease, *, ttl: float = 60.0) -> Lease:
        if ttl <= 0:
            raise ValueError("positive ttl is required")
        refreshed = self._mapper.heartbeat(lease, ttl=ttl)
        self._emit("heartbeat", lease=refreshed, payload={"expires_at": refreshed.expires_at})
        return Lease(**{**refreshed.__dict__, "cancelled": self._cancelled_for(refreshed)})

    def assert_active(self, lease: Lease) -> None:
        self._mapper.assert_active(lease)

    def request_cancel(self, task_id: str, *, reason: str = "cancelled") -> Dict[str, Any]:
        lease = self._current_lease(task_id)
        if lease is None:
            raise QueueConflict("no active lease to cancel for task %s" % task_id)
        self._emit("cancel_requested", lease=lease, payload={"reason": reason})
        return {
            "task_id": task_id, "cancel_requested": True,
            "fencing_token": lease.fencing_token, "reason": reason,
        }

    def complete(self, lease: Lease, *, receipt_ref: str,
                 receipt: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        if not receipt_ref:
            raise ValueError("receipt_ref is required")
        canonical = self._mapper.build_completion_receipt(
            task_id=lease.task_id, agent_id=lease.agent_id,
            fencing_token=str(lease.fencing_token), receipt_ref=receipt_ref,
            extra=receipt,
        )
        result = self._mapper.complete(lease, receipt_ref=receipt_ref, receipt=canonical)
        result = {
            **result,
            "fencing_token": lease.fencing_token,
            "receipt_ref": receipt_ref,
            "agent": lease.identity or {"agent_id": lease.agent_id},
        }
        self._emit("completed", lease=lease, payload={
            "receipt_ref": receipt_ref, "receipt_verified": True,
        })
        return result

    def release(self, lease: Lease, *, reason: str = "handoff") -> Dict[str, Any]:
        result = self._mapper.release(lease, reason=reason)
        self._emit("released", lease=lease, payload={"reason": reason})
        return result

    def events(self, *, after: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for event in self._events_raw():
            if int(event.get("seq", 0)) <= after:
                continue
            body = event.get("payload") or {}
            if body.get("schema") != self._EVENT_SCHEMA:
                continue
            values.append({
                "seq": int(event["seq"]), "task_id": body.get("task_id", ""),
                "kind": event.get("event_type", ""), "agent_id": body.get("agent_id", "system"),
                "fencing_token": body.get("fencing_token"),
                "payload": body.get("payload") or {}, "created_at": event.get("created_at"),
            })
            if len(values) >= limit:
                break
        return values

    def task(self, task_id: str) -> Dict[str, Any]:
        value = self._mapper.task(task_id)
        state = str(value.get("state", ""))
        status = {"queued": "ready", "completed": "completed", "running": "claimed"}.get(state, state)
        lease = None
        for event in reversed(self._events_raw()):
            body = event.get("payload") or {}
            if body.get("schema") == self._EVENT_SCHEMA and body.get("task_id") == task_id:
                if event.get("event_type") == "claimed":
                    lease = body.get("lease")
                    break
                elif event.get("event_type") == "completed":
                    # The completing attempt's own lease/agent identity is exactly
                    # what proves no other concurrently-running attempt's fencing
                    # token or identity leaked onto this task -- keep it, not None.
                    # `receipt_ref` itself lives on the event's own payload (see
                    # `complete()`'s `_emit` call), not on the plain `Lease` shape,
                    # so merge it in for a caller inspecting the completed row.
                    lease = dict(body.get("lease") or {})
                    lease["receipt_ref"] = (body.get("payload") or {}).get("receipt_ref")
                    break
                elif event.get("event_type") == "released":
                    lease = None
                    break
        return {"task_id": task_id, "status": status, "payload": value.get("payload") or {}, "lease": lease}

def _is_loopback_host(host: str) -> bool:
    value = str(host or "").strip().lower().strip("[]")
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def tls_context_from_files(certfile: str, keyfile: str) -> ssl.SSLContext:
    if not certfile or not keyfile:
        raise ValueError("tls certfile and keyfile are both required")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=certfile, keyfile=keyfile)
    return context


def create_http_queue_server(queue: SQLiteRemoteQueue, host: str = "127.0.0.1", port: int = 0,
                             *, token: Optional[str] = None,
                             token_secret: Optional[str] = None,
                             token_scope: Optional[str] = None,
                             revocation_store: Optional[Path] = None,
                             ssl_context: Optional[ssl.SSLContext] = None,
                             audit_log_path: Optional[Path] = None) -> ThreadingHTTPServer:
    """Create a small authenticated HTTP facade over a transactional queue.

    The returned server is not started, allowing tests and embedding runtimes to
    choose a thread, process, or service manager. Non-loopback binds require an
    explicit TLS context.

    Two mutually exclusive auth modes (#289):

    * ``token`` -- legacy static bearer secret, compared verbatim. Never
      expires and cannot be individually revoked; kept only for local/dev use
      and backward compatibility.
    * ``token_secret`` (+ optional ``token_scope``/``revocation_store``) --
      short-lived credential mode (:mod:`scripts.short_lived_credentials`).
      Every request must present a token signed with ``token_secret`` that has
      not expired, is not before its ``nbf``, matches ``token_scope`` if given,
      and whose ``jti`` is not present in the revocation store. This is what
      closes "credential exchange is a bare static secret" without needing an
      OIDC broker.

      Operation-level scoping (#289): if the presented token carries an
      ``ops`` claim (see :func:`scripts.short_lived_credentials.issue_token`),
      it is checked against the specific queue operation in the request path
      (``pull``, ``claim``, ``complete``, ...) -- a token minted with
      ``operations=["pull"]`` is rejected on ``/claim`` or ``/complete`` even
      though its coarser ``scope`` claim matches. Tokens without an ``ops``
      claim are unaffected (legacy/unrestricted shape).

    A missing/invalid/expired/revoked bearer token is rejected (401) before
    any queue operation runs. Every accept/reject is appended to the #289
    audit log (:mod:`scripts.security_audit_log`) with the operation and
    auth mode, never the token itself.
    """
    if not _is_loopback_host(host) and ssl_context is None:
        raise ValueError("TLS is required for non-loopback queue binds")
    if token and token_secret:
        raise ValueError("token and token_secret are mutually exclusive auth modes")
    _verify_short_lived = None
    if token_secret:
        try:
            from scripts.short_lived_credentials import CredentialError, verify_token
        except ImportError as exc:  # pragma: no cover - installed package without scripts namespace
            raise RuntimeError("short-lived credential module unavailable") from exc

        def _verify_short_lived(presented: str, operation: str) -> bool:
            try:
                verify_token(token_secret, presented, expected_scope=token_scope,
                            expected_operation=operation,
                            revocation_store=revocation_store, audit_log_path=audit_log_path)
                return True
            except CredentialError:
                return False

    class Handler(BaseHTTPRequestHandler):
        server_version = "simplicio-queue/1"

        def log_message(self, *_args: Any) -> None:
            return

        def _send(self, status: int, value: Mapping[str, Any]) -> None:
            raw = json.dumps(dict(value), sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            value = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if not isinstance(value, dict):
                raise ValueError("request body must be an object")
            return value

        def do_POST(self) -> None:  # noqa: N802
            operation = self.path.rsplit("/", 1)[-1] if "/" in self.path else self.path
            auth_header = self.headers.get("Authorization", "")
            presented = auth_header[len("Bearer "):] if auth_header.startswith("Bearer ") else ""
            if token is not None and auth_header != "Bearer " + token:
                if _audit_append is not None:
                    _audit_append(audit_log_path, event="remote_queue.auth", decision="reject",
                                  operation=operation, reason="invalid static queue token")
                self._send(401, {"error": "invalid queue token"})
                return
            if _verify_short_lived is not None and not _verify_short_lived(presented, operation):
                # verify_token() already appended the detailed accept/reject
                # line (subject, jti, scope, operation, reason); nothing
                # further to log here since we only have a boolean.
                self._send(401, {"error": "invalid, expired, or revoked queue credential"})
                return
            if token is not None and _audit_append is not None:
                _audit_append(audit_log_path, event="remote_queue.auth", decision="accept",
                              operation=operation, reason="static queue token matched")
            if not self.path.startswith("/v1/queue/"):
                self._send(404, {"error": "unknown queue endpoint"})
                return
            try:
                body = self._body()
                op = self.path.rsplit("/", 1)[-1]
                if op == "enqueue":
                    queue.enqueue(body["task_id"], body.get("payload"))
                    result = {}
                elif op == "pull":
                    tasks = queue.pull(body["agent_id"], capabilities=body.get("capabilities"),
                                      limit=int(body.get("limit", 20)))
                    result = {"tasks": tasks}
                elif op == "claim":
                    lease = queue.claim(body["task_id"], body["agent_id"], idempotency_key=body["idempotency_key"],
                                        ttl=float(body.get("ttl", 60.0)), identity=body.get("identity"),
                                        capabilities=body.get("capabilities"))
                    result = {"lease": _lease_json(lease)}
                elif op == "heartbeat":
                    lease = queue.heartbeat(_lease_from_json(body["lease"]), ttl=float(body.get("ttl", 60.0)))
                    result = {"lease": _lease_json(lease)}
                elif op == "complete":
                    result = queue.complete(_lease_from_json(body["lease"]), receipt_ref=body["receipt_ref"],
                                            receipt=body.get("receipt"))
                elif op == "assert-active":
                    queue.assert_active(_lease_from_json(body["lease"]))
                    result = {"active": True}
                elif op == "cancel":
                    result = queue.request_cancel(body["task_id"], reason=body.get("reason", "cancelled"))
                elif op == "release":
                    result = queue.release(_lease_from_json(body["lease"]), reason=body.get("reason", "handoff"))
                elif op == "events":
                    result = {"events": queue.events(after=int(body.get("after", 0)), limit=int(body.get("limit", 100)))}
                elif op == "task":
                    result = queue.task(body["task_id"])
                else:
                    self._send(404, {"error": "unknown queue operation"})
                    return
                self._send(200, result)
            except QueueConflict as exc:
                self._send(409, {"error": str(exc)})
            except QueueUnavailable as exc:
                self._send(503, {"error": str(exc)})
            except KeyError as exc:
                self._send(404, {"error": str(exc)})
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                self._send(400, {"error": str(exc)})

    server = _QueueHTTPServer((host, port), Handler)
    if ssl_context is not None:
        server.socket = ssl_context.wrap_socket(server.socket, server_side=True)
    return server
