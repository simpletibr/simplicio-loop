"""Automatic `map gc` once an hour and the `map-store` line of `doctor` (#1671)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from simplicio_loop import doctor_overview as dov, map_gc_auto

HOUR = 3600.0


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


def _age(path: Path, seconds: float) -> None:
    stamp = time.time() - seconds
    paths = [path]
    if path.is_dir():
        for dirpath, dirnames, filenames in os.walk(path):
            paths.extend(Path(dirpath, name) for name in dirnames + filenames)
    for item in paths:
        os.utime(item, (stamp, stamp), follow_symlinks=False)  # a link is aged itself, never its target


def _scratch(map_dir: Path, name: str, size: int = 4096) -> Path:
    directory = map_dir / name
    (directory / "tree").mkdir(parents=True)
    (directory / "tree" / "mod.py").write_bytes(b"x" * size)
    return directory


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


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_two_calls_in_less_than_an_hour_run_the_gc_once(repo):
    root, _ = repo
    calls = []
    clock = Clock(1_000_000.0)
    gc = lambda path: calls.append(path) or "ran"
    assert map_gc_auto.maybe_gc(str(root), clock=clock, gc=gc) == "ran"
    clock.now += 30 * 60
    assert map_gc_auto.maybe_gc(str(root), clock=clock, gc=gc) is None
    assert calls == [str(root)]
    clock.now += 31 * 60  # more than an hour after the first run
    assert map_gc_auto.maybe_gc(str(root), clock=clock, gc=gc) == "ran"
    assert len(calls) == 2


def test_the_default_gc_removes_the_stale_leftovers(repo):
    root, map_dir = repo
    stale = _scratch(map_dir, "baseline-build-old")
    _age(stale, 2 * HOUR)
    fresh = _scratch(map_dir, "baseline-build-new")
    result = map_gc_auto.maybe_gc(str(root))
    assert result["removed"] >= 1
    assert not stale.exists() and fresh.exists()


def test_a_failing_gc_never_raises_and_is_not_retried_within_the_hour(repo):
    root, _ = repo
    clock = Clock(5.0)

    def boom(path):
        raise RuntimeError("boom")

    assert map_gc_auto.maybe_gc(str(root), clock=clock, gc=boom) is None
    assert map_gc_auto.maybe_gc(str(root), clock=clock, gc=lambda p: "ran") is None


def test_not_a_repository_or_no_store_is_skipped(tmp_path, repo):
    assert map_gc_auto.maybe_gc(str(tmp_path / "nowhere"), gc=lambda p: pytest.fail("no repo")) is None
    root, map_dir = repo
    shutil.rmtree(map_dir.parent)
    assert map_gc_auto.maybe_gc(str(root), gc=lambda p: pytest.fail("no store")) is None


def test_doctor_map_store_warns_above_the_limit_with_the_fix(repo):
    root, map_dir = repo
    for name in ("baseline-build-a", "baseline-build-b"):
        _age(_scratch(map_dir, name), 2 * HOUR)
    _scratch(map_dir, "baseline-build-recent")
    doc = dov.collect(only="map-store", repo=root, map_store_limit=1000)
    row = doc["checks"][0]
    assert row["name"] == "map-store" and row["status"] == "warn"
    assert row["fix"] == "simplicio-loop map gc"
    assert row["detail"]["baseline_build_older_than_1h"] == 2
    assert row["detail"]["freeable_bytes"] >= 2 * 4096
    assert row["detail"]["size_bytes"] > 1000


def test_doctor_map_store_is_ok_below_the_limit_and_without_a_store(repo, tmp_path):
    root, map_dir = repo
    _age(_scratch(map_dir, "baseline-build-a"), 2 * HOUR)
    row = dov.collect(only="map-store", repo=root)["checks"][0]
    assert row["status"] == "ok" and row["fix"] is None
    assert dov.collect(only="map-store", repo=tmp_path / "nowhere")["checks"][0]["status"] == "ok"


# --- safety: the automatic gc deletes data under <git-common-dir>/simplicio (#1671) -----------------------------------------


def test_a_baseline_build_younger_than_the_age_limit_is_never_deleted(repo):
    root, map_dir = repo
    young = _scratch(map_dir, "baseline-build-59min")
    _age(young, HOUR - 60)
    old = _scratch(map_dir, "baseline-build-61min")
    _age(old, HOUR + 60)
    map_gc_auto.maybe_gc(str(root))
    assert young.exists() and (young / "tree" / "mod.py").exists()
    assert not old.exists()


def test_a_locked_build_is_never_deleted_even_when_old(repo):
    from simplicio_mapper.mapper.file_lock import acquire_lock_at, release_lock_at

    root, map_dir = repo
    locked = _scratch(map_dir, "baseline-build-locked")
    handle = acquire_lock_at(str(locked / "build.lock"), operation="test")  # this process is alive
    assert handle is not None
    _age(locked, 3 * HOUR)
    unlocked = _scratch(map_dir, "baseline-build-unlocked")
    _age(unlocked, 3 * HOUR)
    try:
        map_gc_auto.maybe_gc(str(root))
    finally:
        release_lock_at(handle)
    assert locked.exists() and (locked / "tree" / "mod.py").exists()
    assert not unlocked.exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="/proc")
def test_a_build_with_a_process_working_inside_is_never_deleted(repo):
    root, map_dir = repo
    busy = _scratch(map_dir, "baseline-build-busy")
    _age(busy, 3 * HOUR)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], cwd=str(busy / "tree"))
    try:
        time.sleep(0.3)
        map_gc_auto.maybe_gc(str(root))
        assert busy.exists()
    finally:
        proc.kill()
        proc.wait()


def test_a_symlink_never_takes_the_gc_out_of_the_store(repo, tmp_path):
    root, map_dir = repo
    outside = tmp_path / "outside"
    (outside / "precious").mkdir(parents=True)
    (outside / "precious" / "keep.txt").write_text("data", encoding="utf-8")
    _age(outside, 3 * HOUR)
    link = map_dir / "baseline-build-link"  # a build that is a link to a folder outside the store
    link.symlink_to(outside / "precious", target_is_directory=True)
    build = _scratch(map_dir, "baseline-build-old")  # an old build holding links outside
    (build / "tree" / "escape").symlink_to(outside / "precious", target_is_directory=True)
    (build / "tree" / "escape-file").symlink_to(outside / "precious" / "keep.txt")
    _age(build, 3 * HOUR)
    baseline = map_dir / ("baseline-" + "a" * 40 + ".json")  # a baseline that is a link to a file outside
    baseline.symlink_to(outside / "precious" / "keep.txt")
    map_gc_auto.maybe_gc(str(root))
    assert not build.exists()
    assert (outside / "precious" / "keep.txt").read_text(encoding="utf-8") == "data"


def test_a_store_that_is_itself_a_symlink_is_left_alone(repo, tmp_path):
    root, map_dir = repo
    elsewhere = tmp_path / "elsewhere"
    shutil.move(str(map_dir.parent), str(elsewhere))
    (root / ".git" / "simplicio").symlink_to(elsewhere, target_is_directory=True)
    old = elsewhere / "map" / "baseline-build-old"
    (old / "tree").mkdir(parents=True)
    (old / "tree" / "mod.py").write_text("x", encoding="utf-8")
    _age(old, 3 * HOUR)
    assert map_gc_auto.maybe_gc(str(root), gc=lambda p: pytest.fail("the store is a link")) is None
    assert old.exists()


def test_a_map_folder_that_is_a_symlink_is_left_alone(repo, tmp_path):
    root, map_dir = repo
    elsewhere = tmp_path / "elsewhere-map"
    old = elsewhere / "baseline-build-old"
    (old / "tree").mkdir(parents=True)
    (old / "tree" / "mod.py").write_text("x", encoding="utf-8")
    _age(old, 3 * HOUR)
    map_dir.rmdir()
    map_dir.symlink_to(elsewhere, target_is_directory=True)
    map_gc_auto.maybe_gc(str(root))
    assert old.exists()


def test_two_collections_never_run_at_the_same_time_for_one_repo(repo):
    root, _ = repo
    clock = Clock(1_000_000.0)
    inner = []

    def gc(path):
        clock.now += 2 * HOUR  # the hour is already over for the second caller
        inner.append(map_gc_auto.maybe_gc(str(root), clock=clock, gc=lambda p: inner.append("second ran") or "ran"))
        return "first"

    assert map_gc_auto.maybe_gc(str(root), clock=clock, gc=gc) == "first"
    assert inner == [None]
    assert map_gc_auto.maybe_gc(str(root), clock=clock, gc=lambda p: "again") == "again"  # the lock was released


def test_threads_racing_for_one_repo_run_the_gc_once(repo):
    import threading

    root, _ = repo
    calls = []
    gate = threading.Barrier(6)

    def gc(path):
        calls.append(path)
        time.sleep(0.3)
        return "ran"

    def worker():
        gate.wait()
        map_gc_auto.maybe_gc(str(root), gc=gc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(calls) == 1


def test_the_lock_of_a_dead_process_does_not_block_the_gc_forever(repo):
    import json

    root, map_dir = repo
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    lock = map_dir.parent / map_gc_auto.LOCK_NAME
    lock.write_text(json.dumps({"pid": dead.pid, "token": "t", "owner_token": "t", "acquired_at": time.time()}), encoding="utf-8")
    assert map_gc_auto.maybe_gc(str(root), gc=lambda p: "ran") == "ran"
    assert not lock.exists()


@pytest.mark.parametrize("what", ["gc", "git", "clock", "stamp"])
def test_nothing_ever_raises_into_the_tick(repo, monkeypatch, what):
    root, map_dir = repo
    kwargs = {}
    if what == "gc":
        def gc(path):
            raise RuntimeError("boom")

        kwargs["gc"] = gc
    elif what == "git":
        def boom(path):
            raise OSError("no git")

        monkeypatch.setattr(map_gc_auto, "git_common_dir", boom)
    elif what == "clock":
        def clock():
            raise ValueError("no clock")

        kwargs["clock"] = clock
    else:
        (map_dir.parent / map_gc_auto.STAMP_NAME).mkdir()  # the stamp cannot be written
    assert map_gc_auto.maybe_gc(str(root), **kwargs) is None
    assert not (map_dir.parent / map_gc_auto.LOCK_NAME).exists()  # and the lock never stays behind


def test_the_tick_helper_survives_a_broken_repository(tmp_path, monkeypatch):
    from simplicio_loop.watcher247 import config, tick

    (tmp_path / "base" / ".git").mkdir(parents=True)  # looks like a clone but is not a repository
    monkeypatch.setattr(config, "WORK", tmp_path)
    tick._map_gc_bases()
    monkeypatch.setattr(config, "WORK", tmp_path / "missing")
    tick._map_gc_bases()
