"""Automatic `map gc` once an hour and the `map-store` line of `doctor` (#1671)."""
from __future__ import annotations

import os
import shutil
import subprocess
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
        os.utime(item, (stamp, stamp))


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
