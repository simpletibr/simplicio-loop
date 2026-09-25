"""The verifier's own byproducts must not make a run's plan stale."""
from __future__ import annotations

import subprocess

from simplicio_loop import runner


def _git_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("build/\n")
    (tmp_path / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "init"], check=True)
    return tmp_path


def _write_byproducts(repo):
    (repo / ".pytest_cache").mkdir()
    (repo / ".pytest_cache" / "README.md").write_text("cache")
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "app.cpython-311.pyc").write_bytes(b"\0")
    (repo / "build").mkdir()
    (repo / "build" / "out.txt").write_text("ignored by .gitignore")


def test_fingerprint_ignores_gitignored_files_and_test_caches(tmp_path):
    repo = _git_repo(tmp_path)
    before = runner._repo_fingerprint(repo)
    _write_byproducts(repo)
    assert runner._repo_fingerprint(repo) == before


def test_fingerprint_still_detects_source_edits(tmp_path):
    repo = _git_repo(tmp_path)
    before = runner._repo_fingerprint(repo)
    (repo / "app.py").write_text("x = 2\n")
    assert runner._repo_fingerprint(repo) != before
    (repo / "new.py").write_text("y = 1\n")
    assert "new.py" in runner._plan_relevant_changed_paths(repo)


def test_plan_relevant_changes_skip_python_caches(tmp_path):
    repo = _git_repo(tmp_path)
    _write_byproducts(repo)
    assert runner._plan_relevant_changed_paths(repo) == []
