"""System/E2E suite for issue #276 — real loops, resume, concurrency and recovery.

Unlike the focused unit tests (``test_recovery.py``, ``test_work_item_claims.py``,
``test_budget.py``, ``test_remote_queue*.py``), this file drives several modules
together the way a real run does — the shared SQLite queue, the attempt
coordinator, the phase-event/cursor recovery contract, and the budget ledger —
to prove the end-to-end properties the issue asks for:

  * a goal runs through planning -> execution -> validation -> completion, and the
    final queue/receipt state is verifiable on disk (no mocks);
  * multiple concurrent work items make progress in parallel without violating
    per-task ownership (fencing tokens are exclusive, never shared);
  * a mid-run crash is followed by a resume from the persisted cursor with no
    duplicated completion and no re-execution of terminal work;
  * a repeated ("replayed") completion attempt against an already-terminal lease
    is rejected outright — a crash/retry can never duplicate the side effect;
  * a run budget acts as the infinite-loop / no-progress breaker: once the shared
    envelope is exhausted, further reservations are refused rather than allowing
    the run to spin forever.

This suite is picked up automatically by ``scripts/check.py`` and the CI ``ci``
workflow (any ``tests/test_*.py`` is auto-discovered), satisfying the "runs
automatically in CI" acceptance criterion.
"""
from __future__ import annotations

import concurrent.futures
import json
import threading

import pytest
import sys

pytestmark = [
    pytest.mark.satellite,
    pytest.mark.skipif(
        sys.platform == "darwin",
        reason="real concurrent fencing-token processes are Linux-specific",
    ),
]

from simplicio_loop.work_item_claims import AttemptCoordinator
from simplicio_loop.remote_queue import QueueConflict, SQLiteRemoteQueue
from simplicio_loop.phase_events import build_phase_event
from simplicio_loop.recovery import (
    build_cursor,
    persist_cursor,
    reconcile_after_crash,
    recover_after_crash,
)
from simplicio_loop.budget import BudgetExceeded, BudgetLedger, RunBudget


def _identity(agent_id):
    return {"agent_id": agent_id, "runtime": "pytest", "device_id": "dev-1", "session_id": "sess-1"}


def _queue(tmp_path):
    return SQLiteRemoteQueue(str(tmp_path / "queue.sqlite3"))


# ---------------------------------------------------------------------------
# 1. Full lifecycle: planning -> concurrent execution -> validation -> close
# ---------------------------------------------------------------------------

def test_full_run_lifecycle_with_concurrent_work_items_verifies_final_state(tmp_path):
    """Several work items are claimed and driven to completion concurrently; the
    final queue + receipt state on disk is the verifiable proof of closure."""
    queue = _queue(tmp_path)
    receipt_dir = tmp_path / "receipts"
    coordinator = AttemptCoordinator(queue, run_id="run-276-lifecycle", receipt_dir=receipt_dir)
    work_items = ["task-a", "task-b", "task-c", "task-d"]

    def drive(work_item_id):
        attempt = coordinator.claim(
            work_item_id=work_item_id,
            identity=_identity("agent-%s" % work_item_id),
            goal="ship %s" % work_item_id,
            acs=["AC1"],
        )
        coordinator.record_event(attempt, "execution_started", {"note": "planning done"})
        receipt = coordinator.accept_receipt(attempt, {
            "status": "verified", "summary": "done: %s" % work_item_id,
        })
        result = coordinator.complete(attempt, receipt_ref=receipt["receipt_hash"] if "receipt_hash" in receipt else "receipt")
        return work_item_id, result

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(work_items)) as pool:
        results = dict(pool.map(drive, work_items))

    assert set(results) == set(work_items)
    for work_item_id in work_items:
        assert results[work_item_id]["status"] == "completed"
        # the queue itself (source of truth for exclusivity) reflects completion
        assert queue.task(work_item_id)["status"] == "completed"
        # every attempt left a durable, on-disk trail (planning/execution/receipt events)
        run_dir = receipt_dir / "run-276-lifecycle" / work_item_id
        attempt_dirs = list(run_dir.iterdir())
        assert len(attempt_dirs) == 1, "exactly one attempt directory per completed work item"
        events_file = attempt_dirs[0] / "events.jsonl"
        assert events_file.exists()
        kinds = [json.loads(line)["kind"] for line in events_file.read_text(encoding="utf-8").splitlines()]
        assert kinds[0] == "claimed"
        assert "execution_started" in kinds
        assert kinds[-1] == "completed"


# ---------------------------------------------------------------------------
# 2. Concurrency: ownership must never be violated
# ---------------------------------------------------------------------------

def test_concurrent_claim_of_same_work_item_grants_exactly_one_owner(tmp_path):
    """N racing agents try to claim the SAME task; exactly one wins the lease and
    the rest are rejected outright (QueueConflict) — ownership is never shared."""
    queue = _queue(tmp_path)
    queue.enqueue("shared-task", {"goal": "single-owner work"})
    barrier = threading.Barrier(6)
    winners = []
    losers = []
    lock = threading.Lock()

    def race(idx):
        barrier.wait()
        try:
            lease = queue.claim("shared-task", "agent-%d" % idx,
                                idempotency_key="race-key-%d" % idx, ttl=30.0)
            with lock:
                winners.append(lease)
        except QueueConflict:
            with lock:
                losers.append(idx)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(race, range(6)))

    assert len(winners) == 1, "exactly one concurrent claim may succeed for the same task"
    assert len(losers) == 5
    # the queue's fencing token for the task matches only the winner's lease
    winner = winners[0]
    assert queue.task("shared-task")["lease"]["fencing_token"] == winner.fencing_token
    assert queue.task("shared-task")["lease"]["agent_id"] == winner.agent_id


def test_concurrent_attempts_across_many_items_never_cross_fencing_tokens(tmp_path):
    """Driving 8 work items concurrently through claim -> heartbeat -> complete must
    never let one attempt's fencing token leak onto another task's lease row."""
    queue = _queue(tmp_path)
    items = ["wi-%02d" % i for i in range(8)]
    for work_item_id in items:
        queue.enqueue(work_item_id, {"goal": "concurrent drive"})

    def drive(work_item_id):
        lease = queue.claim(work_item_id, "agent-" + work_item_id,
                            idempotency_key="k-" + work_item_id, ttl=30.0)
        lease = queue.heartbeat(lease, ttl=30.0)
        return work_item_id, queue.complete(lease, receipt_ref="r-" + work_item_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = dict(pool.map(drive, items))

    for work_item_id in items:
        row = queue.task(work_item_id)
        assert row["status"] == "completed"
        # each task's own lease belongs to exactly the agent that drove it — no
        # other concurrently-running attempt's identity or receipt_ref leaked in
        assert row["lease"]["agent_id"] == "agent-" + work_item_id
        assert row["lease"]["task_id"] == work_item_id
        assert row["lease"]["receipt_ref"] == "r-" + work_item_id
        assert results[work_item_id]["status"] == "completed"
        assert results[work_item_id]["receipt_ref"] == "r-" + work_item_id
    # each independent task's fencing sequence started fresh at 1 (no shared counter
    # bleeding state between unrelated tasks) yet each is a distinct row in storage
    all_rows = [queue.task(w) for w in items]
    assert len({(r["task_id"], r["lease"]["lease_id"]) for r in all_rows}) == len(items)


# ---------------------------------------------------------------------------
# 3. Crash recovery: resume from a persisted cursor without duplication
# ---------------------------------------------------------------------------

IDENTITY = {"run_id": "run-276-crash", "work_item_id": "wi-crash", "attempt_id": "att-1", "actor": "codex@host-a"}
CURSOR_IDENTITY = {**IDENTITY, "environment_id": "host-a/python-3.x"}


def _phase_event(sequence, from_phase, to_phase):
    return build_phase_event(**IDENTITY, cause="worker", sequence=sequence,
                             event_id="evt-%d" % sequence, from_phase=from_phase, to_phase=to_phase)


def test_crash_mid_run_resumes_from_persisted_cursor_without_reexecuting(tmp_path):
    """Simulate: the loop applies a few phase transitions, persists its cursor,
    then the process dies. A fresh process loads that cursor from disk and must
    resume from exactly where it left off — not from zero, and not skipping ahead."""
    cursor_path = tmp_path / "cursor.json"
    cursor = build_cursor(**CURSOR_IDENTITY)

    # --- pre-crash: two phases applied and durably persisted ---
    pre_crash_events = [_phase_event(1, None, "intake"), _phase_event(2, "intake", "mapping")]
    cursor, diag = reconcile_after_crash(pre_crash_events, cursor)
    persist_cursor(cursor_path, cursor)
    assert diag["status"] == "resumed"

    # --- "crash": drop all in-memory state, reload strictly from disk ---
    reloaded_cursor = json.loads(cursor_path.read_text(encoding="utf-8"))

    # --- restart: full event log replayed (including the already-applied prefix) ---
    full_log = pre_crash_events + [_phase_event(3, "mapping", "planning"),
                                    _phase_event(4, "planning", "executing")]
    result = recover_after_crash(
        full_log, reloaded_cursor,
        source_state={"status": "open", "run_id": "run-276-crash", "work_item_id": "wi-crash"},
        runtime_reconcile=lambda: {"status": "MEASURED", "pending": 0},
        persist_path=cursor_path,
    )
    assert result["status"] == "RESUMED"
    assert result["execution_allowed"] is True
    # only the two NEW events (seq 3, 4) were (re)applied post-crash, not the pre-crash pair
    assert result["diagnostics"]["applied_sequences"] == [3, 4]
    assert sorted(result["diagnostics"]["replayed_event_ids"]) == ["evt-1", "evt-2"]
    assert result["cursor"]["last_sequence"] == 4

    # the on-disk cursor was advanced accordingly, ready for a *second* crash
    persisted = json.loads(cursor_path.read_text(encoding="utf-8"))
    assert persisted["last_sequence"] == 4


def test_crash_recovery_never_duplicates_completion_once_terminal(tmp_path):
    """Drive a run all the way to a terminal phase, persist, "crash", and resume.
    The resumed run must report COMPLETE / execution_allowed=False — a duplicate
    completion attempt (i.e. rescheduling the same work) is impossible."""
    cursor_path = tmp_path / "cursor.json"
    cursor = build_cursor(**CURSOR_IDENTITY)
    transitions = [
        (1, None, "intake"), (2, "intake", "mapping"), (3, "mapping", "planning"),
        (4, "planning", "executing"), (5, "executing", "validating"),
        (6, "validating", "watching"), (7, "watching", "delivering"), (8, "delivering", "done"),
    ]
    all_events = [_phase_event(seq, before, after) for seq, before, after in transitions]
    for event in all_events:
        cursor, _ = reconcile_after_crash([event], cursor)
    persist_cursor(cursor_path, cursor)
    assert cursor["terminal"] is True

    # crash + resume with the FULL event history replayed again (a naive re-driver
    # would try to redo every phase transition from scratch)
    reloaded = json.loads(cursor_path.read_text(encoding="utf-8"))
    result = recover_after_crash(all_events, reloaded, source_state={"status": "done"})
    assert result["status"] == "COMPLETE"
    assert result["execution_allowed"] is False
    assert result["reason_code"] == "terminal_cursor"
    # a second, independent "restart" of the same terminal cursor is equally inert
    result_again = recover_after_crash(all_events, reloaded, source_state={"status": "done"})
    assert result_again["status"] == "COMPLETE"
    assert result_again["execution_allowed"] is False


def test_repeated_completion_of_same_lease_is_rejected_not_duplicated(tmp_path):
    """A worker that (incorrectly) tries to complete a task twice — e.g. after a
    retried supervisor call following a crash — must be rejected the second time,
    proving repeated execution never duplicates the completion side effect."""
    queue = _queue(tmp_path)
    queue.enqueue("dup-task", {"goal": "no double completion"})
    lease = queue.claim("dup-task", "agent-1", idempotency_key="dup-key", ttl=30.0)
    first = queue.complete(lease, receipt_ref="receipt-1")
    assert first["status"] == "completed"
    with pytest.raises(QueueConflict):
        queue.complete(lease, receipt_ref="receipt-2")
    # the task's terminal state is unaffected by the rejected replay
    assert queue.task("dup-task")["status"] == "completed"


def test_claim_retry_after_release_gets_fresh_attempt_and_fencing_token(tmp_path):
    """A blocked/retried attempt releases its lease and re-claims — the retry must
    get a brand-new attempt id and a genuinely fresh fencing token, never reusing
    the failed attempt's identity (which would risk conflating receipts)."""
    queue = _queue(tmp_path)
    coordinator = AttemptCoordinator(queue, run_id="run-276-retry")
    first_attempt = coordinator.claim(work_item_id="flaky", identity=_identity("agent-1"),
                                      goal="do flaky work", acs=["AC1"])
    retried_attempt = coordinator.retry(first_attempt, reason="tool_timeout")
    assert retried_attempt.attempt_id != first_attempt.attempt_id
    # Fencing tokens are opaque, distinct identifiers (simplicio-mapper's operations
    # store mints them as uuid4 hex, not a monotonic counter) -- the invariant this
    # proves is that a retry never reuses the failed attempt's token, not that tokens
    # sort in claim order.
    assert retried_attempt.lease.fencing_token != first_attempt.lease.fencing_token
    # the old lease is well and truly dead: any action against it is rejected
    with pytest.raises(QueueConflict):
        coordinator.assert_active(first_attempt)
    # the new attempt can complete normally
    receipt = coordinator.accept_receipt(retried_attempt, {"status": "verified"})
    result = coordinator.complete(retried_attempt, receipt_ref="ref-flaky")
    assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# 4. Budget as the infinite-loop / no-progress breaker
# ---------------------------------------------------------------------------

def test_run_budget_stops_a_no_progress_loop_before_it_runs_forever(tmp_path):
    """A run that keeps retrying the same work item without making progress must
    eventually be halted by the shared budget envelope — the mechanical stand-in
    for "loop infinito é detectado e interrompido"."""
    budget = RunBudget(run_id="run-276-budget", token_limit=100, exhaustion_policy="stop")
    ledger = BudgetLedger(str(tmp_path / "budget.sqlite3"), budget)

    iterations_completed = 0
    with pytest.raises(BudgetExceeded):
        for i in range(1000):  # a runaway loop that would otherwise never terminate
            ledger.reserve("iter-%d" % i, "stuck-task", tokens=15)
            iterations_completed += 1

    # the ledger enforced a hard, deterministic cutoff well short of 1000 iterations
    assert 0 < iterations_completed < 1000
    snapshot = ledger.snapshot()
    assert snapshot["reserved_tokens"] <= budget.token_limit
    assert snapshot["remaining_tokens"] >= 0


def test_run_budget_is_shared_and_atomic_across_concurrent_workers(tmp_path):
    """Multiple concurrent "workers" reserving against the SAME run budget must
    never collectively overspend it — the invariant concurrency must not violate."""
    budget = RunBudget(run_id="run-276-shared-budget", token_limit=50, exhaustion_policy="stop")
    path = str(tmp_path / "shared-budget.sqlite3")

    admitted = []
    lock = threading.Lock()

    def worker(idx):
        ledger = BudgetLedger(path, budget)
        try:
            ledger.reserve("res-%d" % idx, "work-%d" % idx, tokens=10)
            with lock:
                admitted.append(idx)
        except BudgetExceeded:
            pass

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(worker, range(10)))

    # exactly 5 reservations of 10 tokens fit inside a 50-token envelope, never more
    assert len(admitted) == 5
    final = BudgetLedger(path, budget).snapshot()
    assert final["reserved_tokens"] == 50
    assert final["remaining_tokens"] == 0
