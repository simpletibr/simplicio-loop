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
