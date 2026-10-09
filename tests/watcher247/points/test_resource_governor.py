"""Tests for resource_governor extension point (intake stage).

Tests the contract: probe local capacity, defer when thresholds are crossed.
All probes are monkeypatched to be host-independent.
"""
from unittest import mock

import pytest

from simplicio_loop import local_capacity
from simplicio_loop.watcher247.points import resource_governor


class TestResourceGovernor:
    """resource_governor defers when disk or memory is low."""

    def test_ok_when_resources_available(self, point_contract, make_ctx, tmp_path, monkeypatch):
        """When disk and memory are sufficient, return ok with evidence."""
        sample = local_capacity.CapacitySample(
            requested_workers=1,
            safe_workers=1,
            cpu_count=4,
            memory_available_bytes=4 * (1 << 30),
            disk_free_bytes=20 * (1 << 30),
            measured=("cpu_count", "disk_free_bytes", "memory_available_bytes"),
            unavailable=(),
            null_reasons={},
            observed_at_ns=0,
        )
        monkeypatch.setattr(
            local_capacity, "probe_local_capacity", lambda *a, **kw: sample
        )
        result = point_contract("resource_governor", make_ctx(state_dir=tmp_path), expect="ok")
        assert result.reason_code is None
        assert "disk_free_gb" in result.evidence

    def test_deferred_on_low_disk(self, point_contract, make_ctx, tmp_path, monkeypatch):
        """When disk free is below minimum, return deferred status."""
        sample = local_capacity.CapacitySample(
            requested_workers=1,
            safe_workers=0,
            cpu_count=4,
            memory_available_bytes=4 * (1 << 30),
            disk_free_bytes=1 * (1 << 30),
            measured=("cpu_count", "disk_free_bytes", "memory_available_bytes"),
            unavailable=(),
            null_reasons={},
            observed_at_ns=0,
        )
        monkeypatch.setattr(
            local_capacity, "probe_local_capacity", lambda *a, **kw: sample
        )
        result = point_contract("resource_governor", make_ctx(state_dir=tmp_path), expect="deferred")
        assert result.reason_code == "low_disk"

    def test_deferred_on_low_memory(self, point_contract, make_ctx, tmp_path, monkeypatch):
        """When memory available is below minimum, return deferred status."""
        sample = local_capacity.CapacitySample(
            requested_workers=1,
            safe_workers=0,
            cpu_count=4,
            memory_available_bytes=100 * (1 << 20),
            disk_free_bytes=20 * (1 << 30),
            measured=("cpu_count", "disk_free_bytes", "memory_available_bytes"),
            unavailable=(),
            null_reasons={},
            observed_at_ns=0,
        )
        monkeypatch.setattr(
            local_capacity, "probe_local_capacity", lambda *a, **kw: sample
        )
        result = point_contract("resource_governor", make_ctx(state_dir=tmp_path), expect="deferred")
        assert result.reason_code == "low_memory"
