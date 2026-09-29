"""Measured local capacity and conservative adaptive worker admission."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

SCHEMA = "simplicio.local-capacity/v1"
MONITOR_SCHEMA = "simplicio.physical-admission-monitor/v1"
DEFAULT_DISK_FLOOR_BYTES = 2 * (1 << 30)
DEFAULT_MEMORY_FLOOR_BYTES = 512 << 20
DEFAULT_SAMPLE_INTERVAL_NS = 5_000_000_000
DEFAULT_TARGET_PRESSURE_PERCENT = 75.0
DEFAULT_NO_NEW_PRESSURE_PERCENT = 80.0
DEFAULT_CHECKPOINT_PRESSURE_PERCENT = 85.0
DEFAULT_TERMINATE_PRESSURE_PERCENT = 88.0
DEFAULT_DISK_SUSPEND_PERCENT = 85.0
DEFAULT_DISK_SUSPEND_FLOOR_BYTES = 10 * (1 << 30)
DEFAULT_RECOVERY_WINDOW_NS = 60_000_000_000


@dataclass(frozen=True)
class CapacitySample:
    """One measured probe; unavailable signals are represented explicitly."""

    requested_workers: int
    safe_workers: int
    cpu_count: int | None
    memory_available_bytes: int | None
    disk_free_bytes: int | None
    measured: tuple[str, ...]
    unavailable: tuple[str, ...]
    null_reasons: dict[str, str]
    observed_at_ns: int
    schema: str = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "requested_workers": self.requested_workers,
            "safe_workers": self.safe_workers,
            "cpu_count": self.cpu_count,
            "memory_available_bytes": self.memory_available_bytes,
            "disk_free_bytes": self.disk_free_bytes,
            "measured": list(self.measured),
            "unavailable": list(self.unavailable),
            "null_reasons": dict(self.null_reasons),
            "observed_at_ns": self.observed_at_ns,
        }


def _cgroup_memory_stats() -> tuple[int, int] | None:
    """Read current and finite limit for the applicable cgroup, when present."""
    candidates = (
        (Path("/sys/fs/cgroup/memory.current"), Path("/sys/fs/cgroup/memory.max")),
        (
            Path("/sys/fs/cgroup/memory/memory.usage_in_bytes"),
            Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
        ),
    )
    for current_path, limit_path in candidates:
        try:
            current_raw = current_path.read_text(encoding="utf-8").strip()
            limit_raw = limit_path.read_text(encoding="utf-8").strip()
            if limit_raw == "max":
                continue
            current = int(current_raw)
            limit = int(limit_raw)
        except (OSError, TypeError, ValueError):
            continue
        # cgroup v1 reports "no limit" as a page-aligned value near 2**63.
        if 0 < limit < 2 ** 60 and current >= 0:
            return current, limit
    return None


def _cgroup_memory_available() -> int | None:
    """Read a bounded cgroup memory budget when available."""
    stats = _cgroup_memory_stats()
    return max(0, stats[1] - stats[0]) if stats is not None else None


def _cgroup_cpu_capacity() -> int | None:
    """Return the finite cgroup CPU quota, preserving host capacity otherwise."""
    candidates = (
        (Path("/sys/fs/cgroup/cpu.max"),),
        (Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"), Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")),
    )
    for paths in candidates:
        try:
            if len(paths) == 1:
                fields = paths[0].read_text(encoding="utf-8").strip().split()
                if len(fields) != 2 or fields[0] == "max":
                    continue
                quota, period = int(fields[0]), int(fields[1])
            else:
                quota = int(paths[0].read_text(encoding="utf-8").strip())
                period = int(paths[1].read_text(encoding="utf-8").strip())
                if quota < 0:
                    continue
            if quota >= 0 and period > 0:
                return max(0, quota // period)
        except (OSError, TypeError, ValueError, IndexError):
            continue
    return None


_PROC_MEMINFO = Path("/proc/meminfo")


def _linux_memory_available() -> int | None:
    """Read MemAvailable (kernel's own estimate) without requiring psutil."""
    try:
        for line in _PROC_MEMINFO.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _macos_memory_available() -> int | None:
    """Read a conservative macOS memory estimate without requiring psutil."""

    if sys.platform != "darwin":
        return None
    sysctl = shutil.which("sysctl") or "/usr/sbin/sysctl"
    vm_stat = shutil.which("vm_stat") or "/usr/bin/vm_stat"
    try:
        total_result = subprocess.run(
            [sysctl, "-n", "hw.memsize"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        stat_result = subprocess.run(
            [vm_stat],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if total_result.returncode != 0 or stat_result.returncode != 0:
        return None
    try:
        total = int((total_result.stdout or "").strip())
        page_match = re.search(r"page size of (\d+) bytes", stat_result.stdout or "")
        page_size = int(page_match.group(1)) if page_match else 0
    except (TypeError, ValueError):
        return None
    if total <= 0 or page_size <= 0:
        return None

    reclaimable_pages = 0
    for line in (stat_result.stdout or "").splitlines():
        match = re.match(r"^Pages (free|inactive|speculative|purgeable):\s+([\d.]+)", line)
        if not match:
            continue
        try:
            reclaimable_pages += int(float(match.group(2).rstrip(".")))
        except ValueError:
            continue
    if reclaimable_pages <= 0:
        return None
    return min(total, reclaimable_pages * page_size)


def _memory_available() -> int | None:
    host_available: int | None = None
    try:
        import psutil

        host_available = int(psutil.virtual_memory().available)
    except (ImportError, OSError, AttributeError, TypeError, ValueError):
        pass
    if host_available is None:
        host_available = _linux_memory_available() or _macos_memory_available()
    cgroup_available = _cgroup_memory_available()
    if host_available is None:
        return cgroup_available
    if cgroup_available is None:
        return host_available
    return min(host_available, cgroup_available)


def probe_local_capacity(
    root: str | os.PathLike[str] = ".",
    *,
    requested_workers: int,
    reserve_workers: int = 1,
    disk_floor_bytes: int = DEFAULT_DISK_FLOOR_BYTES,
    memory_floor_bytes: int = DEFAULT_MEMORY_FLOOR_BYTES,
    now_ns: int | None = None,
) -> CapacitySample:
    """Measure safe physical worker capacity without estimating missing signals."""

    requested = max(1, int(requested_workers))
    unavailable: list[str] = []
    null_reasons: dict[str, str] = {}
    measured: list[str] = []
    try:
        host_cpu_count = int(os.cpu_count() or 0) or None
    except (OSError, TypeError, ValueError):
        host_cpu_count = None
    quota_cpu_count = _cgroup_cpu_capacity() if host_cpu_count is not None else None
    cpu_count = (
        min(host_cpu_count, quota_cpu_count)
        if host_cpu_count is not None and quota_cpu_count is not None
        else host_cpu_count
    )
    if cpu_count is None:
        unavailable.append("cpu_count")
        null_reasons["cpu_count"] = "os_cpu_count_unavailable"
    else:
        measured.append("cpu_count")

    memory = _memory_available()
    if memory is None:
        unavailable.append("memory_available_bytes")
        null_reasons["memory_available_bytes"] = "psutil_unavailable_or_probe_failed"
    else:
        measured.append("memory_available_bytes")

    total_disk = 0
    try:
        usage = shutil.disk_usage(Path(root).resolve())
        disk = int(usage.free)
        total_disk = int(getattr(usage, "total", 0) or 0)
    except (OSError, ValueError, TypeError):
        disk = None
    if disk is None:
        unavailable.append("disk_free_bytes")
        null_reasons["disk_free_bytes"] = "disk_probe_failed"
    else:
        measured.append("disk_free_bytes")

    configured_floor = max(0, int(disk_floor_bytes))
    if total_disk > 0 and configured_floor > int(total_disk * 0.20):
        disk_floor = max(512 << 20, int(total_disk * 0.10))
    else:
        disk_floor = configured_floor
    memory_floor = max(0, int(memory_floor_bytes))
    if unavailable:
        safe = 0
        null_reasons["workers"] = "required_capacity_signal_unavailable"
    elif disk < disk_floor:
        safe = 0
        null_reasons["workers"] = "disk_pressure"
    elif memory < memory_floor:
        safe = 0
        null_reasons["workers"] = "memory_pressure"
    else:
        safe = max(0, min(requested, cpu_count - max(0, int(reserve_workers))))
        if safe < 1:
            null_reasons["workers"] = "worker_capacity_exhausted"

    return CapacitySample(
        requested_workers=requested,
        safe_workers=safe,
        cpu_count=cpu_count,
        memory_available_bytes=memory,
        disk_free_bytes=disk,
        measured=tuple(sorted(measured)),
        unavailable=tuple(sorted(unavailable)),
        null_reasons=null_reasons,
        observed_at_ns=time.time_ns() if now_ns is None else int(now_ns),
    )


def _physical_pressure(root: str | os.PathLike[str]) -> dict[str, Any]:
    """Collect pressure signals without turning a missing percentage into zero."""
    disk_free: int | None = None
    disk_used: float | None = None
    try:
        usage = shutil.disk_usage(Path(root).resolve())
        disk_free = int(usage.free)
        used = int(getattr(usage, "used", 0) or 0)
        # df semantics: blocks reserved for root are neither used nor free to us.
        if used + disk_free > 0:
            disk_used = max(0.0, min(100.0, used / (used + disk_free) * 100.0))
    except (OSError, ValueError, TypeError, AttributeError):
        pass

    memory_used: float | None = None
    memory_stats = _cgroup_memory_stats()
    if memory_stats is not None:
        current, limit = memory_stats
        memory_used = max(0.0, min(100.0, current / limit * 100.0))
    else:
        try:
            import psutil

            memory_used = float(psutil.virtual_memory().percent)
        except (ImportError, OSError, AttributeError, TypeError, ValueError):
            pass
    values = [value for value in (disk_used, memory_used) if value is not None]
    return {
        "available": bool(values or disk_free is not None),
        "pressure_percent": max(values) if values else None,
        "disk_used_percent": disk_used,
        "disk_free_bytes": disk_free,
        "memory_used_percent": memory_used,
        "disk_suspend": bool(
            disk_used is not None
            and disk_used >= DEFAULT_DISK_SUSPEND_PERCENT
            and disk_free is not None
            and disk_free < DEFAULT_DISK_SUSPEND_FLOOR_BYTES
        ),
    }


PHYSICAL_MONITOR_ENV = (
    ("SIMPLICIO_LOOP_TARGET_PRESSURE_PERCENT", "target_pressure_percent", float),
    ("SIMPLICIO_LOOP_NO_NEW_PRESSURE_PERCENT", "no_new_pressure_percent", float),
    ("SIMPLICIO_LOOP_CHECKPOINT_PRESSURE_PERCENT", "checkpoint_pressure_percent", float),
    ("SIMPLICIO_LOOP_TERMINATE_PRESSURE_PERCENT", "terminate_pressure_percent", float),
    ("SIMPLICIO_LOOP_DISK_SUSPEND_PERCENT", "disk_suspend_percent", float),
    ("SIMPLICIO_LOOP_DISK_SUSPEND_FLOOR_BYTES", "disk_suspend_floor_bytes", int),
    ("SIMPLICIO_LOOP_RECOVERY_WINDOW_NS", "recovery_window_ns", int),
)
PHYSICAL_MONITOR_KEYS = frozenset(key for _env, key, _converter in PHYSICAL_MONITOR_ENV)


def physical_monitor_kwargs(overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Resolve safe monitor profile values at the production dispatch boundary."""
    values: dict[str, Any] = {}
    for env_name, key, converter in PHYSICAL_MONITOR_ENV:
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            continue
        try:
            values[key] = converter(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid {env_name} physical admission setting") from exc
    if overrides is not None:
        unknown = set(overrides).difference(PHYSICAL_MONITOR_KEYS)
        if unknown:
            raise ValueError("unsupported physical admission setting: " + ", ".join(sorted(unknown)))
        values.update(dict(overrides))
    return values


class PhysicalAdmissionMonitor:
    """Poll local physical capacity on a monotonic clock and fail closed."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        requested_workers: int,
        *,
        sample_interval_ns: int = DEFAULT_SAMPLE_INTERVAL_NS,
        clock: Callable[[], int] = time.monotonic_ns,
        observation_clock: Callable[[], int] = time.time_ns,
        probe: Callable[..., CapacitySample] | None = None,
        probe_kwargs: dict[str, Any] | None = None,
        pressure_probe: Callable[[str], Mapping[str, Any]] | None = None,
        disk_reserve_bytes: int | None = None,
        estimated_disk_bytes: int | None = None,
        target_pressure_percent: float = DEFAULT_TARGET_PRESSURE_PERCENT,
        no_new_pressure_percent: float = DEFAULT_NO_NEW_PRESSURE_PERCENT,
        checkpoint_pressure_percent: float = DEFAULT_CHECKPOINT_PRESSURE_PERCENT,
        terminate_pressure_percent: float = DEFAULT_TERMINATE_PRESSURE_PERCENT,
        disk_suspend_percent: float = DEFAULT_DISK_SUSPEND_PERCENT,
        disk_suspend_floor_bytes: int = DEFAULT_DISK_SUSPEND_FLOOR_BYTES,
        recovery_window_ns: int = DEFAULT_RECOVERY_WINDOW_NS,
    ) -> None:
        if isinstance(sample_interval_ns, bool) or int(sample_interval_ns) < 1:
            raise ValueError("sample_interval_ns must be positive")
        thresholds = tuple(float(value) for value in (
            target_pressure_percent, no_new_pressure_percent,
            checkpoint_pressure_percent, terminate_pressure_percent,
        ))
        if any(value < 0 or value > 100 for value in thresholds) or not all(
            left < right for left, right in zip(thresholds, thresholds[1:])
        ):
            raise ValueError("pressure thresholds must ascend from 0 to 100")
        if int(recovery_window_ns) < 0:
            raise ValueError("recovery_window_ns must be non-negative")
        self.root = str(root)
        self.requested_workers = max(1, int(requested_workers))
        self.sample_interval_ns = int(sample_interval_ns)
        self.clock = clock
        default_probe = probe is None
        self._default_probe = default_probe
        self.observation_clock = observation_clock
        self.probe = probe or probe_local_capacity
        self.probe_kwargs = dict(probe_kwargs or {})
        configured_reserve = disk_reserve_bytes
        if configured_reserve is None:
            configured_reserve = int(os.environ.get("SIMPLICIO_LOOP_DISK_RESERVE_BYTES", DEFAULT_DISK_FLOOR_BYTES))
        estimated = estimated_disk_bytes
        if estimated is None:
            estimated = int(os.environ.get("SIMPLICIO_LOOP_ESTIMATED_DISK_BYTES", 0) or 0)
        self.disk_reserve_bytes = max(0, int(configured_reserve), int(estimated))
        if default_probe:
            self.probe_kwargs.setdefault("disk_floor_bytes", self.disk_reserve_bytes)
        self.pressure_probe = pressure_probe or _physical_pressure
        self.target_pressure_percent = thresholds[0]
        self.no_new_pressure_percent = thresholds[1]
        self.checkpoint_pressure_percent = thresholds[2]
        self.terminate_pressure_percent = thresholds[3]
        self.disk_suspend_percent = float(disk_suspend_percent)
        self.disk_suspend_floor_bytes = max(0, int(disk_suspend_floor_bytes))
        self.recovery_window_ns = int(recovery_window_ns)
        self.sample: CapacitySample | None = None
        self.last_sample_ns: int | None = None
        self.pressure: dict[str, Any] | None = None
        self.probe_error = ""
        self.pressure_error = ""
        self._had_pressure = False
        self._healthy_since_ns: int | None = None
        self._recovery_ready = True

    def due(self, now_ns: int | None = None) -> bool:
        if self.sample is None or self.last_sample_ns is None:
            return True
        now = int(self.clock() if now_ns is None else now_ns)
        return now - self.last_sample_ns >= self.sample_interval_ns

    def _exception_sample(self, now: int, error: Exception) -> CapacitySample:
        reason = "physical_probe_exception"
        unavailable = ("cpu_count", "disk_free_bytes", "memory_available_bytes")
        observed_at = int(self.observation_clock()) if self._default_probe else now
        return CapacitySample(
            requested_workers=self.requested_workers,
            safe_workers=0,
            cpu_count=None,
            memory_available_bytes=None,
            disk_free_bytes=None,
            measured=(),
            unavailable=unavailable,
            null_reasons={name: reason for name in (*unavailable, "workers")},
            observed_at_ns=observed_at,
        )

    def refresh(self, *, force: bool = False) -> CapacitySample:
        now = int(self.clock())
        if not force and self.sample is not None and not self.due(now):
            return self.sample
        self.probe_error = ""
        try:
            observation_now = int(self.observation_clock()) if self._default_probe else now
            sample = self.probe(
                self.root,
                requested_workers=self.requested_workers,
                now_ns=observation_now,
                **self.probe_kwargs,
            )
            if not isinstance(sample, CapacitySample):
                raise TypeError("capacity probe returned an invalid sample")
        except Exception as exc:
            self.probe_error = f"{type(exc).__name__}: {exc}"
            sample = self._exception_sample(now, exc)
        self.sample = sample
        self.last_sample_ns = now
        self.pressure_error = ""
        try:
            raw_pressure = dict(self.pressure_probe(self.root))
            pressure_percent = raw_pressure.get("pressure_percent")
            if pressure_percent is not None:
                raw_pressure["pressure_percent"] = float(pressure_percent)
            self.pressure = raw_pressure
        except Exception as exc:
            self.pressure_error = f"{type(exc).__name__}: {exc}"
            self.pressure = {"available": False, "pressure_percent": None, "error": self.pressure_error}
        self._update_recovery(now)
        return sample

    poll = refresh

    def _disk_suspend_active(self) -> bool:
        pressure = self.pressure or {}
        disk_used = pressure.get("disk_used_percent")
        disk_free = pressure.get("disk_free_bytes")
        if disk_used is None or disk_free is None:
            return bool(pressure.get("disk_suspend"))
        try:
            return (
                float(disk_used) >= self.disk_suspend_percent
                and int(disk_free) < self.disk_suspend_floor_bytes
            )
        except (TypeError, ValueError):
            return False

    def _update_recovery(self, now: int) -> None:
        pressure_percent = (self.pressure or {}).get("pressure_percent")
        disk_suspend = self._disk_suspend_active()
        # A zero-worker sample is itself a physical-pressure observation.  It must
        # enter the same sustained-recovery state as pressure percentages so a
        # transient capacity return cannot immediately admit heavy work.
        capacity_pressure = self.sample is not None and int(self.sample.safe_workers) < 1
        pressured = capacity_pressure or disk_suspend or (
            isinstance(pressure_percent, (int, float))
            and float(pressure_percent) >= self.no_new_pressure_percent
        )
        if pressured or self.pressure_error:
            self._had_pressure = True
            self._healthy_since_ns = None
            self._recovery_ready = False
            return
        if not self._had_pressure:
            self._recovery_ready = True
            return
        if self._healthy_since_ns is None:
            self._healthy_since_ns = now
        self._recovery_ready = now - self._healthy_since_ns >= self.recovery_window_ns

    @staticmethod
    def admission(sample: CapacitySample) -> dict[str, Any]:
        if sample.unavailable:
            reason = sample.null_reasons.get("workers", "required_capacity_signal_unavailable")
            return {
                "admitted": False,
                "reason_code": "PHYSICAL_SIGNAL_UNAVAILABLE",
                "reason": reason,
                "evidence": sample.to_dict(),
            }
        if sample.safe_workers < 1:
            return {
                "admitted": False,
                "reason_code": "PHYSICAL_CAPACITY_PRESSURE",
                "reason": sample.null_reasons.get("workers", "no_safe_workers"),
                "evidence": sample.to_dict(),
            }
        return {"admitted": True, "reason_code": "PHYSICAL_CAPACITY_AVAILABLE", "evidence": sample.to_dict()}

    def admission_status(self) -> dict[str, Any]:
        sample = self.sample
        if sample is None:
            return {
                "admitted": False,
                "reason_code": "PHYSICAL_SAMPLE_UNAVAILABLE",
                "reason": "no_sample",
                "action": "suspend_new",
                "evidence": {},
            }
        base = self.admission(sample)
        evidence = {
            "sample": sample.to_dict(),
            "pressure": dict(self.pressure or {}),
            "profile": self.profile(),
            "recovery": {
                "had_pressure": self._had_pressure,
                "healthy_since_ns": self._healthy_since_ns,
                "ready": self._recovery_ready,
            },
        }
        if not base.get("admitted"):
            base.update({"action": "suspend_new", "evidence": evidence})
            return base
        if self.probe_error:
            base.update({
                "admitted": False,
                "reason_code": "PHYSICAL_SIGNAL_UNAVAILABLE",
                "reason": "physical_probe_exception",
                "action": "suspend_new",
                "evidence": evidence,
            })
            return base
        pressure = self.pressure or {}
        if not pressure.get("available"):
            base.update({
                "admitted": False,
                "reason_code": "PHYSICAL_PRESSURE_UNAVAILABLE",
                "reason": "physical_pressure_probe_unavailable",
                "action": "suspend_new",
                "evidence": evidence,
            })
            return base
        percent = pressure.get("pressure_percent")
        disk_suspend = self._disk_suspend_active()
        if disk_suspend:
            base.update({
                "admitted": False,
                "reason_code": "PHYSICAL_DISK_SUSPEND",
                "reason": "disk_pressure_suspend",
                "action": "suspend_new",
                "evidence": evidence,
            })
            return base
        if isinstance(percent, (int, float)):
            percent = float(percent)
            if percent >= self.terminate_pressure_percent:
                base.update({"admitted": False, "reason_code": "PHYSICAL_PRESSURE_TERMINATE",
                             "reason": "pressure_terminate_owned", "action": "terminate_owned", "evidence": evidence})
                return base
            if percent >= self.checkpoint_pressure_percent:
                base.update({"admitted": False, "reason_code": "PHYSICAL_PRESSURE_CHECKPOINT",
                             "reason": "pressure_checkpoint_owned", "action": "checkpoint_owned_stop", "evidence": evidence})
                return base
            if percent >= self.no_new_pressure_percent:
                base.update({"admitted": False, "reason_code": "PHYSICAL_PRESSURE_NO_NEW",
                             "reason": "pressure_no_new_work", "action": "suspend_new", "evidence": evidence})
                return base
        if self._had_pressure and not self._recovery_ready:
            base.update({"admitted": False, "reason_code": "PHYSICAL_RECOVERY_SUSTAINING",
                         "reason": "healthy_capacity_not_sustained", "action": "suspend_new", "evidence": evidence})
            return base
        base.update({"action": "admit", "evidence": evidence})
        return base

    def profile(self) -> dict[str, Any]:
        return {
            "target_pressure_percent": self.target_pressure_percent,
            "no_new_pressure_percent": self.no_new_pressure_percent,
            "checkpoint_pressure_percent": self.checkpoint_pressure_percent,
            "terminate_pressure_percent": self.terminate_pressure_percent,
            "disk_reserve_bytes": self.disk_reserve_bytes,
            "disk_suspend_percent": self.disk_suspend_percent,
            "disk_suspend_floor_bytes": self.disk_suspend_floor_bytes,
            "recovery_window_ns": self.recovery_window_ns,
        }

    def status(self) -> dict[str, Any]:
        sample = self.sample
        admission = self.admission_status()
        return {
            "schema": MONITOR_SCHEMA,
            "sample_interval_ns": self.sample_interval_ns,
            "last_sample_ns": self.last_sample_ns,
            "sample": sample.to_dict() if sample is not None else None,
            "pressure": dict(self.pressure or {}),
            "probe_error": self.probe_error,
            "pressure_error": self.pressure_error,
            "profile": self.profile(),
            "recovery": {
                "had_pressure": self._had_pressure,
                "healthy_since_ns": self._healthy_since_ns,
                "ready": self._recovery_ready,
            },
            "admission": admission,
        }


__all__ = [
    "CapacitySample",
    "DEFAULT_DISK_FLOOR_BYTES",
    "DEFAULT_DISK_SUSPEND_FLOOR_BYTES",
    "DEFAULT_SAMPLE_INTERVAL_NS",
    "PhysicalAdmissionMonitor",
    "probe_local_capacity",
]
