import json
import socket
import threading
import sys
from pathlib import Path

import pytest

from simplicio_loop.test_environment import (
    CAPABILITY, REQUEST_SCHEMA, ServiceDefinition, TestEnvironmentHub,
    extension_capability,
)


class Handle:
    pid = 123
    def __init__(self): self.terminated = False
    def terminate(self): self.terminated = True


def command(item, port, root):
    return ("python3", "-c", "pass", str(port), str(root))


def request(*services, network="offline", production=False, **extra):
    value = {
        "schema": REQUEST_SCHEMA,
        "identity": {"run_id": "r1", "task_id": "t1", "attempt_id": "a1", "fence": "7"},
        "production": production, "network_policy": network,
        "services": list(services) or [{"name": "database", "version": "1", "secrets": ["password"]}],
    }
    value.update(extra)
    return value


@pytest.fixture
def hub(tmp_path):
    handles = []
    def launch(spec, lease):
        assert spec.shell is False and spec.idempotency_key == lease.lease_id
        handle = Handle(); handles.append(handle); return handle
    instance = TestEnvironmentHub(tmp_path, services={
        name: ServiceDefinition(name, ("1",), command)
        for name in ("database", "broker", "browser")
    }, launcher=launch)
    instance.handles = handles
    return instance


def test_happy_path_real_disposable_fixtures_and_cleanup(hub):
    receipt = hub.provision(request(
        {"name": "database", "version": "1", "volumes": [{"max_bytes": 1024}], "secrets": ["password"]},
        {"name": "broker", "version": "1"}, {"name": "browser", "version": "1"}, network="loopback"))
    assert receipt["status"] == "READY"
    assert len(receipt["resources"]) == 3 and len(set(x["lease_id"] for x in receipt["resources"])) == 3
    assert all(c["host"] == "127.0.0.1" for c in receipt["connections"].values())
    wire = json.dumps(receipt)
    assert "password" in wire and "secret://" in wire
    assert not any(k in wire for k in ("hunter2", "secret-value"))
    roots = [Path(x["root"]) for x in receipt["resources"]]
    assert all(p.exists() for p in roots)
    cleanup = hub.cleanup(receipt["allocation_id"], cause="success")
    assert cleanup["status"] == "CLEAN" and not any(p.exists() for p in roots)
    assert all(h.terminated for h in hub.handles)
    assert hub.cleanup(receipt["allocation_id"], cause="retry")["idempotent"] is True


@pytest.mark.parametrize("cause", ["failure", "timeout", "cancellation"])
def test_all_terminal_paths_prove_cleanup(hub, cause):
    receipt = hub.provision(request())
    assert hub.cleanup(receipt["allocation_id"], cause=cause) == {
        "status": "CLEAN", "cause": cause, "leaks": [], "idempotent": False}


def test_crash_reconciliation_and_leak_regression(hub):
    receipt = hub.provision(request())
    root = Path(receipt["resources"][0]["root"])
    restarted = TestEnvironmentHub(hub.root, services={})
    result = restarted.reconcile()
    assert result == [{"status": "CLEAN", "cause": "crash_reconcile", "leaks": []}]
    assert not root.exists() and restarted.reconcile() == []


@pytest.mark.parametrize("patch,code", [
    ({"schema": "bad"}, "INVALID_REQUEST"),
    ({"production": True}, "PRODUCTION_TARGET"),
    ({"network_policy": "internet"}, "NETWORK_POLICY"),
])
def test_fail_closed_policy(hub, patch, code):
    value = request(); value.update(patch)
    assert hub.provision(value)["reason_code"] == code


def test_unsupported_unavailable_and_network_service(tmp_path):
    hub = TestEnvironmentHub(tmp_path, services={"online": ServiceDefinition("online", ("1",), command, True)})
    assert hub.provision(request({"name": "missing", "version": "1"}))["reason_code"] == "SERVICE_UNAVAILABLE"
    assert hub.provision(request({"name": "online", "version": "2"}))["reason_code"] == "UNSUPPORTED_VERSION"
    assert hub.provision(request({"name": "online", "version": "1"}))["reason_code"] == "NETWORK_POLICY"


def test_disk_quota_exhaustion_blocks_the_allocation(tmp_path):
    hub = TestEnvironmentHub(
        tmp_path, services={"database": ServiceDefinition("database", ("1",), command)}, max_disk_bytes=10,
    )
    blocked = hub.provision(request({"name": "database", "version": "1", "volumes": [{"max_bytes": 11}]}))
    assert blocked["reason_code"] == "QUOTA_EXHAUSTED"
    assert blocked["resources"] == []


def test_port_collision_is_central_and_machine_readable(hub, monkeypatch):
    def collision():
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); sock.close()
        raise OSError("collision")
    monkeypatch.setattr(hub, "_reserve_port", collision)
    assert hub.provision(request())["reason_code"] == "PORT_UNAVAILABLE"


def test_cross_run_isolation_and_handshake(hub):
    first = hub.provision(request())
    second_req = request(); second_req["identity"]["run_id"] = "r2"
    second = hub.provision(second_req)
    assert first["allocation_id"] != second["allocation_id"]
    assert first["resources"][0]["root"] != second["resources"][0]["root"]
    cap = extension_capability()
    assert cap["capability"] == CAPABILITY and cap["authority"] == "loop"
    assert cap["provider_may_provision"] is False


def test_pre_cancel_does_not_allocate(hub):
    cancelled = threading.Event(); cancelled.set()
    receipt = hub.provision(request(), cancel_event=cancelled)
    assert receipt["status"] == "BLOCKED" and receipt["reason_code"] == "CANCELLED"
    assert list(hub.root.glob("*-*")) == []


def test_system_default_launcher_supervises_real_disposable_process(tmp_path):
    service = ServiceDefinition(
        "database", ("1",),
        lambda item, port, root: (sys.executable, "-c", "import time; time.sleep(60)"),
    )
    hub = TestEnvironmentHub(tmp_path, services={"database": service})
    receipt = hub.provision(request())
    assert receipt["status"] == "READY" and int(receipt["resources"][0]["handle"]) > 0
    handle = hub._active[receipt["allocation_id"]].handles[0]
    assert handle.poll() is None
    assert hub.cleanup(receipt["allocation_id"], cause="system_e2e")["status"] == "CLEAN"
    handle.wait(timeout=5)


def test_schema_files_validate_contract():
    jsonschema = pytest.importorskip("jsonschema")
    base = Path(__file__).parents[1] / "simplicio_loop" / "_contracts" / "test-environment" / "v1"
    req_schema = json.loads((base / "request.schema.json").read_text())
    receipt_schema = json.loads((base / "receipt.schema.json").read_text())
    jsonschema.validate(request(), req_schema)
    blocked = TestEnvironmentHub._blocked(request(), "CANCELLED", "cancelled")
    jsonschema.validate(blocked, receipt_schema)
