"""Gap tests for simplicio_loop map GC (#1574): mutants for recent baselines, apply-time re-check, and lock handling."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

from simplicio_loop import map_service_gc as gc

HOUR = 3600.0


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
    ).stdout.strip()


def _repo(root: Path) -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "T")
    (root / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def _age(path: Path, seconds: float) -> None:
    """Make ``path`` (and everything under it) look ``seconds`` old."""
    stamp = time.time() - seconds
    paths = [path]
    if path.is_dir():
        for dirpath, dirnames, filenames in os.walk(path):
            paths.extend(Path(dirpath, name) for name in dirnames + filenames)
    for item in paths:
        os.utime(item, (stamp, stamp))


def _baseline(map_dir: Path, name: str) -> Path:
    """Create a baseline JSON file with the given name."""
    baseline = map_dir / name
    baseline.write_text('{"tree":"abc","commit":"def"}', encoding="utf-8")
    return baseline


@pytest.fixture()
def repo(tmp_path):
    root = _repo(tmp_path / "repo")
    map_dir = root / ".git" / "simplicio" / "map"
    map_dir.mkdir(parents=True)
    return root, map_dir


def test_a1_recent_baseline_30s_old_unreferenced_is_kept_with_reason_written_moments_ago(repo):
    """A Runtime baseline file written ~30 s ago, unreferenced, keep=0, must be planned as action keep.
    
    Mutant: delete the `elif now - mtime < RECENT_BASELINE_SECONDS:` branch in _classify_baselines.
    """
    root, map_dir = repo
    now = time.time()
    baseline = _baseline(map_dir, "baseline-" + "a" * 40 + ".json")
    _age(baseline, 30.0)  # Set mtime to now-30s
    
    plan = gc.plan_gc(str(root), keep=0, now=now)
    items = [item for item in plan.items if item.kind == "baseline"]
    
    assert len(items) == 1
    assert items[0].action == "keep"
    assert items[0].reason == "written_moments_ago"


def test_a2_apply_time_re_check_keeps_file_aged_to_recent(repo):
    """Apply-time re-check: build a plan for OLD (100 h) unreferenced baseline, then age to now-5 s.
    
    The file must still exist after apply_gc (kept due to recent mtime check).
    Mutant: delete the `if now - path.lstat().st_mtime < RECENT_BASELINE_SECONDS: return False` check in _still_safe.
    """
    root, map_dir = repo
    now = time.time()
    baseline = _baseline(map_dir, "baseline-" + "b" * 40 + ".json")
    _age(baseline, 100 * HOUR)  # Initially mark as very old
    
    # Plan should mark it for removal (old file, keep=0)
    plan = gc.plan_gc(str(root), keep=0, now=now)
    items = [item for item in plan.items if item.kind == "baseline"]
    assert len(items) == 1
    assert items[0].action == "remove", f"Expected remove, got {items[0].reason}"
    
    # Now age the file to just 5 seconds old (in real time) - this happens between plan and apply
    _age(baseline, 5.0)
    
    # Apply should not remove it because _still_safe checks current mtime
    result = gc.apply_gc(plan)
    assert baseline.exists(), "File should be kept due to recent mtime in apply-time re-check"


def test_a3_referenced_keys_includes_default_branch_tree(repo):
    """The central base (default-branch tree) is always counted as referenced.
    
    A repo where main moved on (2 commits), the checkout is on a feature branch forked at the old commit.
    A baseline for the CURRENT default-branch tree, aged 100h, keep=0 should be kept with reason "referenced_by_worktree".
    
    Mutant: delete `runtime.add(base.tree)` in referenced_keys (the block `if base is not None: runtime.add(base.tree)`).
    """
    root, map_dir = repo
    now = time.time()
    
    # Get the current main tree (before moving forward)
    first_main_tree = _git(root, "rev-parse", "main^{tree}")
    
    # Create a feature branch at the current commit
    _git(root, "checkout", "-b", "feature")
    
    # Now move main forward with 2 new commits
    _git(root, "checkout", "main")
    (root / "b.py").write_text("def b():\n    return 2\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "second")
    (root / "c.py").write_text("def c():\n    return 3\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "third")
    
    # Go back to the feature branch (so the checkout is NOT on main)
    _git(root, "checkout", "feature")
    
    # Get the new default-branch tree hash
    current_main_tree = _git(root, "rev-parse", "main^{tree}")
    
    # They should be different now
    assert current_main_tree != first_main_tree
    
    # Create a baseline file for the CURRENT main tree
    baseline = _baseline(map_dir, f"baseline-{current_main_tree}.json")
    _age(baseline, 100 * HOUR)  # Old file
    
    # Plan should mark it as keep because it matches the default-branch tree
    plan = gc.plan_gc(str(root), keep=0, now=now)
    items = [item for item in plan.items if item.kind == "baseline" and item.path == str(baseline)]
    
    assert len(items) == 1, f"Expected 1 baseline item, got {len(items)}"
    assert items[0].action == "keep", f"Expected keep, got {items[0].action}"
    assert items[0].reason == "referenced_by_worktree"


def test_a4_old_scratch_with_unreadable_lock_is_kept(repo, monkeypatch):
    """A scratch dir older than 5h whose build.lock cannot be inspected is KEPT.
    
    Monkeypatch inspect_lock_at to raise RuntimeError.
    Mutant: in _lock_is_live change `except Exception: return True` to `return False`.
    """
    root, map_dir = repo
    now = time.time()
    
    # Create a scratch directory
    scratch = map_dir / "baseline-build-testlock"
    scratch.mkdir(parents=True)
    (scratch / "tree").mkdir()
    (scratch / "tree" / "file.txt").write_text("x" * 100, encoding="utf-8")
    (scratch / "build.lock").write_bytes(b"lock")
    
    _age(scratch, 5 * HOUR)  # Mark as very old
    
    # Monkeypatch inspect_lock_at to raise an exception
    def mock_inspect_lock(path):
        raise RuntimeError("Cannot read lock")
    
    monkeypatch.setattr(
        "simplicio_mapper.mapper.file_lock.inspect_lock_at",
        mock_inspect_lock
    )
    
    # Plan should mark it as keep with reason "lock_held"
    plan = gc.plan_gc(str(root), keep=0, now=now)
    items = [item for item in plan.items if item.kind == "scratch"]
    
    assert len(items) == 1
    assert items[0].action == "keep"
    assert items[0].reason == "lock_held"
