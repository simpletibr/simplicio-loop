from __future__ import annotations

import json
from pathlib import Path

from simplicio_loop import runner as runner_mod


def test_conduct_run_uses_adaptive_dispatch_and_stops_before_watcher_on_blocked_worker(
    monkeypatch, tmp_path
):
    run_id = "run-zero-config"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    status = {
        "run_dir": str(run_dir),
        "state": {"phase": "awaiting_decision", "history": []},
    }
    armed = {
        "run_dir": str(run_dir),
        "manifest": {"run_id": run_id},
        "state": {"phase": "awaiting_decision"},
    }
    dispatch = {}
    watcher_calls = []

    monkeypatch.setattr(runner_mod, "arm_run", lambda *args: armed)

    def fake_batch(*args, **kwargs):
        dispatch.update(kwargs)
        return {
            "workers": [
                {
                    "task_index": 1,
                    "status": "blocked",
                    "reason_code": "PHYSICAL_PRESSURE_TERMINATE",
                }
            ],
            "failed_task_indices": [],
            "blocked_task_indices": [1],
            "dead_letter_task_indices": [],
        }

    monkeypatch.setattr(runner_mod, "execute_operator_batch", fake_batch)
    monkeypatch.setattr(runner_mod, "read_status", lambda *args: status)

    def fail_if_verified(*args, **kwargs):
        watcher_calls.append((args, kwargs))
        raise AssertionError("watcher must not run before a successful operator")

    monkeypatch.setattr(runner_mod, "verify_run", fail_if_verified)

    result = runner_mod._conduct_run("repo", "task")

    assert dispatch["max_workers"] is None
    assert dispatch["auto_fan_out"] is None
    assert watcher_calls == []
    assert result["state"]["phase"] == "blocked"
    assert "PHYSICAL_PRESSURE_TERMINATE" in result["state"]["blockers"][0]


def test_mapper_store_bootstraps_on_normal_mapper_route(monkeypatch, tmp_path):
    from simplicio_loop import mapper_operations

    calls = []

    class FakeAdapter:
        def __init__(self, database, *, auto_create):
            calls.append((database, auto_create))

        def initialize(self):
            calls.append("initialize")
            return {"status": "ready"}

    monkeypatch.setattr(mapper_operations, "MapperOperationsAdapter", FakeAdapter)
    monkeypatch.setattr(
        runner_mod,
        "_mapper_operations_database",
        lambda repo: str(tmp_path / "operations.sqlite"),
    )
    monkeypatch.setattr(
        runner_mod,
        "_storage_route_requested",
        lambda: "mapper",
    )

    result = runner_mod._ensure_mapper_operations_store(tmp_path)

    assert result == {"status": "ready"}
    assert calls == [(str(tmp_path / "operations.sqlite"), True), "initialize"]


def test_mapper_journal_uses_task_repo_root(monkeypatch, tmp_path):
    process_root = tmp_path / "process"
    task_repo = tmp_path / "task-repo"
    process_root.mkdir()
    task_repo.mkdir()
    seen = []

    class FakeJournal:
        def __init__(self, database, *, auto_create):
            seen.append((database, auto_create))

    monkeypatch.chdir(process_root)
    monkeypatch.setattr(runner_mod, "_mapper_journal_enabled", lambda: True)
    monkeypatch.setattr(
        runner_mod,
        "_mapper_operations_database",
        lambda repo: str(Path(repo) / ".simplicio-loop" / "operations.sqlite"),
    )
    monkeypatch.setattr(runner_mod, "MapperRunJournal", FakeJournal)

    runner_mod._dispatch_journal_backend(
        task_repo / ".simplicio-loop" / "loop-runs" / "run" / "run-journal.sqlite",
    )

    assert seen == [(str(task_repo / ".simplicio-loop" / "operations.sqlite"), False)]


def test_mapper_warmup_requires_a_fresh_inspection():
    fresh = type("Result", (), {
        "stdout": json.dumps({"status": {"artifacts_present": True, "fresh": True}}),
    })()
    stale = type("Result", (), {
        "stdout": json.dumps({"status": {"artifacts_present": True, "fresh": False}}),
    })()

    assert runner_mod._mapper_inspection_is_fresh(fresh) is True
    assert runner_mod._mapper_inspection_is_fresh(stale) is False
