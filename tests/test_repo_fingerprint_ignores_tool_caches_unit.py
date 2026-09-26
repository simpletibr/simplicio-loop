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


def _write_coverage_byproducts(repo):
    # pytest-cov's own regenerated data file(s) and HTML report dir -- the
    # exact byproducts a task's own "Coverage verifier" lane writes to the
    # repo root while running (issue: multiprocess tick chain, coverage.py
    # rewrites `.coverage` with fresh, non-deterministic content on every
    # run, same non-source-drift category as .pytest_cache/__pycache__).
    (repo / ".coverage").write_bytes(b"sqlite-or-whatever-coverage-writes-1")
    (repo / ".coverage.host.12345.XXXXXX").write_bytes(b"parallel-mode-data")
    (repo / "htmlcov").mkdir()
    (repo / "htmlcov" / "index.html").write_text("<html></html>")


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


def test_fingerprint_ignores_coverage_tool_byproducts(tmp_path):
    """BUG 2 (multiprocess tick chain) regression: `.coverage` is regenerated
    by a task's own Coverage verifier lane between one tick process and the
    next, with different bytes each run. If it counts toward the repository
    fingerprint, `state["repo_state_chain"]" (persisted right after the dev-
    cli mutation, before the verifier lane runs) can never match a fresh
    ``_repo_fingerprint`` read by a later task's own separate process --
    turning the run's own verifier byproduct into false "repository changed
    after planning" / "plan_repo_state_stale" drift.
    """
    repo = _git_repo(tmp_path)
    before = runner._repo_fingerprint(repo)
    _write_coverage_byproducts(repo)
    assert runner._repo_fingerprint(repo) == before
    assert runner._plan_relevant_changed_paths(repo) == []


def test_fingerprint_still_detects_source_edits_alongside_coverage_byproducts(tmp_path):
    """The coverage-byproduct exclusion must not swallow a real source edit
    that happens to land at the same time (external edits still fail closed).
    """
    repo = _git_repo(tmp_path)
    before = runner._repo_fingerprint(repo)
    _write_coverage_byproducts(repo)
    (repo / "app.py").write_text("x = 2\n")
    assert runner._repo_fingerprint(repo) != before
