"""trajectory (done): write the run outcome to orchestrator/trajectory/<run_id>.jsonl.

That directory is what `retrospective.retrospective` reads; `learn` is the only point that calls it. The record
carries what the tick has at `done`: the turbo result (turbo_status, verify, executor, steps), the issue, the
PR url, and, for a solved run, a deterministic `lesson` built from the executor, models and verify label.
The tick keeps no clock for the run, so no duration is recorded.
"""
from __future__ import annotations

import json
from pathlib import Path

from .registry import PointContext, PointResult, register

NAME = "trajectory"
SOLVED = "ok"


def is_solved(ctx: PointContext) -> bool:
    """The tick's turbo dict (host_mode.run_exec / tick._run_turbo) names the outcome `turbo_status`."""
    return (ctx.turbo_json or {}).get("turbo_status") == SOLVED


def _lesson(ctx: PointContext) -> str:
    turbo = ctx.turbo_json or {}
    steps = turbo.get("steps") or []
    models = sorted({f"{s.get('family')}/{s.get('model')}" for s in steps if s.get("model")})
    via = f"{turbo.get('executor') or 'turbo'} executor" + (f" ({', '.join(models)})" if models else "")
    return f"{ctx.repo}: solved via {via}; verified by {ctx.verify or turbo.get('verify') or 'unverified'}"


async def record_trajectory(ctx: PointContext) -> PointResult:
    """Write the run's record, replacing an earlier record of the same run id (a re-run must not count twice)."""
    if ctx.state_dir is None or ctx.run_dir is None:
        return PointResult(NAME, "skipped", {}, "no_state_dir")
    run_id = Path(ctx.run_dir).name
    turbo = ctx.turbo_json or {}
    steps = turbo.get("steps") or []
    record = {
        "run_id": run_id,
        "issue": (ctx.issue or {}).get("number"),
        "status": turbo.get("turbo_status", "unknown"),
        "verify": ctx.verify or turbo.get("verify"),
        "executor": turbo.get("executor"),
        "steps": steps,
        "attempts": len(steps) or 1,
        "role": ctx.role,
        "family": ctx.family,
        "pr_url": ctx.pr_url,
    }
    if is_solved(ctx):
        record["lesson"] = _lesson(ctx)
    path = Path(ctx.state_dir) / ".simplicio-loop" / "orchestrator" / "trajectory" / f"{run_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    return PointResult(NAME, "ok", {"run_id": run_id, "trajectory_file": str(path.relative_to(ctx.state_dir)),
                                      "status": record["status"], "lesson": record.get("lesson")})


register(NAME, "done", record_trajectory)
