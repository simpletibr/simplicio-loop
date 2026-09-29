"""Chaos coverage for issue #288's restart/recovery gap, one level up from
``tests/test_work_item_claims_run_guarded.py`` (which proves ``run_guarded`` kills its own
child subprocess on lease loss). Here the *whole worker process* is killed -- not merely its
guarded subprocess -- simulating a real crash/OOM-kill/eviction with no graceful release, no
final heartbeat, nothing. This proves the fencing/lease design survives that, end to end:

  1. A real, separate Python **process** claims a work item against a shared on-disk SQLite
     queue and then goes silent (no heartbeat) -- simulating a worker that crashed mid-task.
  2. The parent test **kills that process** (``proc.kill()`` -- SIGKILL-equivalent, no chance
     to run cleanup code), well before the lease TTL would naturally expire from inactivity.
  3. Once the TTL elapses, a **second claimant** (different identity, same queue) can claim
     the same work item -- recovery works, nothing is stuck.
  4. The second claimant completes the work item for real.
  5. The **first (dead) worker's lease can never complete anything** afterward: replaying its
     exact lease/fencing token against ``complete()`` raises ``QueueConflict`` -- proving no
     double-completion is possible even if the killed process had a zombie thread or a retry
     queued up somewhere that eventually fired.
  6. The queue's own event log shows the work item completed **exactly once**, by the second
     claimant's fencing token -- not two completions racing.
"""
import json
import subprocess
import sys
import time

import pytest

from simplicio_loop.remote_queue import QueueConflict, SQLiteRemoteQueue
from simplicio_loop.work_item_claims import AttemptCoordinator

pytestmark = pytest.mark.usefixtures("admitting_capacity")  # host pressure must not decide these dispatch tests

IDENTITY_A = {
    "agent_id": "codex@device-a", "runtime": "codex", "device_id": "device-a",
    "session_id": "session-a", "capabilities": ["claim", "heartbeat", "fencing", "receipts", "events"],
}
IDENTITY_B = {
    "agent_id": "claude@device-b", "runtime": "claude", "device_id": "device-b",
    "session_id": "session-b", "capabilities": ["claim", "heartbeat", "fencing", "receipts", "events"],
}

_CRASHED_WORKER_SCRIPT = r"""
import json, sys, time
sys.path.insert(0, %(repo_root)r)
from simplicio_loop.remote_queue import SQLiteRemoteQueue
from simplicio_loop.work_item_claims import AttemptCoordinator

queue = SQLiteRemoteQueue(%(db_path)r)
coordinator = AttemptCoordinator(queue, run_id=%(run_id)r)
attempt = coordinator.claim(work_item_id=%(work_item_id)r, identity=%(identity)s, goal="mutate", ttl=%(ttl)r)
with open(%(handoff_path)r, "w", encoding="utf-8") as fh:
    json.dump({
        "task_id": attempt.lease.task_id, "agent_id": attempt.lease.agent_id,
        "lease_id": attempt.lease.lease_id, "fencing_token": attempt.lease.fencing_token,
        "expires_at": attempt.lease.expires_at, "idempotency_key": attempt.lease.idempotency_key,
        "identity": attempt.lease.identity, "capabilities": list(attempt.lease.capabilities),
    }, fh)
print("CLAIMED", flush=True)
# Simulate a crash: go silent forever, no heartbeat, no graceful release. The parent test
# kills this process well before this sleep would ever return.
time.sleep(300)
"""


def _lease_from_handoff(handoff):
    from simplicio_loop.remote_queue import Lease
    return Lease(
        handoff["task_id"], handoff["agent_id"], handoff["lease_id"], handoff["fencing_token"],
        handoff["expires_at"], handoff["idempotency_key"], handoff["identity"],
        tuple(handoff["capabilities"]),
    )


def test_killed_worker_process_loses_lease_and_second_claimant_recovers_with_no_double_completion(tmp_path):
    import os

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = str(tmp_path / "queue.db")
    handoff_path = str(tmp_path / "handoff.json")
    run_id = "run-chaos-1"
    work_item_id = "WI-CHAOS-1"
    ttl = 2.0  # short TTL so the test doesn't need to wait long for expiry

    script = _CRASHED_WORKER_SCRIPT % {
        "repo_root": repo_root, "db_path": db_path, "run_id": run_id,
        "work_item_id": work_item_id, "identity": IDENTITY_A, "ttl": ttl,
        "handoff_path": handoff_path,
    }

    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        # Wait for the child to confirm it actually claimed the lease before we kill it --
        # otherwise we'd just be testing "process never started", not "crash mid-task".
        deadline = time.time() + 10.0
        claimed_line = ""
        while time.time() < deadline:
            line = proc.stdout.readline()
            if line:
                claimed_line = line.strip()
                if claimed_line == "CLAIMED":
                    break
        assert claimed_line == "CLAIMED", "child worker never confirmed its claim: %r" % claimed_line

        with open(handoff_path, encoding="utf-8") as fh:
            handoff = json.load(fh)
        assert handoff["task_id"] == work_item_id
        first_fencing_token = handoff["fencing_token"]

        # The crash: kill the process outright. No SIGTERM handler, no release(), no final
        # heartbeat -- exactly the scenario the epic's DoD gap names ("um worker pode perder o
        # lease e continuar alterando", generalized to "a worker can die and never come back").
        proc.kill()
        proc.wait(timeout=10)
    finally:
        try:
            proc.kill()
        except Exception:
            pass

    # Give the TTL time to actually elapse (real wall-clock expiry, not a mocked clock --
    # this is the one piece of real waiting the chaos test needs to stay honest).
    time.sleep(ttl + 0.5)

    queue = SQLiteRemoteQueue(db_path)

    # Recovery: a second claimant, different identity, can now claim the same work item --
    # the dead worker's lease does not permanently wedge the queue.
    second_coordinator = AttemptCoordinator(queue, run_id=run_id)
    second_attempt = second_coordinator.claim(
        work_item_id=work_item_id, identity=IDENTITY_B, goal="mutate", ttl=60.0,
    )
    assert second_attempt.lease.fencing_token > first_fencing_token, (
        "second claim did not receive a fresh, higher fencing token")

    # No double completion, part 1: replay the FIRST (dead) worker's exact lease against
    # complete() -- even though nothing is actually still running as that agent, prove the
    # queue itself would reject it if something somehow tried (stale fencing token).
    stale_lease = _lease_from_handoff(handoff)
    try:
        queue.complete(stale_lease, receipt_ref="stale-should-never-land")
        raise AssertionError("stale lease from the killed worker was able to complete the "
                             "work item -- double-completion is possible")
    except QueueConflict:
        pass

    # The second claimant finishes the job for real.
    result = second_coordinator.complete(second_attempt, receipt_ref="receipt-from-second-claimant")
    assert result["status"] == "completed"

    # No double completion, part 2: the event log shows exactly ONE "completed" event, and it
    # carries the SECOND claimant's fencing token -- the queue's own durable history agrees.
    events = queue.events(after=0, limit=1000)
    completed_events = [e for e in events if e.get("kind") == "completed" and e.get("task_id") == work_item_id]
    assert len(completed_events) == 1, (
        "expected exactly one completion event, got %d: %r" % (len(completed_events), completed_events))
    assert completed_events[0]["fencing_token"] == second_attempt.lease.fencing_token

    # And the stale replay attempt above must not have snuck in as a second completion either.
    task_state = queue.task(work_item_id)
    assert task_state["status"] == "completed"


if __name__ == "__main__":
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_work_item_claims_chaos")
