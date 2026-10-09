"""Physical pressure must use df semantics, not 1 - free/total."""
from __future__ import annotations

from collections import namedtuple

from simplicio_loop import local_capacity as lc

_Usage = namedtuple("_Usage", "total used free")


def test_disk_used_percent_matches_df_when_total_includes_reserved_space(monkeypatch, tmp_path):
    # Measured on a sandbox VM: total=252G, used=9.7G, free=28G -> df reports 26%.
    gib = 1024 ** 3
    monkeypatch.setattr(lc.shutil, "disk_usage", lambda _p: _Usage(252 * gib, int(9.7 * gib), 28 * gib))
    monkeypatch.setattr(lc, "_cgroup_memory_stats", lambda: None)
    pressure = lc._physical_pressure(tmp_path)
    assert round(pressure["disk_used_percent"]) == 26


def test_cgroup_v1_unlimited_sentinel_is_not_a_limit(monkeypatch, tmp_path):
    base = tmp_path / "cg"
    (base / "memory").mkdir(parents=True)
    (base / "memory" / "memory.usage_in_bytes").write_text("1073741824\n")
    (base / "memory" / "memory.limit_in_bytes").write_text("9223372036854771712\n")
    real_path = lc.Path

    def fake_path(value):
        text = str(value)
        return real_path(text.replace("/sys/fs/cgroup", str(base))) if text.startswith("/sys/fs/cgroup") else real_path(value)

    monkeypatch.setattr(lc, "Path", fake_path)
    assert lc._cgroup_memory_stats() is None


def test_linux_memory_comes_from_proc_meminfo_without_psutil(monkeypatch, tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       16000000 kB\nMemAvailable:    8000000 kB\n")
    monkeypatch.setattr(lc, "_PROC_MEMINFO", meminfo)
    assert lc._linux_memory_available() == 8000000 * 1024


def _probe_cores(monkeypatch, tmp_path, *, cpu_count, affinity, quota=None):
    """cpu_count the probe reports for a host with `cpu_count` cores, a CPU affinity set and a cgroup quota."""
    monkeypatch.setattr(lc.os, "cpu_count", lambda: cpu_count)
    if affinity is None:
        monkeypatch.delattr(lc.os, "sched_getaffinity", raising=False)
    elif isinstance(affinity, Exception):
        def broken(_pid):
            raise affinity
        monkeypatch.setattr(lc.os, "sched_getaffinity", broken, raising=False)
    else:
        monkeypatch.setattr(lc.os, "sched_getaffinity", lambda pid: set(affinity), raising=False)
    monkeypatch.setattr(lc, "_cgroup_cpu_capacity", lambda: quota)
    monkeypatch.setattr(lc, "_memory_available", lambda: 8 * 1024 ** 3)
    return lc.probe_local_capacity(tmp_path, requested_workers=1, reserve_workers=0).cpu_count


def test_cpu_affinity_limits_the_core_count(monkeypatch, tmp_path):
    # `taskset -c 0,1` on a 10-core host: only 2 CPUs may run this process; os.cpu_count() still says 10.
    assert _probe_cores(monkeypatch, tmp_path, cpu_count=10, affinity={0, 1}) == 2


def test_the_cgroup_quota_still_applies_below_the_affinity(monkeypatch, tmp_path):
    assert _probe_cores(monkeypatch, tmp_path, cpu_count=10, affinity={0, 1, 2, 3}, quota=3) == 3
    assert _probe_cores(monkeypatch, tmp_path, cpu_count=10, affinity={0, 1}, quota=6) == 2


def test_without_affinity_support_the_probe_uses_cpu_count(monkeypatch, tmp_path):
    assert _probe_cores(monkeypatch, tmp_path, cpu_count=10, affinity=None) == 10  # macOS and Windows have no sched_getaffinity
    assert _probe_cores(monkeypatch, tmp_path, cpu_count=10, affinity=OSError("denied")) == 10
    assert _probe_cores(monkeypatch, tmp_path, cpu_count=10, affinity=set()) == 10, "an empty set is not a measurement"
    assert _probe_cores(monkeypatch, tmp_path, cpu_count=10, affinity=None, quota=4) == 4


def test_the_affinity_is_a_measurement_when_cpu_count_is_unreadable(monkeypatch, tmp_path):
    assert _probe_cores(monkeypatch, tmp_path, cpu_count=0, affinity={0, 1}) == 2
    assert _probe_cores(monkeypatch, tmp_path, cpu_count=0, affinity=None) is None, "nothing measured stays unavailable"
