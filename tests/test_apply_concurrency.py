"""Concurrency behaviour for `simplicio_loop.apply` (issue #1310): two
independent chains' checks run concurrently, not serially."""
from __future__ import annotations

import subprocess
import time

from simplicio_loop import apply as apply_mod


def _write(root, rel, content):
    path = root / rel
    path.write_text(content, encoding="utf-8")
    return path


def _git_init(root):
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(root), check=True)


def _git_commit_all(root):
    subprocess.run(["git", "add", "-A"], cwd=str(root), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(root), check=True)


def test_two_independent_sleep_checks_run_concurrently(tmp_path):
    _git_init(tmp_path)
    _write(tmp_path, "a.txt", "hello-a")
    _write(tmp_path, "b.txt", "hello-b")
    _git_commit_all(tmp_path)
    ops = {
        "tasks": [
            {"id": "t1", "operations": [{"path": "a.txt", "find": "hello-a", "replace": "bye-a"}],
             "check": "sleep 1"},
            {"id": "t2", "operations": [{"path": "b.txt", "find": "hello-b", "replace": "bye-b"}],
             "check": "sleep 1"},
        ]
    }
    started = time.monotonic()
    result = apply_mod.run(ops, repo=tmp_path)
    elapsed = time.monotonic() - started
    assert result["status"] == "PASS"
    assert elapsed < 1.8, f"expected concurrent checks under 1.8s, took {elapsed:.2f}s"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "bye-a"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "bye-b"


def test_check_isolation_env_present_in_child(tmp_path):
    _git_init(tmp_path)
    _write(tmp_path, "a.txt", "hello")
    _git_commit_all(tmp_path)
    ops = {
        "tasks": [
            {"id": "t1", "operations": [{"path": "a.txt", "find": "hello", "replace": "bye"}],
             "check": "echo COVERAGE_FILE=$COVERAGE_FILE PYTHONDONTWRITEBYTECODE=$PYTHONDONTWRITEBYTECODE"},
        ]
    }
    result = apply_mod.run(ops, repo=tmp_path)
    assert result["status"] == "PASS"
    tail = result["tasks"][0]["check"]["stdout_tail"]
    assert "PYTHONDONTWRITEBYTECODE=1" in tail
    assert "COVERAGE_FILE=.simplicio-loop/apply/" in tail
