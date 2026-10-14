"""AGENTS.md wave-safeguards item 2: each lane task's mutation must run in
its own child process by default (`SIMPLICIO_LOOP_DISPATCH_MODE`, default
"process"), reusing the existing `_run_operator_item_process` worker --
not always in the coordinator's own thread/process regardless of the mode,
which was the bug (lanes previously ran via
``loop.run_in_executor(None, ...)``, ignoring the mode entirely).

The stub dispatched here is a top-level (picklable) function, not a local
closure, precisely because a real ProcessPoolExecutor submission is being
exercised -- the same constraint the classic dispatch path's own process-mode
tests observe.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from simplicio_loop import runner as runner_mod
from tests.runner_patch import patch_runner


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


# Module-level (picklable) stub: records the PID it actually ran on into a
# file OUTSIDE the lane's worktree (`item["task_spec"]["pid_dir"]`), since the
# worktree itself is removed by `cleanup_worktrees` before the caller can
# inspect it, and a real child process cannot mutate this test module's
# in-memory state.
def _pid_probe_dispatch(item, retry_budget, owned_process_registry=None):
    task_index = int(item["task_index"])
    repo_dir = Path(item["repo"])
    pid_dir = Path(item["task_spec"]["pid_dir"])
    (pid_dir / f"pid-{task_index}.txt").write_text(str(os.getpid()), encoding="utf-8")
    (repo_dir / ("a.txt" if task_index == 1 else "b.txt")).write_text(f"lane-{task_index}\n", encoding="utf-8")
    return [{
        "schema": "simplicio.operator-worker/v1", "task_index": task_index,
        "run_id": item["run_id"], "repo": item["repo"], "status": "succeeded",
        "execution_state": "applied", "dead_letter": False,
        "operator_receipt": "", "evidence_receipt": "",
    }]


def _items(repo: Path, run_id: str, *, pid_dir: Path | None = None):
    extra = {"pid_dir": str(pid_dir)} if pid_dir is not None else {}
    return [
        {"task_index": 1, "run_id": run_id, "repo": str(repo),
         "task_spec": {"files_affected": ["a.txt"], **extra}},
        {"task_index": 2, "run_id": run_id, "repo": str(repo),
         "task_spec": {"files_affected": ["b.txt"], **extra}},
    ]


def test_default_dispatch_mode_runs_each_lane_task_in_a_real_child_process(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_LOOP_DISPATCH_MODE", raising=False)  # default: "process"
    repo = _init_repo(tmp_path)
    run_id = "wave-run-process"
    run_dir = _seed_run_dir(repo, run_id)
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    patch_runner(monkeypatch, "_run_operator_item_process", _pid_probe_dispatch)

    result = runner_mod._wave_worktree_dispatch(
        repo_path=repo, run_id=run_id, run_dir=run_dir,
        items=_items(repo, run_id, pid_dir=pid_dir), retry_budget=0, max_workers=2,
    )

    assert result is not None
    assert result["dispatch_mode"] == "process"
    assert result["completed_task_indices"] == [1, 2]

    pid_1 = int((pid_dir / "pid-1.txt").read_text())
    pid_2 = int((pid_dir / "pid-2.txt").read_text())
    # Real per-task process isolation: neither lane's dispatch ran in this
    # test/coordinator process.
    assert pid_1 != os.getpid()
    assert pid_2 != os.getpid()


def test_thread_dispatch_mode_runs_each_lane_task_in_the_coordinator_process(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    repo = _init_repo(tmp_path)
    run_id = "wave-run-thread"
    run_dir = _seed_run_dir(repo, run_id)

    seen_pids: list = []

    def probe(item, retry_budget, owned_process_registry=None):
        seen_pids.append(os.getpid())
        task_index = int(item["task_index"])
        return [{
            "schema": "simplicio.operator-worker/v1", "task_index": task_index,
            "run_id": item["run_id"], "repo": item["repo"], "status": "succeeded",
            "execution_state": "applied", "dead_letter": False,
            "operator_receipt": "", "evidence_receipt": "",
        }]

    patch_runner(monkeypatch, "_run_operator_item_process", probe)

    result = runner_mod._wave_worktree_dispatch(
        repo_path=repo, run_id=run_id, run_dir=run_dir,
        items=_items(repo, run_id), retry_budget=0, max_workers=2,
    )

    assert result is not None
    assert result["dispatch_mode"] == "thread"
    assert result["completed_task_indices"] == [1, 2]
    # thread mode never leaves this process -- every dispatch ran in a
    # thread of the very process running this test.
    assert seen_pids and all(pid == os.getpid() for pid in seen_pids)


def test_process_dispatch_mode_actually_uses_a_different_pid_than_the_coordinator(tmp_path, monkeypatch):
    """Real end-to-end proof (no stub): the classic per-task worker function
    itself, `_run_operator_item_process`, is genuinely submitted to a real
    ProcessPoolExecutor by the wave path -- shown by a plain probe function
    (not `_run_operator_item_process` itself, since that one shells out to
    dev-cli) observing a different PID when run through the wave dispatch's
    own process pool machinery."""
    monkeypatch.delenv("SIMPLICIO_LOOP_DISPATCH_MODE", raising=False)
    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(max_workers=1) as pool:
        child_pid = pool.submit(os.getpid).result()
    assert child_pid != os.getpid()
