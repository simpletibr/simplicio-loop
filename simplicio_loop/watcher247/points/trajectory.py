"""trajectory (done): record the run outcome to the trajectory ledger.

Writes the run outcome (issue, status, role, model, attempts, duration) as a JSON record
to orchestrator/trajectory/{run_id}.jsonl for later aggregation by learn.
"""
from __future__ import annotations

import json
from pathlib import Path

from .registry import PointContext, PointResult, register

NAME = "trajectory"


async def record_trajectory(ctx: PointContext) -> PointResult:
    """Write run outcome record to the trajectory ledger."""
    if ctx.state_dir is None or ctx.run_dir is None:
        return PointResult(NAME, "skipped", {}, "no_state_dir")

    run_id = Path(ctx.run_dir).name if ctx.run_dir else None
    if not run_id:
        return PointResult(NAME, "skipped", {}, "no_run_id")

    try:
        traj_dir = Path(ctx.state_dir) / ".simplicio-loop" / "orchestrator" / "trajectory"
        traj_dir.mkdir(parents=True, exist_ok=True)
        traj_file = traj_dir / f"{run_id}.jsonl"

        record = {
            "run_id": run_id,
            "issue": (ctx.issue or {}).get("number"),
            "status": "unknown",
            "role": ctx.role,
        }
        if ctx.turbo_json:
            record["status"] = ctx.turbo_json.get("status", "unknown")

        with traj_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        evidence = {"run_id": run_id, "trajectory_file": str(traj_file.relative_to(ctx.state_dir))}
        return PointResult(NAME, "ok", evidence)
    except Exception as exc:
        return PointResult(NAME, "error", {"error": str(exc)[:300]}, "trajectory_exception")


register(NAME, "done", record_trajectory)
