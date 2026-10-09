"""`point_contract` for a BLOCKING point: the stage raises PointBlocked, and the blocked result is the last one.

Import it into the test module (`from .blocking import point_contract`) to shadow the conftest fixture, which
expects the stage to return.
"""
import asyncio
import json

import pytest

from simplicio_loop.watcher247 import points


@pytest.fixture
def point_contract():
    def check(name, ctx, expect=None):
        [info] = [i for i in points.registered() if i.name == name]
        assert info.blocking and info.stage in points.STAGES
        assert info.module.startswith("simplicio_loop.watcher247.points."), "a point lives in points/<name>.py"
        try:
            results = asyncio.run(points.run(info.stage, ctx))
        except points.PointBlocked as stopped:
            results = stopped.results
        [result] = [r for r in results if r.name == name]
        assert isinstance(result, points.PointResult) and result.status in points.STATUSES
        assert result.status != "error" or result.reason_code, "an error result names its reason_code"
        json.dumps(result.evidence)
        if expect is not None:
            assert result.status == expect, result
        return result
    return check
