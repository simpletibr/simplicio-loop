"""autoscale (intake): record economy_profile's operator-worker recommendation.

Evidence only: the recommendation does not use the capacity probe, and nothing reads it, so it never changes the
tick's batch size, which `squad_capacity` sizes from the measured machine (the registry table keeps this point
`parcial`, not `ligado`).
"""
from ... import economy_profile

from .registry import PointContext, PointResult, register

NAME = "autoscale"


async def scale(ctx: PointContext) -> PointResult:
    """Record economy_profile.recommend_operator_workers() as evidence; a failure is an error result."""
    return PointResult(NAME, "ok", {"recommended_operator_workers": economy_profile.recommend_operator_workers()})


register(NAME, "intake", scale)