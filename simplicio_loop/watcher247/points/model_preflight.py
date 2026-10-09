"""model_preflight (intake): the usable executor families, from exec_auth.check_all. It never blocks.

The tick preflight (host_mode.choose) already blocks when no family is usable; this only records which are.
"""
import os

from ... import exec_auth, executor_select
from .registry import PointContext, PointResult, register

NAME = "model_preflight"


async def preflight(ctx: PointContext) -> PointResult:
    try:
        families = executor_select.resolve(os.environ)["families"]
    except executor_select.ExecutorSelectError as exc:
        return PointResult(NAME, "error", {"error": str(exc)[:300]}, "executor_invalid")
    if not families:
        return PointResult(NAME, "skipped", {}, "no_exec_families")
    results = await exec_auth.check_all(families)
    usable = [r.family for r in results if r.status == "ok"]
    unusable = {r.family: r.status for r in results if r.status != "ok"}
    evidence = {"usable": usable, "unusable": unusable}
    return PointResult(NAME, "ok" if usable else "error", evidence, None if usable else "no_usable_family")


register(NAME, "intake", preflight)
