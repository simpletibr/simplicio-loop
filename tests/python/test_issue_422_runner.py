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


def test_worktree_isolation_scenario_uses_ten_distinct_roots():
    runner = _runner_module()

    result = runner._worktree_isolation_scenario()

    assert result["status"] == "PASS"
    assert result["worktrees"] == 10
    assert result["unique_roots"] == 10
    assert result["scheduler_count"] == 1


def test_mapper_producer_requires_fresh_terminal_unlocked_handoff(monkeypatch):
    runner = _runner_module()
    monkeypatch.setattr(runner.shutil, "which", lambda name: "mapper.exe")

    def fake_run(command, **kwargs):
        if command[1] == "index":
            return runner.subprocess.CompletedProcess(command, 0, "{}", "")
        payload = {"status": {"terminal": True, "fresh": True, "lock": False, "counts": {"files": 1}}}
        return runner.subprocess.CompletedProcess(command, 0, runner.json.dumps(payload), "")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner._mapper_producer_scenario()

    assert result["status"] == "PASS"
    assert result["terminal"] is True
    assert result["fresh"] is True
    assert result["lock"] is False
