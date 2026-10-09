"""endpoint_compare must not stall the event loop (#1548): a slow git delays only its own point, never the tick."""
import asyncio
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

from simplicio_loop.watcher247 import points, sandbox
from simplicio_loop.watcher247.points import endpoint_compare, registry

SLOW_S = 1.0
MAX_GAP_S = 0.25
BEAT_S = 0.05


@pytest.fixture
def slow_git(tmp_path, monkeypatch):
    """A `git` first on PATH that sleeps SLOW_S before running the real one."""
    real = shutil.which("git")
    fake = tmp_path / "fakebin" / "git"
    fake.parent.mkdir()
    fake.write_text(f"#!/bin/sh\nsleep {SLOW_S}\nexec {real} \"$@\"\n", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{fake.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv(sandbox.OPT_OUT, "1")
    monkeypatch.setattr(sandbox, "engine", lambda *a, **k: None)
    return fake


@pytest.fixture
def clone(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "util.txt").write_text("one\n", encoding="utf-8")
    real = shutil.which("git")
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"], ["add", "."],
                 ["commit", "-q", "-m", "base"]):
        subprocess.run([real, *args], cwd=root, check=True, capture_output=True)
    (root / "util.txt").write_text("two\n", encoding="utf-8")  # changed, but not a route: the point is skipped
    return root


async def _max_heartbeat_gap(work) -> tuple[float, object]:
    gaps: list[float] = []
    stop = asyncio.Event()

    async def heartbeat() -> None:
        last = time.monotonic()
        while not stop.is_set():
            await asyncio.sleep(BEAT_S)
            now = time.monotonic()
            gaps.append(now - last)
            last = now
        gaps.append(time.monotonic() - last)

    beat = asyncio.create_task(heartbeat())
    await asyncio.sleep(BEAT_S * 2)  # the heartbeat is running before the work starts
    try:
        outcome = await work()
    finally:
        stop.set()
        await beat
    return max(gaps), outcome


def test_the_applicability_decision_does_not_block_the_event_loop(slow_git, clone, monkeypatch):
    monkeypatch.setattr(registry, "_POINTS", [p for p in registry._POINTS if p.name == "endpoint_compare"])
    ctx = points.PointContext(repo="demo", clone=clone)
    started = time.monotonic()
    gap, results = asyncio.run(_max_heartbeat_gap(lambda: points.run("verify", ctx)))
    assert time.monotonic() - started >= SLOW_S  # the slow git really ran through this path
    assert [(r.name, r.status, r.reason_code) for r in results] == [("endpoint_compare", "skipped", "not_applicable")]
    assert gap < MAX_GAP_S, f"the loop stalled for {gap:.2f}s"


def test_a_sync_applies_is_still_supported(empty_registry, make_ctx):
    async def fn(ctx):
        return points.PointResult("p", "ok")
    points.register("p", "verify", fn, applies=lambda ctx: True)
    assert [r.status for r in asyncio.run(points.run("verify", make_ctx()))] == ["ok"]


def test_an_async_applies_is_awaited_and_its_exception_is_an_error_result(empty_registry, make_ctx):
    async def fn(ctx):
        return points.PointResult("p", "ok")

    async def no(ctx):
        return False

    async def boom(ctx):
        raise KeyError("x")
    points.register("no", "verify", fn, applies=no)
    points.register("boom", "verify", fn, applies=boom)
    skipped, errored = asyncio.run(points.run("verify", make_ctx()))
    assert (skipped.status, skipped.reason_code) == ("skipped", "not_applicable")
    assert (errored.status, errored.reason_code) == ("error", "applies_exception")


def test_concurrent_decisions_load_the_flow_audit_once(clone, monkeypatch):
    monkeypatch.setattr(endpoint_compare, "_module", [])
    monkeypatch.delitem(__import__("sys").modules, "flow_audit", raising=False)
    (clone / "app.py").write_text('@app.get("/api/x")\ndef x():\n    return 1\n', encoding="utf-8")
    ctx = points.PointContext(repo="demo", clone=clone)

    async def many():
        return await asyncio.gather(*(endpoint_compare._applies(ctx) for _ in range(8)))

    assert asyncio.run(many()) == [True] * 8
    assert len(endpoint_compare._module) == 1
