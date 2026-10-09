"""Tests for autoscale extension point (intake stage).

Tests the contract: record safe concurrency estimate in evidence.
All probes are monkeypatched to be host-independent.
"""
from unittest import mock

import pytest

from simplicio_loop import economy_profile, local_capacity
from simplicio_loop.watcher247.points import autoscale, registry



class TestAutoscale:
    """autoscale records safe concurrency estimate."""

    def _patch_disk(self, monkeypatch):
        """Patch resource_governor probe to not block on low disk."""
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

    def test_ok_with_evidence(self, point_contract, make_ctx, tmp_path, monkeypatch):
        """When recommendation succeeds, return ok with safe_concurrency."""
        self._patch_disk(monkeypatch)
        monkeypatch.setattr(
            economy_profile, "recommend_operator_workers", lambda cpu=None: 4
        )
        result = point_contract("autoscale", make_ctx(state_dir=tmp_path), expect="ok")
        assert result.reason_code is None
        assert "safe_concurrency" in result.evidence
        assert result.evidence["safe_concurrency"] == 4

    def test_safe_concurrency_is_positive(self, point_contract, make_ctx, tmp_path, monkeypatch):
        """Safe concurrency is always positive."""
        self._patch_disk(monkeypatch)
        monkeypatch.setattr(
            economy_profile, "recommend_operator_workers", lambda cpu=None: 2
        )
        result = point_contract("autoscale", make_ctx(state_dir=tmp_path), expect="ok")
        assert result.evidence["safe_concurrency"] >= 1
