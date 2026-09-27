"""Concurrency behaviour for `simplicio_loop.apply` (issue #1310): two
independent chains' checks run concurrently, not serially."""
from __future__ import annotations

import json
import subprocess
import time

import pytest

from simplicio_loop import apply as apply_mod


def seed_mapper_survey(root):
    """Write the minimal Mapper survey `simplicio-loop apply` requires
    (issue #1318; issue #1343 removed Fast from the stack entirely): the
    Mapper project map and the brief's per-task Mapper provenance, as a
    real `orient --brief` leaves them."""
    state = root / ".simplicio-loop"
    state.mkdir(parents=True, exist_ok=True)
    (state / "project-map.json").write_text("{}", encoding="utf-8")
    (state / "survey.json").write_text(json.dumps({"generations": [{
        "task": "t", "operator": "simplicio-mapper",
        "generation": "sha256:test", "context_hash": "sha256:test"}]}), encoding="utf-8")


@pytest.fixture(autouse=True)
def _mapper_survey(request, tmp_path):
    if request.node.get_closest_marker("no_survey") is None:
        seed_mapper_survey(tmp_path)


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
    # Dev-cli startup is part of each chain and varies by machine. Overlap is
    # wall clock against the sum of the two recorded chains: a serial run is
    # about that sum, a concurrent run is about the slower chain.
    chain_s = sum(
        task["apply_duration_s"] + task["check"]["duration_s"] for task in result["tasks"]
    )
    assert elapsed < chain_s * 0.75, (
        f"expected overlapping chains, wall {elapsed:.2f}s vs sum {chain_s:.2f}s"
    )
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
