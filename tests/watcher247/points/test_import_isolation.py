"""A point module that fails at import must not take the watcher down (#1509)."""
import asyncio
import sys

import pytest

from simplicio_loop.watcher247 import points

GOOD = '''
from simplicio_loop.watcher247.points.registry import PointResult, register

async def fn(ctx):
    return PointResult("good", "ok")

register("good", "plan", fn)
'''


@pytest.fixture
def broken_package(tmp_path, monkeypatch, empty_registry):
    (tmp_path / "boom.py").write_text("raise RuntimeError('boom at import')\n")
    (tmp_path / "syntax.py").write_text("def (:\n")
    (tmp_path / "good.py").write_text(GOOD)
    monkeypatch.setattr(points, "__path__", [str(tmp_path)])
    monkeypatch.setattr(points, "_IMPORT_FAILURES", [])
    yield
    for name in ("boom", "syntax", "good"):
        sys.modules.pop(f"{points.__name__}.{name}", None)


def test_failing_submodules_do_not_raise(broken_package):
    points._load_submodules()
    assert [m for m, _ in points._IMPORT_FAILURES] == ["boom", "syntax"]


@pytest.mark.parametrize("stage", points.STAGES)
def test_every_stage_reports_the_import_failures(broken_package, make_ctx, stage):
    points._load_submodules()
    results = asyncio.run(points.run(stage, make_ctx()))
    failed = [r for r in results if r.reason_code == "point_import_failed"]
    assert {r.evidence["module"] for r in failed} == {"boom", "syntax"}
    assert all(r.status == "error" for r in failed)
    assert any("boom at import" in r.evidence["error"] for r in failed)


def test_good_points_keep_running(broken_package, make_ctx):
    points._load_submodules()
    results = asyncio.run(points.run("plan", make_ctx()))
    assert [r.status for r in results if r.name == "good"] == ["ok"]


def test_the_real_package_has_no_import_failures(monkeypatch):
    monkeypatch.setattr(points, "_IMPORT_FAILURES", [])  # a fresh list: no other test's failures leak in
    points._load_submodules()  # the real submodules are already imported: nothing registers twice
    assert points._IMPORT_FAILURES == []
