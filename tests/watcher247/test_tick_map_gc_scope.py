"""Tests for mutant J: scope of tick sweep - _map_gc_bases only visits correct directories.

Mutant J: iterate config.WORK.parent instead of config.WORK
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from simplicio_loop.watcher247 import config, tick
from simplicio_loop import map_gc_auto


def test_map_gc_bases_visits_only_git_repos_under_work(tmp_path, monkeypatch):
    """Test that _map_gc_bases only processes directories under config.WORK that have .git."""
    # Set up config.WORK
    monkeypatch.setattr(config, "WORK", tmp_path / "work")
    config.WORK.mkdir()
    
    # Create test directories
    (config.WORK / "repo-a.wt").mkdir()  # Should NOT be visited (ends with .wt)
    (config.WORK / "repo-a.state").mkdir()  # Should NOT be visited (ends with .state)
    (config.WORK / "no-git").mkdir()  # Should NOT be visited (no .git)
    
    # Create valid base clone (has .git)
    base_repo = config.WORK / "base-clone"
    base_repo.mkdir()
    (base_repo / ".git").mkdir()
    
    # Spy on maybe_gc
    calls = []
    def spy_maybe_gc(path):
        calls.append(path)
    
    monkeypatch.setattr(map_gc_auto, "maybe_gc", spy_maybe_gc)
    
    # Call _map_gc_bases
    tick._map_gc_bases()
    
    # Should only have called maybe_gc for the base-clone
    assert calls == [str(base_repo)], f"Expected ['{base_repo}'], got {calls}"


def test_map_gc_bases_skips_parent_of_work(tmp_path, monkeypatch):
    """Test that mutant J (iterating config.WORK.parent) is caught."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    monkeypatch.setattr(config, "WORK", work_dir)
    
    # Create a directory in WORK.parent with .git (should NOT be scanned)
    parent_repo = work_dir.parent / "parent-repo"
    parent_repo.mkdir()
    (parent_repo / ".git").mkdir()
    
    # Create a valid repo in WORK
    work_repo = work_dir / "work-repo"
    work_repo.mkdir()
    (work_repo / ".git").mkdir()
    
    calls = []
    def spy_maybe_gc(path):
        calls.append(path)
    
    monkeypatch.setattr(map_gc_auto, "maybe_gc", spy_maybe_gc)
    
    tick._map_gc_bases()
    
    # Should only visit work-repo, NOT parent-repo
    assert [work_repo] == [Path(c) for c in calls], f"Should only visit work-repo, got {calls}"
    assert str(parent_repo) not in calls, f"Should not visit parent dir: {calls}"


def test_map_gc_bases_handles_empty_work(tmp_path, monkeypatch):
    """Test that _map_gc_bases handles an empty WORK directory gracefully."""
    monkeypatch.setattr(config, "WORK", tmp_path / "empty-work")
    config.WORK.mkdir()
    
    calls = []
    def spy_maybe_gc(path):
        calls.append(path)
    
    monkeypatch.setattr(map_gc_auto, "maybe_gc", spy_maybe_gc)
    
    # Should not crash and should call maybe_gc zero times
    tick._map_gc_bases()
    assert calls == [], f"Should not call maybe_gc for empty WORK: {calls}"


def test_map_gc_bases_handles_work_missing(tmp_path, monkeypatch):
    """Test that _map_gc_bases handles WORK directory not existing."""
    monkeypatch.setattr(config, "WORK", tmp_path / "missing-work")
    
    calls = []
    def spy_maybe_gc(path):
        calls.append(path)
    
    monkeypatch.setattr(map_gc_auto, "maybe_gc", spy_maybe_gc)
    
    # Should not crash, just return
    tick._map_gc_bases()
    assert calls == [], f"Should handle missing WORK gracefully: {calls}"
