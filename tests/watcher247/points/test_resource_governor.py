"""Tests for resource_governor extension point (intake stage).

Tests the contract: probe local capacity, return blocked when thresholds are crossed.
"""
import os
import shutil
from pathlib import Path
from unittest import mock

import pytest

from simplicio_loop.watcher247.points import resource_governor


class TestResourceGovernor:
    """resource_governor probes CPU, RAM, disk and blocks when low."""

    def test_ok_when_resources_available(self, point_contract, make_ctx, tmp_path, monkeypatch):
        """When load and disk are healthy, return ok with evidence."""
        usage = mock.MagicMock()
        usage.free = 10 * (1 << 30)
        usage.total = 100 * (1 << 30)
        monkeypatch.setattr(shutil, "disk_usage", lambda path: usage)
        result = point_contract("resource_governor", make_ctx(state_dir=tmp_path), expect="ok")
        assert result.reason_code is None
        assert "cpu_load" in result.evidence
        assert "disk_free_gb" in result.evidence

    def test_blocked_on_high_load(self, point_contract, make_ctx, tmp_path, monkeypatch):
        """When CPU load exceeds max, return blocked."""
        cpu_count = os.cpu_count() or 4
        monkeypatch.setattr(os, "getloadavg", lambda: (cpu_count + 5.0, 0, 0))
        result = point_contract("resource_governor", make_ctx(state_dir=tmp_path), expect="blocked")
        assert result.reason_code == "high_load"

    def test_blocked_on_low_disk(self, point_contract, make_ctx, tmp_path, monkeypatch):
        """When disk free is below minimum, return blocked."""
        usage = mock.MagicMock()
        usage.free = 1 * (1 << 30)  # 1 GB
        usage.total = 100 * (1 << 30)
        monkeypatch.setattr(shutil, "disk_usage", lambda path: usage)
        result = point_contract("resource_governor", make_ctx(state_dir=tmp_path), expect="blocked")
        assert result.reason_code == "low_disk"
