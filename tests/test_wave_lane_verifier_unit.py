"""AGENTS.md wave-safeguards item 5: `run_worktree_wave`'s `verifier_for` hook
was accepted by `_wave_worktree_dispatch` never at all -- the call site never
passed it, so a lane's changes were always integrated regardless of any
declared verification command (dead code in `wave_worktree.py`, never wired
in `runner.py`). It is wired here to the same ``SIMPLICIO_TEST_CMD`` signal
`task_contract.py` already turns into a task's ``verification_commands``
entry, so a lane whose declared test command fails is never integrated.
"""
from __future__ import annotations

import subprocess
import sys
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


def _items(repo: Path, run_id: str):
    return [
        {"task_index": 1, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["a.txt"]}},
        {"task_index": 2, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["b.txt"]}},
    ]


def _make_fake_dispatch():
    def fake(item, retry_budget, owned_process_registry=None):
        task_index = int(item["task_index"])
        repo_dir = Path(item["repo"])
        (repo_dir / ("a.txt" if task_index == 1 else "b.txt")).write_text(f"lane-{task_index}\n", encoding="utf-8")
        return [{
            "schema": "simplicio.operator-worker/v1", "task_index": task_index,
            "run_id": item["run_id"], "repo": item["repo"], "status": "succeeded",
            "execution_state": "applied", "dead_letter": False,
            "operator_receipt": "", "evidence_receipt": "",
        }]
    return fake


def test_no_verifier_declared_integrates_normally(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    monkeypatch.delenv("SIMPLICIO_TEST_CMD", raising=False)
    repo = _init_repo(tmp_path)
    run_id = "wave-run-no-verifier"
    run_dir = _seed_run_dir(repo, run_id)
    patch_runner(monkeypatch, "_run_operator_item_process", _make_fake_dispatch())

    result = runner_mod._wave_worktree_dispatch(
        repo_path=repo, run_id=run_id, run_dir=run_dir,
        items=_items(repo, run_id), retry_budget=0, max_workers=2,
    )

    assert result is not None
    assert result["completed_task_indices"] == [1, 2]
    assert (repo / "a.txt").read_text() == "lane-1\n"
    assert (repo / "b.txt").read_text() == "lane-2\n"


def test_failing_verification_command_blocks_every_lane_from_integrating(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", f"{sys.executable} -c \"import sys; sys.exit(1)\"")
    repo = _init_repo(tmp_path)
    run_id = "wave-run-failing-verifier"
    run_dir = _seed_run_dir(repo, run_id)
    patch_runner(monkeypatch, "_run_operator_item_process", _make_fake_dispatch())

    result = runner_mod._wave_worktree_dispatch(
        repo_path=repo, run_id=run_id, run_dir=run_dir,
        items=_items(repo, run_id), retry_budget=0, max_workers=2,
    )

    assert result is not None
    # Every lane's verifier failed -- nothing reaches the main repo. The
    # underlying per-task work itself "succeeded" in isolation, so this is
    # reported as blocked (retryable), never as a dead-lettered failure.
    assert result["completed_task_indices"] == []
    assert result["blocked_task_indices"] == [1, 2]
    assert result["dead_letter_task_indices"] == []
    for record in result["workers"]:
        assert record["reason_code"] == "wave_lane_not_integrated"
    assert (repo / "a.txt").read_text() == "orig-a\n"
    assert (repo / "b.txt").read_text() == "orig-b\n"


def test_passing_verification_command_still_integrates(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", f"{sys.executable} -c \"import sys; sys.exit(0)\"")
    repo = _init_repo(tmp_path)
    run_id = "wave-run-passing-verifier"
    run_dir = _seed_run_dir(repo, run_id)
    patch_runner(monkeypatch, "_run_operator_item_process", _make_fake_dispatch())

    result = runner_mod._wave_worktree_dispatch(
        repo_path=repo, run_id=run_id, run_dir=run_dir,
        items=_items(repo, run_id), retry_budget=0, max_workers=2,
    )

    assert result is not None
    assert result["completed_task_indices"] == [1, 2]
    assert (repo / "a.txt").read_text() == "lane-1\n"
    assert (repo / "b.txt").read_text() == "lane-2\n"
