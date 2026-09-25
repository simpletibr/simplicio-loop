"""Epic #498 end-to-end: ProcessSpec through the real Hub IPC boundary.

Proves the "unica fronteira" (single boundary) claim across the pieces that #514 (ProcessSpec/
Lease contract) and #516 (enforcement/observability registry) each landed in isolation, by
driving them together through ``HubDaemon.handle(method="execute")`` -- the real IPC path a
client actually calls, not ``process_supervisor`` called directly. (The previously optional
Rust/Tokio backend, #515, was removed in #1298 -- 100% Python -- so the pure-Python adapter is
now the only backend.)

Two things are proven, both against a real spawned OS process (not a mock):

1. A ProcessSpec submitted via ``execute`` runs to completion through the pure-Python adapter.
2. While that process is alive, it is visible in the enforcement layer's ``ProcessRegistry`` --
   i.e. the Hub's execute path now registers the real pid with the same bookkeeping
   ``process_enforcement.detect_unsupervised`` diffs against -- and is unregistered the moment
   ``execute`` returns. A spec deliberately not routed through Hub (spawned by hand) is used as a
   negative control to show the registry only reflects Hub-supervised pids, not every process on
   the host.
"""

import sys
import time
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.satellite,
    pytest.mark.skipif(
        sys.platform == "darwin",
        reason="real process supervision depends on Linux process semantics",
    ),
]

from simplicio_loop.hub_daemon import HubDaemon, HubEnvelope
from simplicio_loop.process_enforcement import ProcessRegistry


SLEEP_SPEC = {
    "argv": [sys.executable, "-c", "import time; time.sleep(1.2)"],
    "timeout_seconds": 10.0,
}


def _daemon(tmp_path: Path) -> HubDaemon:
    daemon = HubDaemon(str(tmp_path / "hub.lock"))
    daemon.start()
    return daemon


def test_execute_through_hub_ipc_python_backend(tmp_path) -> None:
    daemon = _daemon(tmp_path)
    try:
        response = daemon.handle(
            HubEnvelope("req-py", "execute", {"process_spec": {
                "argv": [sys.executable, "-c", "print('py-backend-ok')"],
                "timeout_seconds": 10.0,
            }})
        )
        assert response["ok"] is True
        assert response["backend"] == "python"
        assert response["result"]["returncode"] == 0
        assert "py-backend-ok" in response["result"]["stdout"]
    finally:
        daemon.stop()


def _run_execute_in_background(daemon: HubDaemon, request_id: str):
    import threading

    holder: dict = {}

    def _worker() -> None:
        holder["response"] = daemon.handle(
            HubEnvelope(request_id, "execute", {"process_spec": dict(SLEEP_SPEC)})
        )

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread, holder


def test_hub_executed_process_is_visible_to_enforcement_registry_while_running(
    tmp_path, monkeypatch
) -> None:
    registry_path = tmp_path / "registry.json"
    registry = ProcessRegistry(registry_path)
    daemon = HubDaemon(str(tmp_path / "hub.lock"), process_registry=registry)
    daemon.start()
    try:
        thread, holder = _run_execute_in_background(daemon, "req-sleep")
        deadline = time.monotonic() + 5
        seen_active = False
        while time.monotonic() < deadline and not seen_active:
            if registry.active_pids():
                seen_active = True
                break
            time.sleep(0.05)
        assert seen_active, "expected the hub-executed pid to appear in the registry while running"

        thread.join(timeout=10)
        assert "response" in holder
        assert holder["response"]["ok"] is True
        assert holder["response"]["result"]["returncode"] == 0

        assert registry.active_pids() == set(), (
            "registry must unregister the pid once HubDaemon.handle(execute) returns"
        )
    finally:
        daemon.stop()


def test_hub_cancel_kills_an_in_flight_execute_for_real(tmp_path, monkeypatch) -> None:
    """The Hub's ``cancel`` IPC method used to only flip a *queue job*'s state -- it never
    touched a real OS process, so an in-flight ``execute`` (synchronous, blocking) had no way to
    be cancelled from a different thread/connection while it was still running. This proves the
    fix: a ``cancel`` request carrying the ``lease_id`` an ``execute`` response reports kills the
    real, still-running process tree, and the blocked ``execute`` call returns promptly instead
    of running to completion."""
    import threading

    registry_path = tmp_path / "registry.json"
    registry = ProcessRegistry(registry_path)
    daemon = HubDaemon(str(tmp_path / "hub.lock"), process_registry=registry)
    daemon.start()
    try:
        long_sleep_spec = {
            "argv": [sys.executable, "-c", "import time; time.sleep(30)"],
            "timeout_seconds": 60.0,
        }
        holder: dict = {}

        def _worker() -> None:
            holder["response"] = daemon.handle(
                HubEnvelope("req-cancel-me", "execute", {"process_spec": long_sleep_spec})
            )

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        # Predictable lease_id: no idempotency_key was set, so the Hub falls back to
        # f"hub-execute-{request_id}" (see HubDaemon.handle's "execute" branch).

        deadline = time.monotonic() + 5
        seen_active = False
        while time.monotonic() < deadline and not seen_active:
            if registry.active_pids():
                seen_active = True
                break
            time.sleep(0.05)
        assert seen_active, "expected the hub-executed pid to appear in the registry while running"

        cancel_response = daemon.handle(
            HubEnvelope("req-cancel-me-cancel", "cancel", {"lease_id": "hub-execute-req-cancel-me"})
        )
        assert cancel_response["ok"] is True
        assert cancel_response["process"]["found"] is True
        assert cancel_response["process"]["killed"] is True

        thread.join(timeout=5)
        assert "response" in holder, "cancel must unblock the in-flight execute promptly"
        result = holder["response"]["result"]
        assert result["returncode"] != 0, "a killed process must not report a clean exit"

        assert registry.active_pids() == set(), (
            "registry must unregister the pid once the cancelled execute call returns"
        )
    finally:
        daemon.stop()


def test_hub_cancel_with_unknown_lease_id_is_a_no_op_not_an_error(tmp_path, monkeypatch) -> None:
    daemon = HubDaemon(str(tmp_path / "hub.lock"))
    daemon.start()
    try:
        response = daemon.handle(
            HubEnvelope("req-noop-cancel", "cancel", {"lease_id": "no-such-lease"})
        )
        assert response["ok"] is True
        assert response["process"]["found"] is False
        assert response["process"]["killed"] is False
    finally:
        daemon.stop()


def test_registry_does_not_track_processes_spawned_outside_the_hub(tmp_path) -> None:
    import subprocess

    registry_path = tmp_path / "registry.json"
    registry = ProcessRegistry(registry_path)
    outside = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
    try:
        assert outside.pid not in registry.active_pids()
    finally:
        outside.wait(timeout=5)
