"""Tests for mutants R4, S1, S7: root/parent swaps during apply.

Mutant R4: path.parent == root replaced by path.parent in root.parents (line ~309)
Mutant S1: loop over (name,) only, ignoring _ROOT_PARENTS
Mutant S7: holder = None
Mutant P1: _ROOT_PARENTS["map"] emptied
Mutant C1: "cache" removed from the parents of "scratch" and "canonical" in _ROOT_PARENTS

Measured (timeout 90, one run each, against the mutated production code):
  P1 -> FAILED tests/test_map_gc_swap_during_apply.py::test_map_root_store_swapped_during_apply_refuses_later_items
  C1 -> FAILED tests/test_map_gc_swap_during_apply.py::test_cache_root_swapped_during_apply_refuses_later_items
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


def test_store_root_swapped_during_apply_refuses_later_items(repo, tmp_path, monkeypatch):
    """Mutants R4, S1, S7: store root swapped during apply; later items refused with symlink error.
    
    Kills: R4 (_still_safe path.parent == root check), S1 (_root_refusal parents loop),
           S7 (holder of map missing).
    """
    root, map_dir = repo
    store = map_dir.parent
    
    # Create TWO old scratch entries under store/scratch
    scratch = store / "scratch"
    scratch.mkdir()
    (scratch / "old1" / "tree").mkdir(parents=True)
    (scratch / "old1" / "tree" / "mod.py").write_bytes(b"x" * 4096)
    (scratch / "old2" / "tree").mkdir(parents=True)
    (scratch / "old2" / "tree" / "mod.py").write_bytes(b"x" * 4096)
    _age(scratch, 3 * HOUR)
    
    # Create outside directory with SAME names
    outside = tmp_path / "outside"
    (outside / "old1" / "tree").mkdir(parents=True)
    (outside / "old1" / "tree" / "file.txt").write_text("precious", encoding="utf-8")
    (outside / "old2" / "tree").mkdir(parents=True)
    (outside / "old2" / "tree" / "file.txt").write_text("precious", encoding="utf-8")
    _age(outside, 3 * HOUR)
    
    plan = gc.plan_gc(str(root))
    removed_items = [item.path for item in plan.items if item.action == "remove"]
    assert str(scratch / "old1") in removed_items
    assert str(scratch / "old2") in removed_items
    
    real_remove = gc._remove_tree
    removed_count = [0]

    def remove_and_swap(path):
        real_remove(path)
        removed_count[0] += 1
        # On FIRST call only, swap the store root
        if removed_count[0] == 1:
            shutil.rmtree(store)
            store.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(gc, "_remove_tree", remove_and_swap)
    result = gc.apply_gc(plan)
    
    # First removal succeeded, second is refused with symlink error
    assert result.removed == [str(scratch / "old1")], f"Expected only [old1] removed, got {result.removed}"
    assert any(str(scratch / "old2") in error and "symlink" in error for error in result.errors),         f"Expected refused error with 'symlink' for old2 path, got: {result.errors}"
    # Outside files must still exist (not deleted)
    assert (outside / "old1" / "tree" / "file.txt").exists()
    assert (outside / "old2" / "tree" / "file.txt").exists()


def _swap_on_first_remove(monkeypatch, swap):
    """Run ``swap`` right after the FIRST real ``_remove_tree`` call of ``apply_gc``."""
    real_remove = gc._remove_tree
    calls = [0]

    def remove_and_swap(path):
        real_remove(path)
        calls[0] += 1
        if calls[0] == 1:
            swap()

    monkeypatch.setattr(gc, "_remove_tree", remove_and_swap)


def test_map_root_store_swapped_during_apply_refuses_later_items(repo, tmp_path, monkeypatch):
    """Mutant P1: ``_ROOT_PARENTS["map"]`` emptied; the store swapped for a link would not refuse the map root."""
    root, map_dir = repo
    store = map_dir.parent

    first, second = map_dir / "baseline-build-1", map_dir / "baseline-build-2"
    for entry in (first, second):
        (entry / "tree").mkdir(parents=True)
        (entry / "tree" / "mod.py").write_bytes(b"x" * 4096)
    _age(map_dir, 3 * HOUR)

    outside = tmp_path / "outside"
    for name in ("baseline-build-1", "baseline-build-2"):
        (outside / "map" / name / "tree").mkdir(parents=True)
        (outside / "map" / name / "tree" / "file.txt").write_text("precious", encoding="utf-8")
    _age(outside, 3 * HOUR)

    plan = gc.plan_gc(str(root))
    removed_items = [item.path for item in plan.items if item.action == "remove"]
    assert removed_items == [str(first), str(second)]

    def swap():
        shutil.rmtree(store)
        store.symlink_to(outside, target_is_directory=True)

    _swap_on_first_remove(monkeypatch, swap)
    result = gc.apply_gc(plan)

    assert result.removed == [str(first)]
    assert result.errors == ["refused %s: store: symlink" % second]
    assert (outside / "map" / "baseline-build-1" / "tree" / "file.txt").exists()
    assert (outside / "map" / "baseline-build-2" / "tree" / "file.txt").exists()


def test_cache_root_swapped_during_apply_refuses_later_items(repo, tmp_path, monkeypatch):
    """Mutant C1: ``cache`` dropped from the parents of scratch/canonical; a cache root swapped for a link inside the store."""
    root, map_dir = repo
    store = map_dir.parent
    cache = store / "cc"
    monkeypatch.setenv("SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR", str(cache))

    first, second = cache / "scratch" / "s1", cache / "scratch" / "s2"
    for entry in (first, second):
        (entry / "tree").mkdir(parents=True)
        (entry / "tree" / "mod.py").write_bytes(b"x" * 4096)
    _age(cache, 3 * HOUR)

    # Inside the store, so the scratch root alone does not resolve out of it (that would be refused as outside_store).
    other = store / "other"
    for name in ("s1", "s2"):
        (other / "scratch" / name / "tree").mkdir(parents=True)
        (other / "scratch" / name / "tree" / "file.txt").write_text("precious", encoding="utf-8")
    _age(other, 3 * HOUR)

    plan = gc.plan_gc(str(root))
    removed_items = [item.path for item in plan.items if item.action == "remove"]
    assert removed_items == [str(first), str(second)]

    def swap():
        shutil.rmtree(cache)
        cache.symlink_to(other, target_is_directory=True)

    _swap_on_first_remove(monkeypatch, swap)
    result = gc.apply_gc(plan)

    assert result.removed == [str(first)]
    assert result.errors == ["refused %s: cache: symlink" % second]
    assert (other / "scratch" / "s1" / "tree" / "file.txt").exists()
    assert (other / "scratch" / "s2" / "tree" / "file.txt").exists()
