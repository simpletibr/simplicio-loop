"""model_preflight (intake): the usable executor families, read from the result of host_mode.choose. It never blocks.

The tick preflight (choose, once per tick) already probes every family and blocks when none is usable; this only
records which are, so the per-issue point never spawns a status subprocess.
"""
from .. import host_mode
from .registry import PointContext, PointResult, register

NAME = "model_preflight"


async def preflight(ctx: PointContext) -> PointResult:
    results = host_mode.last_auth()  # the probe of this tick's choose(); nothing is probed here
    if not results:
        return PointResult(NAME, "skipped", {}, "no_auth_result")
    usable = [r.family for r in results if r.status == "ok"]
    unusable = {r.family: r.status for r in results if r.status != "ok"}
    evidence = {"usable": usable, "unusable": unusable, "selected": ctx.family}
    return PointResult(NAME, "ok" if usable else "error", evidence, None if usable else "no_usable_family")


register(NAME, "intake", preflight)
