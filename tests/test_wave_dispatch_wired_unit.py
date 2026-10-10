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
import threading
import time
from pathlib import Path

import pytest

from simplicio_loop import local_capacity
from simplicio_loop import runner as runner_mod

# A lane that never meets the other lanes waits at most this long, then the barrier breaks and the test fails.
# It is a failure bound only: a run that overlaps never waits, so no time limit decides a pass.
RENDEZVOUS_FAIL_AFTER_S = 10


@pytest.fixture(autouse=True)
def _idle_host(monkeypatch):
    """The lanes a wave may run at once come from a probe of this host (cores allowed to the process, free memory and
    disk): on 2 cores it admits one lane at a time. Pin an idle 8-core host so the test never reads the real machine."""
    def idle_probe(_root, *, requested_workers, now_ns=None, **_kwargs):
        requested = max(1, int(requested_workers))
        return local_capacity.CapacitySample(
            requested_workers=requested, safe_workers=requested, cpu_count=8,
            memory_available_bytes=8 << 30, disk_free_bytes=100 << 30,
            measured=("cpu_count", "disk_free_bytes", "memory_available_bytes"), unavailable=(),
            null_reasons={}, observed_at_ns=int(now_ns or 1),
        )

    monkeypatch.setattr(local_capacity, "probe_local_capacity", idle_probe)
    monkeypatch.setattr(local_capacity, "_physical_pressure", lambda _root: {
        "available": True, "pressure_percent": 0.0, "disk_used_percent": 0.0,
        "disk_free_bytes": 100 << 30, "memory_used_percent": 0.0, "disk_suspend": False,
    })


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
    run_dir = repo / ".simplicio-loop" / "loop-runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        '{"schema": "simplicio.loop-manifest/v1", "repo": "%s", "run_id": "%s"}' % (repo, run_id),
        encoding="utf-8",
    )
    (run_dir / "state.json").write_text('{"phase": "executing"}', encoding="utf-8")
    return run_dir


FILES_BY_INDEX = {1: "a.txt", 2: "b.txt", 3: "c.txt"}


def _make_fake_dispatch(timeline: list, rendezvous: threading.Barrier | None = None):
    """A worker that, with a `rendezvous`, waits for the other lanes to be inside it too: lanes overlap only if they all arrive."""
    def fake(item, retry_budget, owned_process_registry=None):
        task_index = int(item["task_index"])
        repo_dir = Path(item["repo"])
        started = time.monotonic()
        if rendezvous is not None:
            rendezvous.wait()
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
    # This test stubs the per-task worker with a local closure (`fake`), which
    # cannot cross a real process boundary -- same reason every classic-dispatch
    # unit test that stubs a worker this way pins thread mode (AGENTS.md item 2:
    # the wave path now honors SIMPLICIO_LOOP_DISPATCH_MODE, default "process").
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    repo = _init_repo(tmp_path)
    run_id = "wave-run-1"
    run_dir = _seed_run_dir(repo, run_id)
    items = [
        {"task_index": 1, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["a.txt"]}},
        {"task_index": 2, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["b.txt"]}},
        {"task_index": 3, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["c.txt"]}},
    ]
    timeline: list = []
    rendezvous = threading.Barrier(3, timeout=RENDEZVOUS_FAIL_AFTER_S)
    monkeypatch.setattr(runner_mod, "_run_operator_item_process", _make_fake_dispatch(timeline, rendezvous))

    result = runner_mod._wave_worktree_dispatch(
        repo_path=repo, run_id=run_id, run_dir=run_dir,
        items=items, retry_budget=0, max_workers=3,
    )

    assert result is not None
    assert len(result["wave"]["lanes"]) == 3
    assert result["completed_task_indices"] == [1, 2, 3]
    assert result["dead_letter_task_indices"] == []
    assert len(timeline) == 3
    # No lane leaves the rendezvous until all three are inside it, so the lanes ran together by construction: no clock decides.
    assert not rendezvous.broken
    assert all(
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
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    repo = _init_repo(tmp_path)
    run_id = "wave-run-conflict"
    run_dir = _seed_run_dir(repo, run_id)
    items = [
        {"task_index": 1, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["a.txt"]}},
        {"task_index": 2, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["b.txt"]}},
    ]
    timeline: list = []
    fake = _make_fake_dispatch(timeline)

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
