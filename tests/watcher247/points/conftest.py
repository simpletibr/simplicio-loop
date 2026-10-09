"""Fixtures for the stage points (#1509): a PointContext factory, an isolated registry and the contract check.

A new point's test reuses `point_contract`:

    def test_contract(point_contract, make_ctx, tmp_path):
        result = point_contract("my_point", make_ctx(clone=tmp_path), expect="ok")
        assert result.evidence["key"] == ...
"""
import asyncio
import json

import pytest

from simplicio_loop.watcher247 import points
from simplicio_loop.watcher247.points import registry


@pytest.fixture
def make_ctx():
    """PointContext factory: every field is optional, `repo` defaults to a demo name."""
    def build(**fields):
        fields.setdefault("repo", "simplicio-demo")
        return points.PointContext(**fields)
    return build


@pytest.fixture
def empty_registry(monkeypatch):
    """An empty registry for one test; the real one is restored afterwards."""
    monkeypatch.setattr(registry, "_POINTS", [])
    return registry


@pytest.fixture
def point_contract(monkeypatch):
    """check(name, ctx, expect=...) runs the registered point through the registry and asserts the contract.

    Only that point runs: a blocking point earlier in the same stage (judge, delivery_gate) would stop it.

    The point is registered once, at a valid stage, as an async function in points/<name>.py; it returns a
    PointResult named after itself with a known status and JSON-serializable evidence; and it never raises.
    """
    def check(name, ctx, expect=None):
        monkeypatch.setattr(registry, "_POINTS", [p for p in registry._POINTS if p.name == name])  # this point alone
        matches = [info for info in points.registered() if info.name == name]
        assert len(matches) == 1, f"point {name!r} must be registered exactly once"
        info = matches[0]
        assert info.stage in points.STAGES
        assert info.module.startswith("simplicio_loop.watcher247.points."), "a point lives in points/<name>.py"
        results = [r for r in asyncio.run(points.run(info.stage, ctx)) if r.name == name]
        assert len(results) == 1
        result = results[0]
        assert isinstance(result, points.PointResult)
        assert result.status in points.STATUSES
        assert result.status != "error" or result.reason_code, "an error result names its reason_code"
        json.dumps(result.evidence)
        if expect is not None:
            assert result.status == expect, result
        return result
    return check
