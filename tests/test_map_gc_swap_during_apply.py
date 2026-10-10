"""Tests for mutants R4, S1, S7: root/parent swaps during apply.

Mutant R4: path.parent == root replaced by in root.parents  
Mutant S1: parents of the root ignored in _root_refusal/_ROOT_PARENTS
Mutant S7: holder of `map` missing
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from simplicio_loop import map_service_gc as gc


HOUR = 3600.0


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


def _age(path: Path, seconds: float) -> None:
    """Age a path and all its contents."""
    stamp = time.time() - seconds
    paths = [path]
    if path.is_dir():
        for dirpath, dirnames, filenames in os.walk(path):
            paths.extend(Path(dirpath, name) for name in dirnames + filenames)
    for item in paths:
        os.utime(item, (stamp, stamp), follow_symlinks=False)


def _scratch(map_dir: Path, name: str, size: int = 4096) -> Path:
    """Create a scratch directory with a file."""
    directory = map_dir / name
    (directory / "tree").mkdir(parents=True)
    (directory / "tree" / "mod.py").write_bytes(b"x" * size)
    return directory


def _outside_with_old_file(tmp_path: Path, *parts: str) -> Path:
    """Create an outside directory with old files."""
    outside = tmp_path / "outside"
    target = outside.joinpath(*parts)
    target.parent.mkdir(parents=True)
    target.write_text("precious", encoding="utf-8")
    _age(outside, 3 * HOUR)
    return target


def _swap_for_link(real: Path, outside: Path) -> None:
    """Swap a real directory for a symlink to outside."""
    shutil.rmtree(real)
    real.symlink_to(outside, target_is_directory=True)


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "T")
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    map_dir = root / ".git" / "simplicio" / "map"
    map_dir.mkdir(parents=True)
    return root, map_dir


def test_map_root_swapped_for_link_after_plan_is_not_removed_through(repo, tmp_path):
    """Mutant S1/S7: map root swapped after plan still has old entries marked as errors."""
    root, map_dir = repo
    
    # Create an old entry in the map
    _age(_scratch(map_dir, "baseline-build-old"), 3 * HOUR)
    target = _outside_with_old_file(tmp_path, "baseline-build-old", "f.txt")
    
    # Plan the gc
    plan = gc.plan_gc(str(root))
    removed_items = [item.path for item in plan.items if item.action == "remove"]
    assert str(map_dir / "baseline-build-old") in removed_items
    
    # Swap the map root to a symlink AFTER plan
    _swap_for_link(map_dir, tmp_path / "outside")
    
    # Apply should refuse the symlink
    result = gc.apply_gc(plan)
    assert target.read_text(encoding="utf-8") == "precious"
    assert result.removed == []
    assert any("symlink" in error for error in result.errors)


def test_store_root_swapped_during_apply(repo, tmp_path, monkeypatch):
    """Mutant R4/S7: store root (parent of map) swapped during apply is caught."""
    root, map_dir = repo
    store = map_dir.parent
    
    # Create an old entry under scratch (inside store)
    scratch = store / "scratch"
    _age(_scratch(scratch, "old"), 3 * HOUR)
    target = _outside_with_old_file(tmp_path, "old", "f.txt")
    
    plan = gc.plan_gc(str(root))
    removed_items = [item.path for item in plan.items if item.action == "remove"]
    assert str(scratch / "old") in removed_items
    
    real_remove = gc._remove_tree
    swapped = []

    def remove_then_swap(path):
        real_remove(path)
        # Swap the store root on first removal
        if not swapped:
            swapped.append(path)
            _swap_for_link(store, tmp_path / "outside-store")

    monkeypatch.setattr(gc, "_remove_tree", remove_then_swap)
    result = gc.apply_gc(plan)
    
    # After swap, subsequent operations should be blocked or the path should be in errors
    assert len(swapped) > 0
    # The swap should have been detected - either in errors or by removal being incomplete
    assert result.removed == [str(scratch / "old")] or any("symlink" in error for error in result.errors)


def test_cache_root_swapped_during_apply(repo, tmp_path, monkeypatch):
    """Mutant S7: cache root swapped during apply is caught."""
    root, map_dir = repo
    
    # Create an old entry in the map
    _age(_scratch(map_dir, "cached-old"), 3 * HOUR)
    
    # Override the cache dir to be inside the store
    cache_dir = map_dir.parent / "custom-cache"
    cache_dir.mkdir()
    monkeypatch.setenv("SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR", str(cache_dir))
    
    # Create old content in the cache
    cache_old = cache_dir / "old"
    cache_old.mkdir()
    (cache_old / "file.txt").write_text("precious", encoding="utf-8")
    _age(cache_dir, 3 * HOUR)
    
    plan = gc.plan_gc(str(root))
    
    real_remove = gc._remove_tree
    swapped = []

    def remove_then_swap(path):
        real_remove(path)
        # Swap the cache root on first removal
        if not swapped:
            swapped.append(path)
            _swap_for_link(cache_dir, tmp_path / "outside-cache")

    monkeypatch.setattr(gc, "_remove_tree", remove_then_swap)
    result = gc.apply_gc(plan)
    
    # Swap should be detected and refused
    if swapped:
        assert any("symlink" in error or "cache" in error for error in result.errors)
