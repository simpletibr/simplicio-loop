"""learn (done): the ONLY caller of retrospective to aggregate and deduplicate lessons.

Only runs when the turbo_json status is ok (solved). Updates the precedents ledger by calling
the existing retrospective function to deduplicate and merge lessons.
"""
from __future__ import annotations

from pathlib import Path

from ... import retrospective
from .registry import PointContext, PointResult, register

NAME = "learn"


async def learn_from_run(ctx: PointContext) -> PointResult:
    """Update precedents from a solved run by aggregating lessons."""
    if ctx.state_dir is None or ctx.run_dir is None:
        return PointResult(NAME, "skipped", {}, "no_state_dir")

    run_id = Path(ctx.run_dir).name if ctx.run_dir else None
    try:
        receipt = retrospective.retrospective(ctx.state_dir, run_id=run_id)
        evidence = {
            "run_id": receipt.get("run_id"),
            "new_lessons": receipt.get("new"),
            "merged_lessons": receipt.get("merged"),
            "index_path": receipt.get("index_path"),
            "receipt_path": receipt.get("receipt_path"),
        }
        return PointResult(NAME, "ok", evidence)
    except Exception as exc:
        return PointResult(NAME, "error", {"error": str(exc)[:300]}, "learn_exception")


def _is_solved(ctx: PointContext) -> bool:
    """Only apply when the run is solved (turbo_json status is ok)."""
    if ctx.turbo_json is None:
        return False
    return ctx.turbo_json.get("status") == "ok"


register(NAME, "done", learn_from_run, applies=_is_solved)
