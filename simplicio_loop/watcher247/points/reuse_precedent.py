"""reuse_precedent (plan): a prior SOLVED precedent the planner may reuse instead of regenerating.

Only a candidate of the native runtime search with `reuse_level == "high"` counts (the runtime checks it with a
git-apply dry-run); the local keyword overlap ranks, but it never proves a reuse is safe. Same ranking as
`recall` (`recall.search`, the mapper's precedent delegation). None reusable is ok, labelled UNVERIFIED.
"""
from .recall import applies, search
from .registry import PointContext, PointResult, register

NAME = "reuse_precedent"
REUSABLE = "high"


async def reuse(ctx: PointContext) -> PointResult:
    try:
        candidates, delegation = await search(ctx)
    except ImportError:
        return PointResult(NAME, "skipped", {}, "mapper_unavailable")
    for candidate in candidates:
        if candidate.get("reuse_level") == REUSABLE:
            return PointResult(NAME, "ok", {"reuse": {key: candidate.get(key) for key in (
                "precedent_id", "path", "reuse_level", "suggested_next_action")}, "delegation": delegation})
    return PointResult(NAME, "ok", {"reuse": None, "delegation": delegation, "label": "UNVERIFIED|no_reusable_precedent"})


register(NAME, "plan", reuse, applies=applies)
