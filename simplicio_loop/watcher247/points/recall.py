"""recall (plan): the top prior precedents of the issue, ranked by the mapper (no new ranking here).

The ranking is the mapper's `prototype_context._precedent_candidates`: the native `simplicio precedent search`
first, the local keyword overlap over `.simplicio-loop/precedent-index.json` when the runtime does not answer.
The matches go to the evidence of the result (events.jsonl and the execution report), where the planner prompt
reads them; none found is still ok, and says so as UNVERIFIED.
"""
import asyncio
import json

from .registry import PointContext, PointResult, register

NAME = "recall"
LIMIT = 3
QUERY_CAP = 1000
INDEX = (".simplicio-loop", "precedent-index.json")


def applies(ctx: PointContext) -> bool:
    return ctx.clone is not None and ctx.issue is not None


def _items(ctx: PointContext) -> list[dict]:
    try:
        items = json.loads(ctx.clone.joinpath(*INDEX).read_text(encoding="utf-8")).get("items")
    except (OSError, ValueError, AttributeError):
        return []
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _search(ctx: PointContext) -> tuple[list[dict], dict]:
    from simplicio_mapper import prototype_context  # lazy: the mapper is a heavy import, and optional
    query = f"{ctx.issue.get('title') or ''}\n{ctx.issue.get('body') or ''}".strip()[:QUERY_CAP]
    return prototype_context._precedent_candidates(str(ctx.clone), _items(ctx), query, LIMIT)


async def search(ctx: PointContext) -> tuple[list[dict], dict]:
    """(candidates, delegation) for the issue; shared with reuse_precedent."""
    return await asyncio.to_thread(_search, ctx)


async def recall(ctx: PointContext) -> PointResult:
    try:
        candidates, delegation = await search(ctx)
    except ImportError:
        return PointResult(NAME, "skipped", {}, "mapper_unavailable")
    matches = [{key: candidate.get(key) for key in ("precedent_id", "path", "summary", "confidence", "provenance")}
               for candidate in candidates[:LIMIT]]
    evidence = {"matches": matches, "delegation": delegation}
    if not matches:
        evidence["label"] = "UNVERIFIED|no_precedent_found"
    return PointResult(NAME, "ok", evidence)


register(NAME, "plan", recall, applies=applies)
