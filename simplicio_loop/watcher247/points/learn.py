"""learn (done): the ONLY caller of `retrospective.retrospective`, for a SOLVED run.

`retrospective` reads the run's records in orchestrator/trajectory/<run_id>.jsonl (written by `trajectory`) and
writes orchestrator/lessons.jsonl (deduplicated lessons with hit_count) and learn-index.json. It does not write
the precedent index that `recall` reads.
"""
from __future__ import annotations

from pathlib import Path

from ... import retrospective
from . import trajectory  # imported first so trajectory registers (and writes) before learn reads
from .registry import PointContext, PointResult, register

NAME = "learn"


async def learn_from_run(ctx: PointContext) -> PointResult:
    """Aggregate the lessons of the run's trajectory records into lessons.jsonl."""
    if ctx.state_dir is None or ctx.run_dir is None:
        return PointResult(NAME, "skipped", {}, "no_state_dir")
    receipt = retrospective.retrospective(ctx.state_dir, run_id=Path(ctx.run_dir).name)
    return PointResult(NAME, "ok", {
        "run_id": receipt["run_id"],
        "records_seen": receipt["records_seen"],
        "new_lessons": receipt["new"],
        "merged_lessons": receipt["merged"],
        "lessons_path": receipt["lessons_path"],
    })


register(NAME, "done", learn_from_run, applies=trajectory.is_solved)
