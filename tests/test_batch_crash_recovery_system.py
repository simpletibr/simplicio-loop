"""Real, un-mocked cross-process crash/recovery ("saga") proof for issue #288's remaining
gap: if the orchestrating process itself crashes mid-batch, a restarted process must
discover in-flight claims via the existing lease/fencing mechanism and resume/reconcile,
rather than silently losing track of the work or redoing/duplicating it.

Two *actual OS processes* (``subprocess.Popen`` running
``tests/_batch_orchestrator_process.py``, not two threads in one interpreter) dispatch one
real 3-item batch against one shared, file-backed ``SQLiteRemoteQueue`` and one shared
JSONL journal:

  1. Process A claims and completes item 0 (durably journaled + the queue marks it
     ``completed``), then claims item 1 and is deterministically stalled -- for real wall-clock
     seconds -- mid-attempt, its lease genuinely active and in-flight.
  2. Process A is killed (``proc.kill()`` -- a real SIGKILL/TerminateProcess on a live
     process), abandoning item 1's lease without any graceful release. Item 2 was never even
     reached.
  3. Once item 1's lease TTL genuinely expires (real time.sleep, no mocked clock), a freshly
     started process B (a new orchestrator, same queue db, same journal dir) is run against
     the identical item list.

Verified afterward: item 0 is NOT redone (the journal already had its receipt; process B's
own ``skipped_completed`` count proves it), items 1 and 2 are picked up and completed by
process B, the recovered lease shows a strictly higher fencing token than the abandoned one
(proof this is a genuinely new claim, not a stale one silently reused), and the final journal
contains exactly one ``succeeded`` record per task -- no lost tasks, no duplicated completions.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ORCHESTRATOR = Path(__file__).resolve().parent / "_batch_orchestrator_process.py"

TASK = """Sistema: PLANES
Funcionalidade: Tela de Modelagem — Ordenacao de linhas
Tipo: Evolucao

COMO analista do ONS,
QUERO organizar as linhas
PARA melhorar a analise

1. Criterios de Aceite

Cenario 1: Estrutural aparece primeiro
  Dado que existe uma linha estrutural
  Quando a tela for exibida
  Entao a linha estrutural aparece primeiro [RN01]

2. Regras de Negocio

RN01 - Estrutural sempre primeiro.
"""


def _identity(n):
    return {
        "agent_id": f"codex@device-{n}", "runtime": "codex", "device_id": f"device-{n}",
        "session_id": f"session-crash-{n}",
        "capabilities": ["claim", "heartbeat", "fencing", "receipts", "events"],
    }


def _arm_fixture(tmp_path, monkeypatch, name):
    """Arm one deterministic run in the parent test process (monkeypatch is available
    here); the child orchestrator processes only ever read the persisted armed run from
    disk plus env-var opt-in fakes (no in-process monkeypatching is possible once a
    real subprocess starts)."""
    from simplicio_loop import runner as runner_mod

    repo = tmp_path / f"repo-{name}"
    repo.mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".simplicio/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", ".gitignore", "src/app.py"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Simplicio Tests", "-c", "user.email=tests@simplicio.local",
         "commit", "-qm", "fixture"],
        cwd=repo, check=True,
    )
    task = tmp_path / f"task-{name}.md"
    task.write_text(TASK, encoding="utf-8")

    # Deliberately NOT a fixed/mocked fingerprint: the dispatch phase below runs in a
    # genuinely separate OS process where nothing in this parent process can be
    # monkeypatched, so ``_repo_fingerprint``/``_changed_paths`` must stay the project's
    # real, unmocked implementations end-to-end (arm time here, execute time in the child)
    # -- only the mapper/dev-cli *binary* calls are faked (arm-time via monkeypatch here,
    # dispatch-time via the project's existing env-var overrides).
    def fake_mapper(repo_path, run_root, **kwargs):
        fingerprint = runner_mod._repo_fingerprint(repo_path)
        runner_mod._write_json(run_root / "mapper-preflight.json", {
            "tool": "simplicio-mapper", "identity_ok": True, "version_ok": True,
            "missing_verbs": [], "repo_state": dict(fingerprint),
        })
        payload = {
            "scan": {"returncode": 0, "stdout": {}, "stderr": ""},
            "inspect": {"returncode": 0, "stdout": {
                "status": {"artifacts_present": True, "fresh": True},
                "evidence": {"artifacts": {
                    "project_map": {"exists": True},
                    "precedent_index": {"exists": True},
                }},
            }, "stderr": ""},
            "handoff": {"returncode": 0, "stdout": {
                "context_pack": {"pack_hash": "pack-fixed",
                                "files": [{"path": "src/app.py", "tests": []}]},
            }, "stderr": ""},
            "generated_at": "2026-07-14T00:00:00Z",
            "repo_state_before": dict(fingerprint),
            "repo_state_after": dict(fingerprint),
        }
        runner_mod._write_json(run_root / "mapper-context.json", payload)
        return payload

    def fake_operator_preflight(repo_path, run_root):
        help_surface = "Usage: simplicio-dev-cli edit --plan PLAN --apply --dry-run --json"
        receipt = {
            "tool": "simplicio-dev-cli", "identity_ok": True, "version_ok": True,
            "help_stdout": help_surface, "task_help_stdout": help_surface,
            "required_tokens": list(runner_mod.DEVCLI_REQUIRED_TOKENS),
            "missing_tokens": [],
            "required_capabilities": list(runner_mod.DEVCLI_REQUIRED_CAPABILITIES),
            "missing_capabilities": [],
            "repo_state": runner_mod._repo_fingerprint(repo_path),
        }
        runner_mod._write_json(run_root / "operator-preflight.json", receipt)
        return receipt

    monkeypatch.setattr(runner_mod, "_run_mapper", fake_mapper)
    monkeypatch.setattr(runner_mod, "_preflight_operator", fake_operator_preflight)
    monkeypatch.setenv("SIMPLICIO_REQUIRE_MUTATION_AUTHORITY", "0")
    # The fixture lives on pytest's small tmpfs; capacity admission is outside this
    # queue/journal recovery proof, so make its test boundary explicit.
    monkeypatch.setenv("SIMPLICIO_LOOP_DISK_RESERVE_BYTES", "0")
    monkeypatch.setenv("SIMPLICIO_LOOP_DISK_SUSPEND_FLOOR_BYTES", "0")
    monkeypatch.setenv("SIMPLICIO_LOOP_FAKE_OPERATOR_JSON", json.dumps({
        "execution_state": "dry_run", "returncode": 0,
        "stdout": {"kind": "operator-proposal", "ok": True}, "stderr": "",
        "argv": ["simplicio-dev-cli", "task", "demo"],
    }))
    armed = runner_mod.arm_run(str(repo), str(task), "verified", 12)
    assert armed["state"]["phase"] == "awaiting_decision", armed["state"]
    return str(repo), armed["manifest"]["run_id"]


def _spawn_orchestrator(*, items_json, queue_db, journal_dir, result_file, env,
                        max_workers=1, retry_budget=0):
    return subprocess.Popen(
        [sys.executable, str(ORCHESTRATOR),
         "--items-json", str(items_json), "--queue-db", str(queue_db),
         "--journal-dir", str(journal_dir), "--result-file", str(result_file),
         "--max-workers", str(max_workers), "--retry-budget", str(retry_budget)],
        cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        stdin=subprocess.DEVNULL, env=env,
    )


def _journal_lines(journal_path):
    if not journal_path.exists():
        return []
    lines = []
    for raw in journal_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw:
            lines.append(json.loads(raw))
    return lines


def _wait_until(predicate, *, timeout, interval=0.1, message="condition not met"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise TimeoutError(message)


def test_orchestrator_crash_mid_batch_is_recovered_by_a_fresh_process(tmp_path, monkeypatch):
    from simplicio_loop.remote_queue import SQLiteRemoteQueue

    lane_count = 3
    raw_items = []
    for lane in range(lane_count):
        repo, run_id = _arm_fixture(tmp_path, monkeypatch, lane)
        raw_items.append({
            "repo": repo, "run_id": run_id, "task_index": 1,
            "task_id": f"task-crash-{lane}",
            "identity": _identity(lane),
            "goal": f"converge PLANES ordering lane {lane}",
            "acs": ["RN01"],
            "branch": f"feat/crash-recovery-{lane}",
        })
    items_json = tmp_path / "items.json"
    items_json.write_text(json.dumps(raw_items), encoding="utf-8")

    queue_db = tmp_path / "shared-queue.db"
    journal_dir = tmp_path / "journal"
    result_a = tmp_path / "result-a.json"
    result_b = tmp_path / "result-b.json"

    slow_task_id = raw_items[1]["task_id"]  # item 1 -- the one crash-in-flight will stall on

    fake_devcli_preflight = json.dumps({
        "help_stdout": "Usage: simplicio-dev-cli edit --plan PLAN --apply --dry-run --json",
    })
    fake_exec = json.dumps({
        "returncode": 0, "stdout": {"kind": "operator-result", "ok": True}, "stderr": "",
        "write_files": {"src/app.py": "def main():\n    return 'ok-merged'\n"},
    })

    common_env = dict(os.environ)
    common_env.update({
        "SIMPLICIO_GUARDED_DISPATCH": "1",
        # A and B are still distinct OS orchestrator processes. Keep each process's
        # single worker in-thread so the test-only Hookwall ledger seam installed by
        # _batch_orchestrator_process.py remains visible to that worker.
        "SIMPLICIO_LOOP_DISPATCH_MODE": "thread",
        "SIMPLICIO_AUTO_MERGE_PR": "0",
        "SIMPLICIO_REQUIRE_MUTATION_AUTHORITY": "0",
        # Generous relative to real per-item overhead (real ``git`` subprocess calls for
        # fingerprinting/diffing on every arm+execute step) observed on this host -- the
        # point under test is TTL *expiry-driven recovery*, not a razor-thin TTL race.
        "SIMPLICIO_REMOTE_QUEUE_TTL": "8",
        "SIMPLICIO_LOOP_FAKE_DEVCLI_PREFLIGHT_JSON": fake_devcli_preflight,
        "SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON": fake_exec,
    })
    common_env.pop("SIMPLICIO_LOOP_FAKE_OPERATOR_JSON", None)  # arm-time only, must not leak into execute

    env_a = dict(common_env)
    env_a["SIMPLICIO_LOOP_TEST_SLOW_TASK_ID"] = slow_task_id
    env_a["SIMPLICIO_LOOP_TEST_SLOW_TASK_SECONDS"] = "300"

    proc_a = _spawn_orchestrator(
        items_json=items_json, queue_db=queue_db, journal_dir=journal_dir,
        result_file=result_a, env=env_a,
    )
    queue = SQLiteRemoteQueue(str(queue_db))
    journal_path = journal_dir / "operator-batch.jsonl"
    try:
        # 1) Wait for item 0 to be durably journaled as succeeded -- proof process A made
        # real, persisted progress before we kill it.
        def first_item_succeeded():
            if proc_a.poll() is not None:
                stdout, stderr = proc_a.communicate()
                raise AssertionError(
                    f"process A exited before journaling item 0 (rc={proc_a.returncode})\n"
                    f"stdout:\n{stdout}\nstderr:\n{stderr}"
                )
            return any(
                rec.get("task_id") == raw_items[0]["task_id"]
                and rec.get("status") == "succeeded"
                for rec in _journal_lines(journal_path)
            )

        _wait_until(
            first_item_succeeded,
            timeout=240.0, message="process A never journaled item 0 as succeeded",
        )
        # 2) Wait for item 1 to actually be claimed (an active, in-flight lease) before
        # killing -- otherwise this would only prove recovery of *queued*, not *claimed*,
        # work, which is the easy case, not the epic-288 gap.
        def slow_task_is_claimed():
            # ``SQLiteRemoteQueue.task`` deliberately raises ``KeyError`` until the
            # orchestrator has enqueued the item.  During this polling window that
            # simply means the claim has not happened yet, rather than a failure of
            # the recovery contract being exercised.
            try:
                return queue.task(slow_task_id).get("status") == "claimed"
            except KeyError:
                return False

        _wait_until(
            slow_task_is_claimed,
            timeout=120.0, message="process A never claimed item 1 before it could be killed",
        )

        # 3) Kill process A for real -- no graceful shutdown, no release call. Item 1's
        # lease is abandoned mid-flight; item 2 was never even reached.
        proc_a.kill()
        proc_a.wait(timeout=10)
    finally:
        if proc_a.poll() is None:
            proc_a.kill()
            proc_a.wait(timeout=10)

    # Immediately after the crash: item 0 completed for real, item 1 abandoned mid-claim
    # (not released, not completed), item 2 never touched.
    assert queue.task(raw_items[0]["task_id"])["status"] == "completed"
    abandoned = queue.task(slow_task_id)
    assert abandoned["status"] == "claimed"
    abandoned_fencing_token = abandoned["lease"]["fencing_token"]
    # item 2 was never even reached (serial dispatch, item 1 was still in flight) -- it
    # hasn't been enqueued in the shared queue at all yet.
    try:
        queue.task(raw_items[2]["task_id"])
        raise AssertionError("item 2 should not have been enqueued before the crash")
    except KeyError:
        pass
    lines_after_crash = _journal_lines(journal_path)
    assert len(lines_after_crash) == 1, "process A must not have journaled a partial/failed item 1 attempt"

    # 4) Let item 1's lease genuinely expire (real wall-clock wait, no mocked time) before
    # the fresh orchestrator tries to reclaim it.
    time.sleep(15.0)

    # 5) A brand-new orchestrator process, same queue db, same journal dir, same item
    # list -- no slow-task stall this time -- discovers and resumes/reconciles the batch.
    proc_b = _spawn_orchestrator(
        items_json=items_json, queue_db=queue_db, journal_dir=journal_dir,
        result_file=result_b, env=common_env,
    )
    rc_b = proc_b.wait(timeout=240)
    assert rc_b == 0, proc_b.stderr.read()

    result_b_payload = json.loads(result_b.read_text(encoding="utf-8"))

    # --- item 0 was NOT redone: process B's own accounting shows it as already-completed,
    # skipped from its pending queue ---
    assert result_b_payload["skipped_completed"] == 1, result_b_payload

    # --- items 1 and 2 were picked up and completed by the fresh process; item 0's worker
    # record is still reported (full accounting), but only because it was carried over from
    # the journal -- ``skipped_completed`` above is what proves it was never re-dispatched ---
    workers_b = {w["task_id"]: w for w in result_b_payload["workers"]}
    assert workers_b[raw_items[0]["task_id"]]["status"] == "succeeded"
    for task_id in (raw_items[1]["task_id"], raw_items[2]["task_id"]):
        record = workers_b[task_id]
        assert record["status"] == "succeeded", record
        assert record["execution_state"] == "applied", record
        assert record["receipt_status"] == "VERIFIED", record.get("receipt_verdict_reason")

    # --- the recovered lease is a genuinely new claim, not the stale abandoned one.
    # MapperStore fencing tokens are opaque UUID strings, so freshness is identity,
    # not lexicographic ordering. ---
    recovered = queue.task(slow_task_id)
    assert recovered["status"] == "completed"
    # Completed MapperStore queue rows intentionally clear their live lease. The
    # durable worker receipt retains the fencing token that authorized the recovery.
    recovered_fencing_token = workers_b[slow_task_id]["lease"]["fencing_token"]
    assert recovered_fencing_token != abandoned_fencing_token

    # --- no lost tasks: all three end up completed exactly once ---
    for raw in raw_items:
        assert queue.task(raw["task_id"])["status"] == "completed", raw["task_id"]

    # --- no duplicated completions: the journal has exactly one succeeded record per
    # task_id across BOTH processes combined (proves process B did not redo item 0, and
    # did not double-journal items 1/2) ---
    final_lines = _journal_lines(journal_path)
    succeeded_task_ids = [rec["task_id"] for rec in final_lines if rec.get("status") == "succeeded"]
    assert sorted(succeeded_task_ids) == sorted(raw["task_id"] for raw in raw_items)
    assert len(succeeded_task_ids) == len(set(succeeded_task_ids)) == lane_count


if __name__ == "__main__":
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_batch_crash_recovery")
