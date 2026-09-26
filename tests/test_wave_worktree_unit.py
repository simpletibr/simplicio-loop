"""Worktree-parallel wave: disjoint-path lane grouping, concurrent lane
execution in real git worktrees, serial integration in task order, and the
conflict -> serial-repair fallback. All git usage here is real (a throwaway
tmp_path repo); nothing about git itself is mocked."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import pytest

from simplicio_loop import wave_worktree as ww


# --------------------------------------------------------------------------
# group_disjoint_tasks
# --------------------------------------------------------------------------

def test_independent_tasks_each_get_their_own_lane():
    lanes = ww.group_disjoint_tasks([["a.py"], ["b.py"], ["c.py"]])
    assert lanes == [[1], [2], [3]]


def test_tasks_touching_the_same_path_share_one_lane_in_order():
    lanes = ww.group_disjoint_tasks([["shared.py"], ["other.py"], ["shared.py"]])
    assert lanes == [[1, 3], [2]]


def test_a_task_bridging_two_lanes_merges_them_in_first_seen_order():
    # task 1 -> a.py, task 2 -> b.py (independent so far), task 3 touches both
    # a.py and b.py, so all three must end up in one lane.
    lanes = ww.group_disjoint_tasks([["a.py"], ["b.py"], ["a.py", "b.py"]])
    assert lanes == [[1, 2, 3]]


def test_empty_or_blank_paths_do_not_merge_tasks():
    lanes = ww.group_disjoint_tasks([[], [""], ["  "]])
    assert lanes == [[1], [2], [3]]


# --------------------------------------------------------------------------
# ArtifactCache
# --------------------------------------------------------------------------

def test_artifact_cache_builds_once_and_reuses_on_second_call(tmp_path):
    cache = ww.ArtifactCache(tmp_path / "cache")
    calls = []

    def builder(target: Path) -> None:
        calls.append(target)
        (target / "survey.json").write_text("{}", encoding="utf-8")

    dir1, hit1 = cache.get_or_build("sha-abc", builder)
    dir2, hit2 = cache.get_or_build("sha-abc", builder)

    assert hit1 is False
    assert hit2 is True
    assert dir1 == dir2
    assert len(calls) == 1
    assert (dir1 / "survey.json").exists()


def test_artifact_cache_different_keys_build_independently(tmp_path):
    cache = ww.ArtifactCache(tmp_path / "cache")
    seen = set()

    def builder(target: Path) -> None:
        seen.add(target)

    cache.get_or_build("sha-1", builder)
    cache.get_or_build("sha-2", builder)
    assert len(seen) == 2


def test_default_branch_commit_falls_back_to_head_without_a_remote(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "a@b.c")
    _git(repo, "config", "user.name", "a")
    (repo / "f.txt").write_text("1", encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-m", "init")
    head = _git(repo, "rev-parse", "HEAD").strip()
    assert ww.default_branch_commit(repo) == head


# --------------------------------------------------------------------------
# Worktree-parallel lane execution + serial integration (real git)
# --------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True,
    )
    return result.stdout


@pytest.fixture()
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "a@b.c")
    _git(repo, "config", "user.name", "a")
    (repo / "a.py").write_text("# a\n", encoding="utf-8")
    (repo / "b.py").write_text("# b\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


def _apply_writes(writes: dict[int, tuple[str, str]]) -> ww.ApplyFn:
    """Fake apply_fn standing in for the real dev-cli compile+apply step:
    for each task index in the lane, append a line to the mapped file."""
    async def _apply(wt_path: Path, task_indices) -> dict:
        for index in task_indices:
            if index not in writes:
                continue
            rel, line = writes[index]
            path = wt_path / rel
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return {"applied": True}
    return _apply


def test_two_disjoint_lanes_run_concurrently_and_integrate_serially(git_repo):
    base = _git(git_repo, "rev-parse", "HEAD").strip()
    lanes = [[1], [2]]
    apply_fn = _apply_writes({1: ("a.py", "double = 1"), 2: ("b.py", "triple = 1")})

    sleep_s = 0.3
    spans: dict[int, tuple[float, float]] = {}

    # `run_worktree_wave` calls `apply_fn(wt_path, task_indices)` per lane
    # without threading the lane id through, so record each lane's own
    # [start, end) span by task index instead of by lane id, then map it
    # back below -- lane 0 carries task 1, lane 1 carries task 2.
    async def _sleepy_apply(wt_path: Path, task_indices):
        lane_id = task_indices[0]
        t0 = time.perf_counter()
        await asyncio.sleep(sleep_s)
        t1 = time.perf_counter()
        spans[lane_id] = (t0, t1)
        return await apply_fn(wt_path, task_indices)

    results = asyncio.run(ww.run_worktree_wave(
        git_repo, git_repo / ".simplicio-loop" / "run", lanes, base, _sleepy_apply,
    ))

    assert {r.status for r in results} == {"applied"}
    assert set(spans) == {1, 2}
    (start_1, end_1), (start_2, end_2) = spans[1], spans[2]
    # Real concurrency: each lane's sleep window must overlap the other's,
    # not just "the whole run finished quickly" (a wall-clock bound can pass
    # by coincidence on a slow/loaded machine, or hide a regression to
    # serial execution on a fast one). Overlap means lane 1 starts before
    # lane 2 ends AND lane 2 starts before lane 1 ends.
    assert start_1 < end_2 and start_2 < end_1

    def _reapply(lane_id, task_indices):
        raise AssertionError("no conflict expected in this test")

    outcome = ww.integrate_lane_results(git_repo, results, _reapply)
    assert outcome["failed_lanes"] == []
    assert outcome["repaired_lanes"] == []
    assert sorted(outcome["integrated_lanes"]) == [1, 2]
    assert "double = 1" in (git_repo / "a.py").read_text()
    assert "triple = 1" in (git_repo / "b.py").read_text()

    ww.cleanup_worktrees(git_repo, results)
    worktree_list = _git(git_repo, "worktree", "list")
    assert str(git_repo / ".simplicio-loop" / "run" / "wt") not in worktree_list


def test_lane_that_no_longer_applies_falls_back_to_serial_reapply(git_repo):
    base = _git(git_repo, "rev-parse", "HEAD").strip()
    lanes = [[1]]
    apply_fn = _apply_writes({1: ("a.py", "double = 1")})

    results = asyncio.run(ww.run_worktree_wave(git_repo, git_repo / ".simplicio-loop" / "run", lanes, base, apply_fn))
    assert results[0].status == "applied"

    # Simulate the integrated tree moving under the lane's patch: someone
    # else touches the exact same line before integration runs.
    (git_repo / "a.py").write_text("# a\nconflicting change\n", encoding="utf-8")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-m", "advance base")

    repaired_calls = []

    def _reapply(lane_id, task_indices):
        repaired_calls.append((lane_id, list(task_indices)))
        with (git_repo / "a.py").open("a", encoding="utf-8") as fh:
            fh.write("double = 1 (repaired)\n")

    outcome = ww.integrate_lane_results(git_repo, results, _reapply)
    assert outcome["failed_lanes"] == []
    assert outcome["repaired_lanes"] == [1]
    assert repaired_calls == [(1, [1])]
    assert "double = 1 (repaired)" in (git_repo / "a.py").read_text()


def test_lane_apply_failure_is_recorded_and_never_integrated(git_repo):
    base = _git(git_repo, "rev-parse", "HEAD").strip()
    lanes = [[1]]

    async def _failing_apply(wt_path: Path, task_indices):
        return {"applied": False}

    results = asyncio.run(ww.run_worktree_wave(git_repo, git_repo / ".simplicio-loop" / "run", lanes, base, _failing_apply))
    assert results[0].status == "failed"

    def _reapply(lane_id, task_indices):
        raise AssertionError("a never-applied lane must not be re-applied")

    outcome = ww.integrate_lane_results(git_repo, results, _reapply)
    assert outcome["failed_lanes"] == [1]
    assert outcome["integrated_lanes"] == []


def test_lane_verifier_failure_blocks_integration_of_that_lane(git_repo):
    base = _git(git_repo, "rev-parse", "HEAD").strip()
    lanes = [[1]]
    apply_fn = _apply_writes({1: ("a.py", "double = 1")})

    results = asyncio.run(ww.run_worktree_wave(
        git_repo, git_repo / ".simplicio-loop" / "run", lanes, base, apply_fn,
        verifier_for=lambda lane_id: f"{sys.executable} -c \"import sys; sys.exit(1)\"",
    ))
    assert results[0].status == "failed"
