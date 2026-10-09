"""Tests for autoscale extension point (intake stage).

Tests the contract: record safe concurrency estimate in evidence.
All probes are monkeypatched to be host-independent.
"""
from unittest import mock

import pytest

from simplicio_loop import economy_profile
from simplicio_loop.watcher247.points import autoscale



class TestAutoscale:
    """autoscale records safe concurrency estimate."""

    def test_ok_with_evidence(self, point_contract, make_ctx, tmp_path, monkeypatch):
        """When recommendation succeeds, return ok with safe_concurrency."""
        monkeypatch.setattr(
            economy_profile, "recommend_operator_workers", lambda cpu=None: 4
        )
        result = point_contract("autoscale", make_ctx(state_dir=tmp_path), expect="ok")
        assert result.reason_code is None
        assert "safe_concurrency" in result.evidence
        assert result.evidence["safe_concurrency"] == 4

    def test_safe_concurrency_is_positive(self, point_contract, make_ctx, tmp_path, monkeypatch):
        """Safe concurrency is always positive."""
        monkeypatch.setattr(
            economy_profile, "recommend_operator_workers", lambda cpu=None: 2
        )
        result = point_contract("autoscale", make_ctx(state_dir=tmp_path), expect="ok")
        assert result.evidence["safe_concurrency"] >= 1
