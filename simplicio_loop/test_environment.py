"""Loop-owned hermetic test-environment provisioning contract.

Providers submit declarative data to :class:`TestEnvironmentHub`; only the Hub
allocates ports/directories, starts supervised ``ProcessSpec`` services, issues
opaque secret references, and reconciles cleanup.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from .process_supervisor import ProcessLease, ProcessSpec

REQUEST_SCHEMA = "simplicio.test-environment-request/v1"
RECEIPT_SCHEMA = "simplicio.test-environment-receipt/v1"
CAPABILITY = "test_environment_v1"
BLOCKED_REASONS = frozenset({
    "INVALID_REQUEST", "NETWORK_POLICY", "PRODUCTION_TARGET", "QUOTA_EXHAUSTED",
    "PORT_UNAVAILABLE", "SERVICE_UNAVAILABLE", "UNSUPPORTED_VERSION", "CANCELLED",
})


class EnvironmentContractError(ValueError):
    def __init__(self, reason_code: str, detail: str):
        self.reason_code = reason_code
        super().__init__(detail)


@dataclass(frozen=True)
class ServiceDefinition:
    name: str
    versions: tuple[str, ...]
    command: Callable[[Mapping[str, Any], int, Path], tuple[str, ...]]
    requires_network: bool = False


@dataclass
class _Allocation:
    receipt: Dict[str, Any]
    roots: list[Path]
    sockets: list[socket.socket]
    leases: list[ProcessLease]
    handles: list[Any]


def extension_capability() -> Dict[str, Any]:
    """Handshake fragment advertised to quality extensions."""
    return {
        "schema": "simplicio.extension-capability/v1",
        "capability": CAPABILITY,
        "request_schema": REQUEST_SCHEMA,
        "receipt_schema": RECEIPT_SCHEMA,
        "authority": "loop",
        "provider_may_provision": False,
    }


class TestEnvironmentHub:
    """Central allocator; process launching is deliberately an injected Hub seam."""
    __test__ = False

    def __init__(self, root: str | Path, *, services: Mapping[str, ServiceDefinition],
                 launcher: Optional[Callable[[ProcessSpec, ProcessLease], Any]] = None,
                 max_services: int = 8, max_disk_bytes: int = 1 << 30) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.services = dict(services)
        self.launcher = launcher or self._launch
        self.max_services = max_services
        self.max_disk_bytes = max_disk_bytes
        self._active: Dict[str, _Allocation] = {}

    @staticmethod
    def _blocked(request: Mapping[str, Any], code: str, detail: str) -> Dict[str, Any]:
        assert code in BLOCKED_REASONS
        identity = request.get("identity") if isinstance(request, Mapping) else {}
        return {
            "schema": RECEIPT_SCHEMA, "status": "BLOCKED", "reason_code": code,
            "detail": detail, "identity": dict(identity or {}), "resources": [],
            "connections": {}, "secret_refs": [], "cleanup": {"status": "not_allocated"},
        }

    @staticmethod
    def validate(request: Mapping[str, Any]) -> None:
        if request.get("schema") != REQUEST_SCHEMA:
            raise EnvironmentContractError("INVALID_REQUEST", "unsupported request schema")
        identity = request.get("identity")
        required = ("run_id", "task_id", "attempt_id", "fence")
        if not isinstance(identity, Mapping) or any(not str(identity.get(k, "")).strip() for k in required):
            raise EnvironmentContractError("INVALID_REQUEST", "identity requires run/task/attempt/fence")
        services = request.get("services", [])
        if not isinstance(services, list) or not services:
            raise EnvironmentContractError("INVALID_REQUEST", "services must be a non-empty array")
        if request.get("network_policy", "offline") not in ("offline", "loopback"):
            raise EnvironmentContractError("NETWORK_POLICY", "only offline or loopback is allowed")
        if request.get("production") is not False:
            raise EnvironmentContractError("PRODUCTION_TARGET", "production must be explicitly false")
        allowed = {"name", "version", "ports", "health_probe", "volumes", "fixtures", "secrets"}
        for service in services:
            if not isinstance(service, Mapping) or set(service) - allowed:
                raise EnvironmentContractError("INVALID_REQUEST", "invalid service declaration")
            if "endpoint" in service or "host" in service:
                raise EnvironmentContractError("PRODUCTION_TARGET", "caller endpoints are forbidden")

    @staticmethod
    def _reserve_port() -> tuple[int, socket.socket]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1], sock

    @staticmethod
    def _launch(spec: ProcessSpec, lease: ProcessLease) -> subprocess.Popen:
        environment = {key: os.environ[key] for key in spec.env_allowlist if key in os.environ}
        environment.update(spec.env)
        return subprocess.Popen(spec.argv, cwd=spec.cwd, env=environment,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=os.name != "nt")

    def provision(self, request: Mapping[str, Any], *, cancel_event: Any = None) -> Dict[str, Any]:
        try:
            self.validate(request)
        except EnvironmentContractError as exc:
            return self._blocked(request, exc.reason_code, str(exc))
        services = request["services"]
        if len(services) > self.max_services:
            return self._blocked(request, "QUOTA_EXHAUSTED", "service cap exceeded")
        requested_disk = sum(int(v.get("max_bytes", 0)) for s in services for v in s.get("volumes", []))
        if requested_disk > self.max_disk_bytes:
            return self._blocked(request, "QUOTA_EXHAUSTED", "disk cap exceeded")
        identity = dict(request["identity"])
        allocation_id = uuid.uuid4().hex
        roots: list[Path] = []
        sockets: list[socket.socket] = []
        leases: list[ProcessLease] = []
        handles: list[Any] = []
        try:
            resources, connections, secret_refs = [], {}, []
            for index, item in enumerate(services):
                if cancel_event is not None and cancel_event.is_set():
                    raise EnvironmentContractError("CANCELLED", "environment allocation cancelled")
                definition = self.services.get(str(item.get("name", "")))
                if not definition:
                    raise EnvironmentContractError("SERVICE_UNAVAILABLE", f"service {item.get('name')} unavailable")
                version = str(item.get("version", ""))
                if version not in definition.versions:
                    raise EnvironmentContractError("UNSUPPORTED_VERSION", f"{definition.name} version {version} unsupported")
                if definition.requires_network and request["network_policy"] == "offline":
                    raise EnvironmentContractError("NETWORK_POLICY", f"{definition.name} requires network")
                service_root = Path(tempfile.mkdtemp(prefix=f"{allocation_id}-{index}-", dir=self.root))
                roots.append(service_root)
                port, reserved = self._reserve_port()
                sockets.append(reserved)
                lease = ProcessLease(f"env-{allocation_id}-{index}", "pending", ttl_seconds=float(request.get("lease_seconds", 60)))
                argv = definition.command(item, port, service_root)
                spec = ProcessSpec(argv=argv, cwd=str(service_root), cwd_allowlist=(str(self.root),),
                                   timeout_seconds=None, idempotency_key=lease.lease_id)
                lease.spec_hash = spec.spec_hash
                reserved.close(); sockets.remove(reserved)
                handle = self.launcher(spec, lease)
                handles.append(handle)
                leases.append(lease)
                connections[definition.name] = {"host": "127.0.0.1", "port": port, "scheme": "loopback"}
                for secret in item.get("secrets", []):
                    secret_refs.append({"name": str(secret), "ref": f"secret://{allocation_id}/{index}/{secret}", "expires_with_lease": lease.lease_id})
                resources.append({"service": definition.name, "version": version, "root": str(service_root),
                                  "lease_id": lease.lease_id, "process_spec_hash": spec.spec_hash,
                                  "handle": str(getattr(handle, "pid", "managed"))})
            fingerprint = hashlib.sha256(json.dumps({"identity": identity, "resources": resources}, sort_keys=True).encode()).hexdigest()
            receipt = {"schema": RECEIPT_SCHEMA, "status": "READY", "reason_code": None,
                       "allocation_id": allocation_id, "identity": identity, "network_policy": request["network_policy"],
                       "resources": resources, "connections": connections, "secret_refs": secret_refs,
                       "fingerprint": fingerprint, "cleanup": {"status": "pending", "leaks": None},
                       "created_at": time.time()}
            self._active[allocation_id] = _Allocation(receipt, roots, sockets, leases, handles)
            self._persist(receipt)
            return receipt
        except EnvironmentContractError as exc:
            self._rollback(roots, sockets, leases, handles)
            return self._blocked(request, exc.reason_code, str(exc))
        except OSError as exc:
            self._rollback(roots, sockets, leases, handles)
            return self._blocked(request, "PORT_UNAVAILABLE", str(exc))

    def _persist(self, receipt: Mapping[str, Any]) -> None:
        target = self.root / f"{receipt['allocation_id']}.json"
        target.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")

    def _rollback(self, roots: list[Path], sockets: list[socket.socket], leases: list[ProcessLease],
                  handles: list[Any]) -> None:
        for handle in handles:
            terminate = getattr(handle, "terminate", None)
            if callable(terminate):
                terminate()
        for lease in leases:
            lease.cancel()
        for sock in sockets:
            sock.close()
        for root in roots:
            shutil.rmtree(root, ignore_errors=True)

    def cleanup(self, allocation_id: str, *, cause: str = "success") -> Dict[str, Any]:
        allocation = self._active.pop(allocation_id, None)
        if allocation is None:
            return {"status": "CLEAN", "cause": cause, "leaks": [], "idempotent": True}
        self._rollback(allocation.roots, allocation.sockets, allocation.leases, allocation.handles)
        leaks = [str(root) for root in allocation.roots if root.exists()]
        result = {"status": "CLEAN" if not leaks else "LEAKED", "cause": cause, "leaks": leaks, "idempotent": False}
        allocation.receipt["cleanup"] = result
        self._persist(allocation.receipt)
        return result

    def reconcile(self) -> list[Dict[str, Any]]:
        """Crash recovery: clean every receipt whose cleanup was not proven."""
        results = []
        for path in self.root.glob("*.json"):
            receipt = json.loads(path.read_text(encoding="utf-8"))
            if receipt.get("cleanup", {}).get("status") == "pending":
                for resource in receipt.get("resources", []):
                    shutil.rmtree(resource.get("root", ""), ignore_errors=True)
                leaks = [r["root"] for r in receipt.get("resources", []) if Path(r["root"]).exists()]
                receipt["cleanup"] = {"status": "CLEAN" if not leaks else "LEAKED", "cause": "crash_reconcile", "leaks": leaks}
                path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
                results.append(receipt["cleanup"])
        return results
