"""trajectory (done): record the run outcome by aggregating trajectory lessons.

Records issue number, status, role, model, attempts, duration to the retrospective ledger.
Runs at the done stage when a run completes, calling the existing retrospective function.
"""
from __future__ import annotations

from pathlib import Path

from ... import retrospective
from .registry import PointContext, PointResult, register

NAME = "trajectory"


async def record_trajectory(ctx: PointContext) -> PointResult:
    """Aggregate trajectory lessons from the run."""
    if ctx.state_dir is None or ctx.run_dir is None:
        return PointResult(NAME, "skipped", {}, "no_state_dir")

    run_id = Path(ctx.run_dir).name if ctx.run_dir else None
    try:
        receipt = retrospective.retrospective(ctx.state_dir, run_id=run_id)
        evidence = {
            "run_id": receipt.get("run_id"),
            "records_seen": receipt.get("records_seen"),
            "candidates": receipt.get("candidates"),
            "new_lessons": receipt.get("new"),
            "merged_lessons": receipt.get("merged"),
            "lessons_path": receipt.get("lessons_path"),
        }
        return PointResult(NAME, "ok", evidence)
    except Exception as exc:
        return PointResult(NAME, "error", {"error": str(exc)[:300]}, "trajectory_exception")


register(NAME, "done", record_trajectory)
