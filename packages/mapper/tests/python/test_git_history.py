from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from simplicio_mapper.git_history import HISTORY_SCHEMA, HistoryError, build_git_history


def _git(root: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        close_fds=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _commit(root: Path, message: str) -> str:
    _git(root, "add", ".")
    _git(root, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", message)
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        close_fds=True,
        check=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    (root / "a.py").write_text("a = 1\n", encoding="utf-8")
    (root / "b.py").write_text("b = 1\n", encoding="utf-8")
    _commit(root, "contains secret-like subject that must not be exported")
    return root


def test_history_is_bounded_deterministic_and_redacts_commit_text(tmp_path):
    root = _repo(tmp_path)
    first = build_git_history(root, max_commits=10)
    second = build_git_history(root, max_commits=10)
    assert first == second
    assert first["schema"] == HISTORY_SCHEMA
    assert first["provenance"]["diffs_included"] is False
    assert all("author" not in node and "subject" not in node for node in first["nodes"])
    assert any(edge["kind"] == "changed_with" for edge in first["edges"])
    assert len(first["commits"]) == 1


def test_rename_and_incremental_after_commit_emit_handles(tmp_path):
    root = _repo(tmp_path)
    baseline = build_git_history(root)
    _git(root, "mv", "a.py", "renamed.py")
    new_head = _commit(root, "rename")
    history = build_git_history(root, after_commit=baseline["head"])
    assert history["base_commit"] == baseline["head"]
    assert history["head"] == new_head
    assert any(change["kind"] == "renamed" for commit in history["commits"] for change in commit["changes"])
    assert any(edge["kind"] == "renamed_from" for edge in history["edges"])
    assert history["handles"]


def test_invalid_root_and_budget_fail_closed(tmp_path):
    with pytest.raises(HistoryError, match="not a git repository"):
        build_git_history(tmp_path)
    root = _repo(tmp_path)
    with pytest.raises(HistoryError, match="between"):
        build_git_history(root, max_commits=0)


def test_test_cochange_edges_and_consumer_provenance(tmp_path):
    root = _repo(tmp_path)
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    (root / "a.py").write_text("a = 2\n", encoding="utf-8")
    _commit(root, "fix with test")
    history = build_git_history(root, max_commits=20)
    kinds = {edge["kind"] for edge in history["edges"]}
    assert "tested_by" in kinds
    assert "fixed_with" in kinds
    assert history["schema"] == HISTORY_SCHEMA
    assert history["provenance"]["consumer"] == "simplicio-fast"
    assert history["provenance"]["owner"] == "simplicio-mapper"
    assert "reverts" in history["provenance"]["edge_kinds"]
