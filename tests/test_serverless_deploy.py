from __future__ import annotations

import pytest

from simplicio_loop.serverless_deploy import DeploymentGateError, build_plan, execute_plan


def test_dry_run_is_read_only_and_classifies_missing_adapter(tmp_path) -> None:
    plan = build_plan(tmp_path, backend="modal", environment="staging", image="app:test")
    assert plan["mode"] == "dry_run"
    assert plan["effects_attempted"] is False
    assert plan["status"] == "BLOCKED"
    assert plan["reason_code"] == "serverless_adapter_missing"
    assert plan["receipt_hash"].startswith("sha256:")


def test_apply_requires_action_gate_before_provider_execution(tmp_path) -> None:
    plan = build_plan(tmp_path, backend="daytona")
    blocked = execute_plan(plan, apply=True)
    assert blocked["reason_code"] == "action_gate_required"
    assert blocked["effects_attempted"] is False


def test_invalid_backend_and_unenabled_provider_fail_closed(tmp_path) -> None:
    with pytest.raises(ValueError, match="backend"):
        build_plan(tmp_path, backend="unknown")
    plan = dict(build_plan(tmp_path, backend="modal"), adapter_available=True)
    with pytest.raises(DeploymentGateError, match="not enabled"):
        execute_plan(plan, apply=True, action_gate=True)
