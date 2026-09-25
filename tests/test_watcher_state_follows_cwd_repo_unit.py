"""Run from a user repo, the watcher reads and writes that repo's loop state."""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "watcher_verify.py"


def _load(monkeypatch, cwd):
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("SIMPLICIO_LOOP_REPO", raising=False)
    monkeypatch.delenv("SIMPLICIO_LOOP_DIR", raising=False)
    spec = importlib.util.spec_from_file_location("watcher_verify_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_state_repo_defaults_to_the_cwd_git_toplevel(monkeypatch, tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "pkg").mkdir()
    module = _load(monkeypatch, tmp_path / "pkg")
    assert os.path.realpath(module.REPO) == os.path.realpath(tmp_path)
    assert os.path.realpath(module.LOOP_DIR).startswith(os.path.realpath(tmp_path))


def test_explicit_override_still_wins(monkeypatch, tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("SIMPLICIO_LOOP_REPO", str(other))
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location("watcher_verify_override", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert os.path.realpath(module.REPO) == os.path.realpath(other)
