"""Wiring test for AGENTS.md item C: `_wave_worktree_dispatch` (the actual
wave dispatch path in runner.py) groups disjoint-path items into lanes via
`wave_worktree.group_disjoint_tasks` and, with more than one lane, runs them
concurrently in real git worktrees, integrates serially, and rebinds
`repo_state_chain`. Real git worktree/apply/cleanup runs for real; only the
per-task dev-cli dispatch itself (`_run_operator_item_process`) is stubbed,
the same boundary every other dispatch unit test in this repo stubs.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from simplicio_loop import runner as runner_mod


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


FILES_BY_INDEX = {1: "a.txt", 2: "b.txt", 3: "c.txt"}


def _make_fake_dispatch(sleep_s: float, timeline: list):
    def fake(item, retry_budget, owned_process_registry=None):
        task_index = int(item["task_index"])
        repo_dir = Path(item["repo"])
        started = time.monotonic()
        time.sleep(sleep_s)
        (repo_dir / FILES_BY_INDEX[task_index]).write_text(f"lane-{task_index}\n", encoding="utf-8")
        finished = time.monotonic()
        timeline.append((task_index, started, finished))
        return [{
            "schema": "simplicio.operator-worker/v1", "task_index": task_index,
            "run_id": item["run_id"], "repo": item["repo"], "status": "succeeded",
            "execution_state": "applied", "dead_letter": False,
            "operator_receipt": "", "evidence_receipt": "",
        }]
    return fake


def _intervals_overlap(a, b) -> bool:
    (_, a_start, a_end) = a
    (_, b_start, b_end) = b
    return a_start < b_end and b_start < a_end


def test_three_disjoint_tasks_form_three_lanes_and_run_concurrently(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    run_id = "wave-run-1"
    run_dir = _seed_run_dir(repo, run_id)
    items = [
        {"task_index": 1, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["a.txt"]}},
        {"task_index": 2, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["b.txt"]}},
        {"task_index": 3, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["c.txt"]}},
    ]
    sleep_s = 0.6
    timeline: list = []
    monkeypatch.setattr(runner_mod, "_run_operator_item_process", _make_fake_dispatch(sleep_s, timeline))

    started = time.monotonic()
    result = runner_mod._wave_worktree_dispatch(
        repo_path=repo, run_id=run_id, run_dir=run_dir,
        items=items, retry_budget=0, max_workers=3,
    )
    elapsed = time.monotonic() - started

    assert result is not None
    assert len(result["wave"]["lanes"]) == 3
    assert result["completed_task_indices"] == [1, 2, 3]
    assert result["dead_letter_task_indices"] == []
    assert len(timeline) == 3
    # 3 lanes each sleeping sleep_s running concurrently must take much less
    # than the 3 * sleep_s a serial run would need -- generous margin for a
    # loaded CI/dev box (thread scheduling, not tight timing, is the point).
    assert elapsed < sleep_s * 2
    # Genuine overlap: at least one pair of lanes' [start, end) intervals overlap.
    assert any(
        _intervals_overlap(timeline[i], timeline[j])
        for i in range(len(timeline)) for j in range(i + 1, len(timeline))
    )

    assert (repo / "a.txt").read_text() == "lane-1\n"
    assert (repo / "b.txt").read_text() == "lane-2\n"
    assert (repo / "c.txt").read_text() == "lane-3\n"

    state = runner_mod._load_json(run_dir / "state.json")
    assert state["repo_state_chain"]

    worktree_list = _git(repo, "worktree", "list")
    assert str(run_dir / "wt") not in worktree_list


def test_single_lane_returns_none_and_keeps_existing_serial_path(tmp_path):
    repo = _init_repo(tmp_path)
    run_id = "wave-run-single"
    run_dir = _seed_run_dir(repo, run_id)
    items = [
        {"task_index": 1, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["a.txt"]}},
        {"task_index": 2, "task_spec": {"files_affected": ["a.txt"]}},
    ]
    result = runner_mod._wave_worktree_dispatch(
        repo_path=repo, run_id=run_id, run_dir=run_dir,
        items=items, retry_budget=0, max_workers=2,
    )
    assert result is None


def test_lane_conflict_at_integration_reapplies_serially_on_main_repo(tmp_path, monkeypatch):
    """One lane's patch no longer applies (a real conflicting commit lands on
    the main repo between the lane's worktree run and integration) -- the
    lane's task is re-run directly on the main repo, not dead-lettered."""
    repo = _init_repo(tmp_path)
    run_id = "wave-run-conflict"
    run_dir = _seed_run_dir(repo, run_id)
    items = [
        {"task_index": 1, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["a.txt"]}},
        {"task_index": 2, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["b.txt"]}},
    ]
    timeline: list = []
    fake = _make_fake_dispatch(0.0, timeline)

    real_run_worktree_wave = runner_mod.wave_worktree.run_worktree_wave

    async def sabotaging_run_worktree_wave(*args, **kwargs):
        results = await real_run_worktree_wave(*args, **kwargs)
        # Simulate the main repo moving out from under lane 1's patch right
        # after its worktree finished, before integration runs.
        (repo / "a.txt").write_text("advanced-by-someone-else\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "advance base under lane 1")
        return results

    monkeypatch.setattr(runner_mod, "_run_operator_item_process", fake)
    monkeypatch.setattr(runner_mod.wave_worktree, "run_worktree_wave", sabotaging_run_worktree_wave)

    result = runner_mod._wave_worktree_dispatch(
        repo_path=repo, run_id=run_id, run_dir=run_dir,
        items=items, retry_budget=0, max_workers=2,
    )

    assert result is not None
    assert result["completed_task_indices"] == [1, 2]
    assert result["wave"]["integration"]["repaired_lanes"] == [1]
    assert result["wave"]["integration"]["failed_lanes"] == []
    # The repair re-ran task 1 directly on the (now-advanced) main repo.
    assert (repo / "a.txt").read_text() == "lane-1\n"
    assert (repo / "b.txt").read_text() == "lane-2\n"
