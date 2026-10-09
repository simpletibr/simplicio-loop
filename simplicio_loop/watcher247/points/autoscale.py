"""autoscale (intake): record safe concurrency estimate.

Uses economy_profile.recommend_operator_workers to estimate workers.
Records the recommendation as evidence (evidence-only, no wiring to config yet).
"""
from ... import economy_profile

from .registry import PointContext, PointResult, register

NAME = "autoscale"





async def scale(ctx: PointContext) -> PointResult:
    """Record recommended concurrency based on CPU count."""
    evidence = {}

    try:
        safe_concurrency = economy_profile.recommend_operator_workers()
        evidence["safe_concurrency"] = safe_concurrency
    except (OSError, TypeError, ValueError) as e:
        evidence["safe_concurrency"] = 1
        evidence["error"] = str(e)

    return PointResult(NAME, "ok", evidence)


register(NAME, "intake", scale)