"""resource_governor (intake): probe CPU load and disk; block when low.

Uses stdlib to measure system capacity.
Returns blocked with reason_code when thresholds are crossed:
  - high_load: CPU load exceeds SIMPLICIO_247_MAX_LOAD (default: number of CPUs)
  - low_disk: disk free < SIMPLICIO_247_MIN_FREE_GB (default: 5 GB)
"""
import os
import shutil

from .registry import PointContext, PointResult, register

NAME = "resource_governor"


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


async def govern(ctx: PointContext) -> PointResult:
    """Probe local capacity; block if CPU load is high or disk is low."""
    evidence = {}

    try:
        load_avg = os.getloadavg()[0]
        cpu_count = os.cpu_count() or 1
        max_load = int(os.environ.get("SIMPLICIO_247_MAX_LOAD", cpu_count))
        evidence["cpu_load"] = round(load_avg, 2)
        evidence["cpu_count"] = cpu_count

        if load_avg > max_load:
            return PointResult(NAME, "blocked", evidence, "high_load")
    except (OSError, AttributeError, TypeError, ValueError):
        evidence["cpu_load"] = None

    try:
        min_free_gb = int(os.environ.get("SIMPLICIO_247_MIN_FREE_GB", 5))
        min_free_bytes = min_free_gb * (1 << 30)
        usage = shutil.disk_usage(".")
        disk_free_gb = usage.free / (1 << 30)
        evidence["disk_free_gb"] = round(disk_free_gb, 2)

        if usage.free < min_free_bytes:
            return PointResult(NAME, "blocked", evidence, "low_disk")
    except (OSError, ValueError, TypeError):
        evidence["disk_free_gb"] = None

    try:
        mem_avail = _get_meminfo()
        if mem_avail is not None:
            evidence["memory_available_bytes"] = mem_avail
    except (OSError, ValueError):
        pass

    return PointResult(NAME, "ok", evidence)


register(NAME, "intake", govern)