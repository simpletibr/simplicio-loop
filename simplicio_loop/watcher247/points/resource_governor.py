"""resource_governor (intake): probe local capacity; defer when disk/memory low.

The decision is local_capacity.probe_local_capacity's own verdict: `safe_workers < 1` defers, with
`null_reasons["workers"]` as the reason_code. The point is blocking, so a deferred stops the intake stage
(PointDeferred) and the tick gives the attempt back.
"""
from ... import local_capacity, squad_capacity

from .registry import PointContext, PointResult, register

NAME = "resource_governor"


async def govern(ctx: PointContext) -> PointResult:
    """Probe the disk the work is written to; defer when the probe finds no safe worker."""
    sample = squad_capacity.shared_sample(ctx.capacity) or local_capacity.probe_local_capacity(  # the tick's sample while fresh
        ctx.state_dir,
        requested_workers=1,
        reserve_workers=0,  # one attempt at a time: only disk/memory pressure or a missing signal says no
    )
    evidence = {
        "cpu_count": sample.cpu_count,
        "disk_free_bytes": sample.disk_free_bytes,
        "memory_available_bytes": sample.memory_available_bytes,
        "measured": list(sample.measured),
        "unavailable": list(sample.unavailable),
        "safe_workers": sample.safe_workers,
    }
    if sample.safe_workers < 1:
        return PointResult(NAME, "deferred", evidence, sample.null_reasons.get("workers", "no_safe_workers"))
    return PointResult(NAME, "ok", evidence)


register(NAME, "intake", govern, applies=lambda ctx: ctx.state_dir is not None, blocking=True)  # no state dir, nothing to measure