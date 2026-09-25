"""Real, un-mocked two-process end-to-end proof for issue #286.

Two *actual OS processes* (``subprocess.Popen``, not two threads sharing an
interpreter) run ``scripts/remote_worker_daemon.py`` against one shared SQLite queue
file. This proves the full remaining #286 promise in one pass:

  1. process A claims a task and starts heartbeating it,
  2. process B tries to claim the same task while A's lease is alive and is rejected,
  3. process A is killed mid-task (``proc.kill()`` -- a real crash, no graceful
     shutdown / no release call), so its lease is abandoned rather than released,
  4. once A's lease TTL genuinely expires, process B successfully claims the same
     task and completes it.

No component here is mocked: the queue is a real SQLite file on disk, the workers are
real Python processes started with ``subprocess.Popen``, and the "crash" is a real
``SIGKILL``/``TerminateProcess`` on a live process, not a simulated exception.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

pytestmark = [
    pytest.mark.satellite,
    pytest.mark.skipif(
        sys.platform == "darwin",
        reason="real process crash and lease handoff is Linux-specific",
    ),
]
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DAEMON = REPO_ROOT / "scripts" / "remote_worker_daemon.py"


def _read_status(path: Path, *, timeout: float = 5.0) -> dict:
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


def _spawn(*args: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(DAEMON), *args],
        cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        stdin=subprocess.DEVNULL,
    )


def test_two_real_processes_crash_and_lease_expiry_handoff(tmp_path):
    db = tmp_path / "shared-queue.db"
    status_a = tmp_path / "worker-a.status.json"
    status_b1 = tmp_path / "worker-b-early.status.json"
    status_b2 = tmp_path / "worker-b-final.status.json"

    from simplicio_loop.remote_queue import SQLiteRemoteQueue
    queue = SQLiteRemoteQueue(str(db))
    queue.enqueue("WI-286-E2E", {"goal": "prove real two-process handoff"})

    # 1) Process A claims the task and holds it for longer than we'll wait before
    # killing it -- a real crash, mid-task, not a graceful shutdown.
    proc_a = _spawn(
        "claim", "--db", str(db), "--agent-id", "agent-a", "--task-id", "WI-286-E2E",
        "--idempotency-key", "run:a", "--ttl", "1.5", "--heartbeat-interval", "0.3",
        "--hold-seconds", "30", "--receipt-ref", "receipts/WI-286-E2E.json",
        "--status-file", str(status_a),
    )
    try:
        status = _wait_for_state(status_a, {"running"}, timeout=10.0)
        assert status["claimed"] is True
        crashed_fencing_token = status["fencing_token"]

        # 2) Process B tries to claim the same task while A's lease is alive: rejected.
        proc_b_early = _spawn(
            "claim", "--db", str(db), "--agent-id", "agent-b", "--task-id", "WI-286-E2E",
            "--idempotency-key", "run:b-early", "--ttl", "5", "--heartbeat-interval", "0.5",
            "--hold-seconds", "1", "--receipt-ref", "receipts/never.json",
            "--status-file", str(status_b1),
        )
        rc_early = proc_b_early.wait(timeout=10)
        assert rc_early == 3, proc_b_early.stderr.read()
        early_status = _read_status(status_b1)
        assert early_status["claimed"] is False

        # 3) Kill process A mid-task -- a real crash: no graceful release, the lease is
        # simply abandoned and must expire on its own.
        proc_a.kill()
        proc_a.wait(timeout=10)
    finally:
        if proc_a.poll() is None:
            proc_a.kill()
            proc_a.wait(timeout=10)

    # The task must still be "claimed" (not "ready") immediately after the crash --
    # a killed process cannot have released it gracefully.
    assert queue.task("WI-286-E2E")["status"] == "claimed"

    # 4) Once A's 1.5s TTL genuinely expires, process B claims and completes the task.
    # A's lease was last heartbeat/claimed up to ~1.5s before the kill; wait that out
    # for real (no mocking of time) before retrying the claim as an independent process.
    deadline = time.monotonic() + 15.0
    rc_final = None
    while time.monotonic() < deadline:
        proc_b_final = _spawn(
            "claim", "--db", str(db), "--agent-id", "agent-b", "--task-id", "WI-286-E2E",
            "--idempotency-key", "run:b-final-%d" % int(time.monotonic() * 1000),
            "--ttl", "5", "--heartbeat-interval", "0.3", "--hold-seconds", "0.5",
            "--receipt-ref", "receipts/WI-286-E2E.json", "--status-file", str(status_b2),
        )
        rc_final = proc_b_final.wait(timeout=15)
        if rc_final == 0:
            break
        time.sleep(0.2)
    assert rc_final == 0, proc_b_final.stderr.read()
    final_status = _read_status(status_b2)
    assert final_status["claimed"] is True
    assert final_status["state"] == "completed"

    final_task = queue.task("WI-286-E2E")
    assert final_task["status"] == "completed"
    assert final_task["lease"]["agent_id"] == "agent-b"
    # Fencing tokens are opaque, distinct identifiers (simplicio-mapper's operations
    # store mints them as uuid4 hex, not a monotonic counter) -- the genuinely-new-lease
    # proof is that the post-crash reclaim's token is not the crashed attempt's token.
    assert final_task["lease"]["fencing_token"] != crashed_fencing_token


def test_two_real_processes_cooperative_cancellation(tmp_path):
    """A separate real-process proof for cancellation: process A claims and holds a
    task; a `cancel` invocation (a third real process) flags it; process A observes the
    cancellation on its next heartbeat, aborts its work, and releases the task -- all
    without being killed."""
    db = tmp_path / "shared-queue.db"
    status_a = tmp_path / "worker-a.status.json"

    from simplicio_loop.remote_queue import SQLiteRemoteQueue
    queue = SQLiteRemoteQueue(str(db))
    queue.enqueue("WI-286-CANCEL", {"goal": "prove real cooperative cancellation"})

    proc_a = _spawn(
        "claim", "--db", str(db), "--agent-id", "agent-a", "--task-id", "WI-286-CANCEL",
        "--idempotency-key", "run:cancel-a", "--ttl", "5", "--heartbeat-interval", "0.2",
        "--hold-seconds", "30", "--receipt-ref", "receipts/never.json",
        "--status-file", str(status_a),
    )
    try:
        _wait_for_state(status_a, {"running"}, timeout=10.0)

        proc_cancel = _spawn("cancel", "--db", str(db), "--task-id", "WI-286-CANCEL",
                             "--reason", "operator requested stop")
        rc_cancel = proc_cancel.wait(timeout=10)
        assert rc_cancel == 0, proc_cancel.stderr.read()

        rc_a = proc_a.wait(timeout=10)
        assert rc_a == 2  # the CLI's cancelled exit code
    finally:
        if proc_a.poll() is None:
            proc_a.kill()
            proc_a.wait(timeout=10)

    final_status = _read_status(status_a)
    assert final_status["state"] == "cancelled"
    assert queue.task("WI-286-CANCEL")["status"] == "ready"
