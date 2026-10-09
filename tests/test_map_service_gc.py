"""`simplicio-loop map gc`: stale build scratch, orphan locks and old bases (#1574).

Root cause of the 6.8 GB leak (measured with the real Simplicio Runtime binary on a synthetic repo):
a one-shot `simplicio context`/`runtime map` that is killed or that exits while the detached
`simplicio-baseline-build` thread is running leaves `<git-common-dir>/simplicio/map/baseline-build-*`
(a full tree copy) and its `baseline-<tree>.lock` behind. Nothing in the loop reclaimed them.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from simplicio_loop import map_service_gc as gc
from simplicio_loop.map_service_cli import run

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


def _scratch(map_dir: Path, name: str, size: int = 2048) -> Path:
    directory = map_dir / name
    (directory / "tree" / "pkg").mkdir(parents=True)
    (directory / "tree" / "pkg" / "mod.py").write_bytes(b"x" * size)
    (directory / "index").write_bytes(b"i" * 64)
    return directory


@pytest.fixture()
def repo(tmp_path):
    root = _repo(tmp_path / "repo")
    map_dir = root / ".git" / "simplicio" / "map"
    map_dir.mkdir(parents=True)
    return root, map_dir


def test_stale_unlocked_scratch_is_listed_with_its_size_and_removed(repo):
    root, map_dir = repo
    stale = _scratch(map_dir, "baseline-build-AbC123")
    _age(stale, 2 * HOUR)

    plan = gc.plan_gc(str(root))
    items = [item for item in plan.items if item.kind == "scratch"]
    assert [item.path for item in items] == [str(stale)]
    assert items[0].bytes >= 2048 + 64
    assert items[0].action == "remove"

    result = gc.apply_gc(plan)
    assert not stale.exists()
    assert result.removed_bytes >= 2048 + 64


def test_fresh_scratch_is_kept(repo):
    root, map_dir = repo
    fresh = _scratch(map_dir, "baseline-build-fresh1")
    plan = gc.plan_gc(str(root))
    gc.apply_gc(plan)
    assert fresh.exists()
    assert all(item.path != str(fresh) or item.action == "keep" for item in plan.items)


def test_old_scratch_that_holds_a_live_lock_is_kept(repo):
    root, map_dir = repo
    locked = _scratch(map_dir, "baseline-build-locked")
    from simplicio_mapper.mapper.file_lock import acquire_lock_at, release_lock_at

    handle = acquire_lock_at(str(locked / "build.lock"), operation="baseline-build")
    assert handle is not None
    try:
        _age(locked, 5 * HOUR)
        plan = gc.plan_gc(str(root))
        gc.apply_gc(plan)
        assert locked.exists(), "a build that still holds its lock must survive the GC"
        item = next(i for i in plan.items if i.path == str(locked))
        assert item.action == "keep" and item.reason == "lock_held"
    finally:
        release_lock_at(handle)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs /proc")
def test_old_scratch_with_a_process_working_inside_it_is_kept(repo):
    root, map_dir = repo
    busy = _scratch(map_dir, "baseline-build-busy")
    _age(busy, 5 * HOUR)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], cwd=str(busy / "tree"),
    )
    try:
        time.sleep(0.3)
        plan = gc.plan_gc(str(root))
        gc.apply_gc(plan)
        assert busy.exists()
        item = next(i for i in plan.items if i.path == str(busy))
        assert item.reason == "process_inside"
    finally:
        child.kill()
        child.wait()


def test_dry_run_changes_nothing_and_reports_every_candidate(repo, capsys):
    root, map_dir = repo
    stale = _scratch(map_dir, "baseline-build-zzz")
    _age(stale, 3 * HOUR)
    lock = map_dir / ("baseline-" + "a" * 40 + ".lock")
    lock.write_bytes(b"")
    _age(lock, 3 * HOUR)

    assert run("gc", repo=str(root), as_json=True, dry_run=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.map-gc/v1"
    assert payload["dry_run"] is True
    assert payload["removed"] == []
    kinds = {item["kind"] for item in payload["items"] if item["action"] == "remove"}
    assert {"scratch", "lock"} <= kinds
    assert payload["would_free_bytes"] > 0
    assert stale.exists() and lock.exists()


def test_real_gc_removes_only_safe_things_and_reports_them(repo, capsys):
    root, map_dir = repo
    stale = _scratch(map_dir, "baseline-build-old")
    _age(stale, 3 * HOUR)
    fresh = _scratch(map_dir, "baseline-build-new")
    stale_lock = map_dir / ("baseline-" + "b" * 40 + ".lock")
    stale_lock.write_bytes(b"")
    _age(stale_lock, 3 * HOUR)
    live_lock = map_dir / ("baseline-" + "c" * 40 + ".lock")
    live_lock.write_bytes(b"")

    assert run("gc", repo=str(root), as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is False
    assert not stale.exists() and not stale_lock.exists()
    assert fresh.exists() and live_lock.exists()
    assert str(stale) in payload["removed"]
    assert payload["freed_bytes"] > 0


def test_non_git_directory_stays_a_reported_noop(tmp_path, capsys):
    assert run("gc", repo=str(tmp_path), as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["removed"] == []
    assert payload["reason_code"] == "standalone_no_store"


def test_runtime_baselines_keep_the_newest_n_and_the_ones_a_worktree_still_forks_from(tmp_path):
    root = _repo(tmp_path / "repo")
    old_tree = _git(root, "rev-parse", "HEAD^{tree}")
    old_wt = tmp_path / "old-wt"
    _git(root, "worktree", "add", "-q", "-b", "old", str(old_wt))
    (root / "b.py").write_text("b = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "main moves")
    new_tree = _git(root, "rev-parse", "HEAD^{tree}")

    map_dir = root / ".git" / "simplicio" / "map"
    map_dir.mkdir(parents=True)
    fillers = []
    for index in range(4):
        path = map_dir / ("baseline-%040x.json" % (index + 1))
        path.write_bytes(b"{}" * 100)
        _age(path, (10 + index) * HOUR)
        fillers.append(path)
    referenced = map_dir / ("baseline-%s.json" % old_tree)
    referenced.write_bytes(b"{}" * 100)
    _age(referenced, 50 * HOUR)  # the oldest of all, yet a live worktree forks from it
    newest = map_dir / ("baseline-%s.json" % new_tree)
    newest.write_bytes(b"{}" * 100)

    plan = gc.plan_gc(str(root), keep=2)
    gc.apply_gc(plan)
    assert newest.exists() and referenced.exists()
    survivors = [path for path in fillers if path.exists()]
    assert len(survivors) == 1, "keep=2 keeps the newest two files in total (newest + one filler)"
    assert survivors[0] == fillers[0]  # the youngest filler


def test_a_baseline_with_a_fresh_build_lock_is_never_removed(repo):
    root, map_dir = repo
    key = "d" * 40
    baseline = map_dir / ("baseline-%s.json" % key)
    baseline.write_bytes(b"{}" * 10)
    _age(baseline, 100 * HOUR)
    (map_dir / ("baseline-%s.lock" % key)).write_bytes(b"")  # a builder is working on it right now
    plan = gc.plan_gc(str(root), keep=0)
    gc.apply_gc(plan)
    assert baseline.exists()


def test_startup_gc_only_reclaims_scratch_and_orphan_locks_never_a_base(repo):
    root, map_dir = repo
    stale = _scratch(map_dir, "baseline-build-startup")
    _age(stale, 4 * HOUR)
    base = map_dir / ("baseline-%s.json" % ("e" * 40))
    base.write_bytes(b"{}" * 10)
    _age(base, 400 * HOUR)

    removed = gc.startup_gc(str(root))
    assert str(stale) in removed
    assert not stale.exists()
    assert base.exists(), "startup GC must never delete a baseline"


def test_startup_gc_never_raises(tmp_path):
    assert gc.startup_gc(str(tmp_path / "does-not-exist")) == []
    assert gc.startup_gc(str(tmp_path)) == []


def test_every_mapper_index_reclaims_stale_scratch_first(repo, monkeypatch):
    """The startup GC runs inside `run_mapper_index`, i.e. before every orient's index."""
    import asyncio

    from simplicio_loop import map_service_mapper as msm

    root, map_dir = repo
    stale = _scratch(map_dir, "baseline-build-beforeindex")
    _age(stale, 6 * HOUR)
    monkeypatch.setattr(msm.shutil, "which", lambda name: None)  # no binary: the index itself fails

    with pytest.raises(msm.MapperUnavailableError):
        asyncio.run(msm.run_mapper_index(str(root)))
    assert not stale.exists()


def test_a_baseline_a_worktree_started_forking_from_after_the_plan_is_not_removed(tmp_path):
    """TOCTOU (found in review): the plan said remove, then a worktree was created at that tree."""
    root = _repo(tmp_path / "repo")
    old_commit = _git(root, "rev-parse", "HEAD")
    old_tree = _git(root, "rev-parse", "HEAD^{tree}")
    (root / "b.py").write_text("b = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "main moves")
    map_dir = root / ".git" / "simplicio" / "map"
    map_dir.mkdir(parents=True)
    baseline = map_dir / ("baseline-%s.json" % old_tree)
    baseline.write_bytes(b"{}" * 50)
    _age(baseline, 100 * HOUR)

    plan = gc.plan_gc(str(root), keep=0)
    item = next(i for i in plan.items if i.path == str(baseline))
    assert item.action == "remove", "nobody forks from the old tree yet"

    _git(root, "worktree", "add", "-q", "-b", "late", str(tmp_path / "late"), old_commit)
    gc.apply_gc(plan)
    assert baseline.exists(), "a worktree now forks from it: the apply-time re-check must keep it"
