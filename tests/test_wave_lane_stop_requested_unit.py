"""AGENTS.md wave-safeguards item 4: the wave dispatch path must poll
``stop_requested`` before starting each lane and again between integration
steps, stopping cleanly with a typed status (``pending``/``drain_status:
"held"``, never a failure or a dead-letter) -- the previous behaviour never
checked it at all.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from simplicio_loop import runner as runner_mod
from simplicio_loop import wave_worktree as ww


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)
    return result.stdout


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "a@b.c")
    _git(repo, "config", "user.name", "a")
    (repo / "a.txt").write_text("orig-a\n", encoding="utf-8")
    (repo / "b.txt").write_text("orig-b\n", encoding="utf-8")
    (repo / "c.txt").write_text("orig-c\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


def _seed_run_dir(repo: Path, run_id: str) -> Path:
    run_dir = repo / ".simplicio" / "loop-runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        '{"schema": "simplicio.loop-manifest/v1", "repo": "%s", "run_id": "%s"}' % (repo, run_id),
        encoding="utf-8",
    )
    (run_dir / "state.json").write_text('{"phase": "executing"}', encoding="utf-8")
    return run_dir


def _items(repo: Path, run_id: str):
    return [
        {"task_index": 1, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["a.txt"]}},
        {"task_index": 2, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["b.txt"]}},
        {"task_index": 3, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["c.txt"]}},
    ]


def _make_fake_dispatch():
    def fake(item, retry_budget, owned_process_registry=None):
        task_index = int(item["task_index"])
        repo_dir = Path(item["repo"])
        name = {1: "a.txt", 2: "b.txt", 3: "c.txt"}[task_index]
        (repo_dir / name).write_text(f"lane-{task_index}\n", encoding="utf-8")
        return [{
            "schema": "simplicio.operator-worker/v1", "task_index": task_index,
            "run_id": item["run_id"], "repo": item["repo"], "status": "succeeded",
            "execution_state": "applied", "dead_letter": False,
            "operator_receipt": "", "evidence_receipt": "",
        }]
    return fake


def test_stop_requested_from_the_start_runs_no_lane_and_holds_every_task(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    repo = _init_repo(tmp_path)
    run_id = "wave-run-stop-all"
    run_dir = _seed_run_dir(repo, run_id)
    calls: list = []

    def spy(item, retry_budget, owned_process_registry=None):
        calls.append(int(item["task_index"]))
        raise AssertionError("no lane task may run once a stop is already requested")

    monkeypatch.setattr(runner_mod, "_run_operator_item_process", spy)

    result = runner_mod._wave_worktree_dispatch(
        repo_path=repo, run_id=run_id, run_dir=run_dir,
        items=_items(repo, run_id), retry_budget=0, max_workers=3,
        stop_requested=lambda: True,
    )

    assert result is not None
    assert calls == []
    assert result["completed_task_indices"] == []
    assert result["failed_task_indices"] == []
    assert result["dead_letter_task_indices"] == []
    assert result["drain"]["status"] == "drained"
    assert result["drain"]["reason_code"] == "operator_stop_requested"
    assert sorted(result["drain"]["pending_task_indices"]) == [1, 2, 3]
    for record in result["workers"]:
        assert record["status"] == "pending"
        assert record["drain_status"] == "held"
        assert record.get("dead_letter") is False

    # No lane ever touched the real repo files.
    assert (repo / "a.txt").read_text() == "orig-a\n"
    assert (repo / "b.txt").read_text() == "orig-b\n"
    assert (repo / "c.txt").read_text() == "orig-c\n"
    worktree_list = _git(repo, "worktree", "list")
    assert "lane-" not in worktree_list


def test_stop_requested_after_one_lane_completes_does_not_touch_remaining_lanes(tmp_path, monkeypatch):
    """A stop that fires only after the first lane has already finished must
    still let that lane's already-applied change through -- only lanes not
    yet started are held."""
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    repo = _init_repo(tmp_path)
    run_id = "wave-run-stop-partial"
    run_dir = _seed_run_dir(repo, run_id)
    monkeypatch.setattr(runner_mod, "_run_operator_item_process", _make_fake_dispatch())

    started_lanes: list = []
    real_run_worktree_lane = ww.run_worktree_lane

    async def counting_run_worktree_lane(*args, **kwargs):
        started_lanes.append(args[2])  # lane_id positional arg
        return await real_run_worktree_lane(*args, **kwargs)

    monkeypatch.setattr(ww, "run_worktree_lane", counting_run_worktree_lane)

    calls = {"n": 0}

    def stop_after_first_lane_starts() -> bool:
        # Flip to "stop" only once at least one lane has actually begun --
        # proves later lanes are the ones held, not merely "stop from turn 0".
        return len(started_lanes) >= 1

    result = runner_mod._wave_worktree_dispatch(
        repo_path=repo, run_id=run_id, run_dir=run_dir,
        items=_items(repo, run_id), retry_budget=0, max_workers=1,
        stop_requested=stop_after_first_lane_starts,
    )

    assert result is not None
    assert result["drain"]["status"] == "drained"
    pending = set(result["drain"]["pending_task_indices"])
    assert pending, "at least one lane must have been held"
    completed = set(result["completed_task_indices"])
    assert completed | pending == {1, 2, 3}
    assert completed.isdisjoint(pending)
    for record in result["workers"]:
        if record["task_index"] in pending:
            assert record["status"] == "pending"
            assert record["drain_status"] == "held"
        else:
            assert record["status"] == "succeeded"
