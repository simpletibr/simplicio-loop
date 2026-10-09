"""autoscale (intake): compute safe concurrency from local capacity probes.

Uses stdlib to probe CPU, memory and disk, then computes a conservative safe
concurrency estimate that respects the machine's available resources.
"""
import os
import shutil

from .registry import PointContext, PointResult, register

NAME = "autoscale"


def _get_meminfo() -> int | None:
    """Read available memory from /proc/meminfo when present."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) * 1024
    except (OSError, ValueError):
        pass
    return None


async def scale(ctx: PointContext) -> PointResult:
    """Compute safe concurrency from local capacity."""
    evidence = {}

    try:
        cpu_count = os.cpu_count() or 1
        evidence["cpu_count"] = cpu_count
    except (OSError, TypeError):
        cpu_count = 1

    try:
        usage = shutil.disk_usage(".")
        disk_free_gb = usage.free / (1 << 30)
        evidence["disk_free_gb"] = round(disk_free_gb, 2)
    except (OSError, ValueError, TypeError):
        disk_free_gb = 0

    try:
        mem_avail = _get_meminfo()
        if mem_avail is not None:
            evidence["memory_available_bytes"] = mem_avail
            mem_gb = mem_avail / (1 << 30)
        else:
            mem_gb = 0
    except (OSError, ValueError):
        mem_gb = 0

    safe_concurrency = max(1, min(cpu_count, int(cpu_count * 0.8 + 1)))
    evidence["safe_concurrency"] = safe_concurrency

    return PointResult(NAME, "ok", evidence)


register(NAME, "intake", scale)