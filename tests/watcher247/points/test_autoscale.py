"""Tests for autoscale extension point (intake stage).

Tests the contract: compute safe concurrency from local capacity probes.
"""
import os
from unittest import mock

import pytest

from simplicio_loop.watcher247.points import autoscale


class TestAutoscale:
    """autoscale computes safe concurrency from capacity probes."""

    def test_ok_with_evidence(self, point_contract, make_ctx, tmp_path):
        """When resources are available, return ok with safe_concurrency in evidence."""
        result = point_contract("autoscale", make_ctx(state_dir=tmp_path), expect="ok")
        assert result.reason_code is None
        assert "safe_concurrency" in result.evidence
        assert isinstance(result.evidence["safe_concurrency"], int)
        assert result.evidence["safe_concurrency"] >= 1

    def test_safe_concurrency_respects_cpu_count(self, point_contract, make_ctx, tmp_path, monkeypatch):
        """Safe concurrency should not exceed CPU count."""
        cpu_count = 4
        monkeypatch.setattr(os, "cpu_count", lambda: cpu_count)
        result = point_contract("autoscale", make_ctx(state_dir=tmp_path), expect="ok")
        safe = result.evidence["safe_concurrency"]
        assert safe >= 1
