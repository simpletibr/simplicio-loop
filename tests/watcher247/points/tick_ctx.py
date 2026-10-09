"""The PointContext the REAL tick hands to the `done` stage, for the trajectory/learn tests (#1509)."""
from simplicio_loop.watcher247 import points

from ..fakes import FakeRun, baseline, issue, run_tick


def capture_done_ctx(env, monkeypatch, number=7):
    """Run a tick (issue `number` of simplicio-a, solved, PR opened) and return its `done` ctx.

    The tick builds the ctx inline, so points.run is spied during the tick and restored afterwards.
    """
    env(FakeRun({"simplicio-a": [issue(number, "Add x")]}))
    baseline()
    seen = {}

    async def spy(stage, ctx):
        seen[stage] = ctx
        return []

    with monkeypatch.context() as patch:
        patch.setattr(points, "run", spy)
        run_tick()
    return seen["done"]
