"""Real, un-mocked two-*machine-shaped*-process proof over an actual HTTP socket (issue #286).

``tests/test_remote_worker_e2e.py`` proves the claim/heartbeat/crash/handoff/cancel contract
with two real OS processes sharing one SQLite file -- the closest local proxy for two devices
when they can share a disk. This file removes even that: **three** independent real OS
processes, none of which ever touches the SQLite file directly.

  * one process is ``scripts/remote_queue_server.py`` -- a real HTTP server bound to
    ``127.0.0.1`` on an OS-assigned port, the "coordinator device" that owns the queue.
  * one process is a worker (``scripts/remote_worker_daemon.py claim --http URL``) -- a real
    HTTP *client* hitting that server over an actual loopback TCP socket, the "remote device".
  * a second, later worker process repeats the claim over the same real socket to prove
    fencing/rejection/reclaim work identically over the wire as they do over SQLite.

Every claim, heartbeat, cancel, and complete in this test crosses a real ``127.0.0.1`` TCP
connection between two separate processes -- never an in-process call, never a mock transport.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.satellite,
    pytest.mark.skipif(
        sys.platform == "darwin",
        reason="real HTTP worker crash and lease handoff is Linux-specific",
    ),
]

from simplicio_loop.remote_queue import HTTPRemoteQueue

REPO_ROOT = Path(__file__).resolve().parent.parent
DAEMON = REPO_ROOT / "scripts" / "remote_worker_daemon.py"
SERVER = REPO_ROOT / "scripts" / "remote_queue_server.py"
TOKEN = "http-e2e-shared-secret"  # noqa: secret -- fixed test-fixture bearer token, not a real credential


def _spawn(*args: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(DAEMON), *args],
        cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        stdin=subprocess.DEVNULL,
    )


def _spawn_server(db: Path):
    proc = subprocess.Popen(
        [sys.executable, str(SERVER), "--db", str(db), "--host", "127.0.0.1", "--port", "0",
         "--token", TOKEN],
        cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        stdin=subprocess.DEVNULL,
    )
    line = proc.stdout.readline()
    match = re.search(r":(\d+)\s*$", line.strip())
    if not match:
        proc.kill()
        raise RuntimeError(f"server did not print its bound port; line={line!r} stderr={proc.stderr.read()}")
    return proc, int(match.group(1))


def _read_status(path: Path, *, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                last_error = exc
        time.sleep(0.05)
    raise TimeoutError(f"status file {path} never became readable: {last_error}")


def _wait_for_state(path: Path, states: set[str], *, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        if path.exists():
            try:
                last = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                last = None
        if last is not None and last.get("state") in states:
            return last
        time.sleep(0.05)
    raise TimeoutError(f"status file {path} never reached one of {states}; last seen: {last}")


@pytest.fixture
def http_server(tmp_path):
    proc, port = _spawn_server(tmp_path / "http-e2e-queue.db")
    try:
        yield f"http://127.0.0.1:{port}", tmp_path
    finally:
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def test_claim_heartbeat_crash_handoff_over_real_http_socket(http_server):
    """Same crash/handoff proof as the SQLite E2E, but every mutation crosses a real HTTP
    socket to a real, separate server process instead of a shared file."""
    url, tmp_path = http_server
    status_a = tmp_path / "worker-a.status.json"
    status_b1 = tmp_path / "worker-b-early.status.json"
    status_b2 = tmp_path / "worker-b-final.status.json"

    # Enqueue is itself a real, independent process hitting the server over HTTP -- not the
    # test process reaching into the SQLite file.
    proc_enqueue = _spawn("enqueue", "--http", url, "--token", TOKEN, "--task-id", "HTTP-286-E2E",
                          "--payload", json.dumps({"goal": "prove real HTTP two-process handoff"}))
    assert proc_enqueue.wait(timeout=10) == 0, proc_enqueue.stderr.read()

    proc_a = _spawn(
        "claim", "--http", url, "--token", TOKEN, "--agent-id", "agent-a", "--task-id", "HTTP-286-E2E",
        "--idempotency-key", "http:a", "--ttl", "1.5", "--heartbeat-interval", "0.3",
        "--hold-seconds", "30", "--receipt-ref", "receipts/HTTP-286-E2E.json",
        "--status-file", str(status_a),
    )
    try:
        status = _wait_for_state(status_a, {"running"}, timeout=10.0)
        assert status["claimed"] is True
        crashed_fencing_token = status["fencing_token"]

        # A second real process, over the same real socket, is rejected while A's lease holds.
        proc_b_early = _spawn(
            "claim", "--http", url, "--token", TOKEN, "--agent-id", "agent-b", "--task-id", "HTTP-286-E2E",
            "--idempotency-key", "http:b-early", "--ttl", "5", "--heartbeat-interval", "0.5",
            "--hold-seconds", "1", "--receipt-ref", "receipts/never.json",
            "--status-file", str(status_b1),
        )
        rc_early = proc_b_early.wait(timeout=10)
        assert rc_early == 3, proc_b_early.stderr.read()
        early_status = _read_status(status_b1)
        assert early_status["claimed"] is False

        # Real crash: kill process A mid-task with no graceful release.
        proc_a.kill()
        proc_a.wait(timeout=10)
    finally:
        if proc_a.poll() is None:
            proc_a.kill()
            proc_a.wait(timeout=10)

    # Verified over the real HTTP client too -- the server (a distinct process) is still the
    # sole authority on task state.
    client = HTTPRemoteQueue(url, token=TOKEN, timeout=10)
    assert client.task("HTTP-286-E2E")["status"] == "claimed"

    deadline = time.monotonic() + 15.0
    rc_final = None
    while time.monotonic() < deadline:
        proc_b_final = _spawn(
            "claim", "--http", url, "--token", TOKEN, "--agent-id", "agent-b", "--task-id", "HTTP-286-E2E",
            "--idempotency-key", "http:b-final-%d" % int(time.monotonic() * 1000),
            "--ttl", "5", "--heartbeat-interval", "0.3", "--hold-seconds", "0.5",
            "--receipt-ref", "receipts/HTTP-286-E2E.json", "--status-file", str(status_b2),
        )
        rc_final = proc_b_final.wait(timeout=15)
        if rc_final == 0:
            break
        time.sleep(0.2)
    assert rc_final == 0, proc_b_final.stderr.read()
    final_status = _read_status(status_b2)
    assert final_status["claimed"] is True
    assert final_status["state"] == "completed"

    final_task = client.task("HTTP-286-E2E")
    assert final_task["status"] == "completed"
    assert final_task["lease"]["agent_id"] == "agent-b"
    # Fencing tokens are opaque, distinct identifiers (simplicio-mapper's operations
    # store mints them as uuid4 hex, not a monotonic counter) -- the genuinely-new-lease
    # proof is that the post-crash reclaim's token is not the crashed attempt's token.
    assert final_task["lease"]["fencing_token"] != crashed_fencing_token


def test_cooperative_cancellation_over_real_http_socket(http_server):
    """A third real process cancels a task; the claimant (a fourth real process, over the
    same real socket) observes it on its next heartbeat and releases -- no kill involved."""
    url, tmp_path = http_server
    status_a = tmp_path / "worker-a.status.json"

    proc_enqueue = _spawn("enqueue", "--http", url, "--token", TOKEN, "--task-id", "HTTP-286-CANCEL",
                          "--payload", json.dumps({"goal": "prove real HTTP cooperative cancellation"}))
    assert proc_enqueue.wait(timeout=10) == 0, proc_enqueue.stderr.read()

    proc_a = _spawn(
        "claim", "--http", url, "--token", TOKEN, "--agent-id", "agent-a", "--task-id", "HTTP-286-CANCEL",
        "--idempotency-key", "http:cancel-a", "--ttl", "5", "--heartbeat-interval", "0.2",
        "--hold-seconds", "30", "--receipt-ref", "receipts/never.json",
        "--status-file", str(status_a),
    )
    try:
        _wait_for_state(status_a, {"running"}, timeout=10.0)

        proc_cancel = _spawn("cancel", "--http", url, "--token", TOKEN, "--task-id", "HTTP-286-CANCEL",
                             "--reason", "operator requested stop")
        rc_cancel = proc_cancel.wait(timeout=10)
        assert rc_cancel == 0, proc_cancel.stderr.read()

        rc_a = proc_a.wait(timeout=10)
        assert rc_a == 2
    finally:
        if proc_a.poll() is None:
            proc_a.kill()
            proc_a.wait(timeout=10)

    final_status = _read_status(status_a)
    assert final_status["state"] == "cancelled"

    client = HTTPRemoteQueue(url, token=TOKEN, timeout=10)
    assert client.task("HTTP-286-CANCEL")["status"] == "ready"


if __name__ == "__main__":
    import os
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_remote_worker_http_e2e")
