"""resource_governor (intake): probe local capacity; defer when disk/memory low.

Reuses local_capacity.probe_local_capacity to measure CPU, RAM, disk.
Returns deferred (transient condition) when disk or memory fall below minimum.
"""
import os

from ... import local_capacity

from .registry import PointContext, PointResult, register

NAME = "resource_governor"





async def govern(ctx: PointContext) -> PointResult:
    """Probe local capacity; defer if disk or memory is low."""
    evidence = {}

    min_free_gb = int(os.environ.get("SIMPLICIO_247_MIN_FREE_GB", 5))
    min_free_bytes = min_free_gb * (1 << 30)

    sample = local_capacity.probe_local_capacity(
        ".",
        requested_workers=1,
        disk_floor_bytes=min_free_bytes,
        memory_floor_bytes=local_capacity.DEFAULT_MEMORY_FLOOR_BYTES,
    )

    evidence["cpu_count"] = sample.cpu_count
    evidence["disk_free_gb"] = round((sample.disk_free_bytes or 0) / (1 << 30), 2) if sample.disk_free_bytes is not None else None
    evidence["memory_available_bytes"] = sample.memory_available_bytes
    evidence["measured"] = list(sample.measured)
    evidence["unavailable"] = list(sample.unavailable)

    if sample.disk_free_bytes is not None and sample.disk_free_bytes < min_free_bytes:
        return PointResult(NAME, "deferred", evidence, "low_disk")

    if sample.memory_available_bytes is not None and sample.memory_available_bytes < local_capacity.DEFAULT_MEMORY_FLOOR_BYTES:
        return PointResult(NAME, "deferred", evidence, "low_memory")

    return PointResult(NAME, "ok", evidence)


register(NAME, "intake", govern)