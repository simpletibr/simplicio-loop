"""Contract classification tests for the issue #422 evidence runner."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _runner_module():
    path = Path(__file__).parents[2] / "scripts" / "issue_422_e2e.py"
    spec = importlib.util.spec_from_file_location("issue_422_e2e", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_probe_reports_verified_contract_without_claiming_e2e(monkeypatch):
    runner = _runner_module()
    monkeypatch.setattr(
        runner,
        "runtime_verify_contract",
        lambda **_: {
            "verified": True,
            "version": "3.5.6",
            "binary": "simplicio-runtime",
            "capabilities": ["simplicio.effect-transaction/v1"],
        },
    )

    result = runner._runtime_scenario()

    assert result["status"] == "AVAILABLE_NOT_E2E"
    assert result["version"] == "3.5.6"
    assert "effect E2E" in result["reason"]


def test_runtime_probe_keeps_failed_contract_unverified(monkeypatch):
    runner = _runner_module()
    monkeypatch.setattr(
        runner,
        "runtime_verify_contract",
        lambda **_: {
            "verified": False,
            "reason": "runtime-binary-not-found",
            "capabilities": [],
        },
    )

    result = runner._runtime_scenario()

    assert result["status"] == "UNVERIFIED"
    assert result["reason"] == "runtime-binary-not-found"
