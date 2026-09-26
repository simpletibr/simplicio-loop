"""Evidence and watcher fingerprint the run's diff the same way, and the loop's
own bookkeeping under .simplicio-loop/ (which changes between the two) is excluded."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

from simplicio_loop.evidence import _git_meta

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "watcher_verify.py"


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "init"], check=True)
    return tmp_path


def _watcher():
    spec = importlib.util.spec_from_file_location("watcher_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_loop_bookkeeping_does_not_change_the_fingerprint(tmp_path):
    repo = _repo(tmp_path)
    (repo / "app.py").write_text("x = 2\n")
    before = _git_meta(repo)["diff_hash"]
    (repo / ".simplicio-loop" / "loop-runs").mkdir(parents=True)
    (repo / ".simplicio-loop" / "loop-runs" / "state.json").write_text("{}")
    assert _git_meta(repo)["diff_hash"] == before


def test_watcher_and_evidence_agree_on_a_modified_tracked_file(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    (repo / "app.py").write_text("x = 2\n")
    monkeypatch.setenv("SIMPLICIO_LOOP_REPO", str(repo))
    assert _watcher()._git_meta(worktree=str(repo))["diff_hash"] == _git_meta(repo)["diff_hash"]
