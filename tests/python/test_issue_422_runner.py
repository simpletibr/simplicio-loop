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
    assert "SIMPLICIO_RUNTIME_EFFECT_URL" in result["reason"]


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


def test_runtime_probe_executes_and_replays_configured_http_effect(monkeypatch, tmp_path):
    runner = _runner_module()
    monkeypatch.setattr(
        runner,
        "runtime_verify_contract",
        lambda **_: {
            "verified": True,
            "version": "3.5.7",
            "binary": "simplicio-runtime",
            "capabilities": ["simplicio.effect-transaction/v1"],
        },
    )
    monkeypatch.setenv("SIMPLICIO_RUNTIME_EFFECT_URL", "http://127.0.0.1:9119")
    monkeypatch.setenv("SIMPLICIO_RUNTIME_E2E_ROOT", str(tmp_path))
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: runner.subprocess.CompletedProcess(
            args[0],
            0,
            runner.json.dumps({"status": "authorized", "authorization_digest": "sha256:" + "a" * 64}),
            "",
        ),
    )

    class FakeTransport:
        def __init__(self, base_url, *, timeout_s):
            assert base_url.endswith(":9119")
            assert timeout_s == 20.0
            self.receipt = None

        def capabilities(self):
            return {"effect_transaction_schemas": ["simplicio.effect-transaction/v1"]}

        def submit(self, transaction):
            artifact = tmp_path / transaction["effect"]["artifact_ref"]
            plan = runner.json.loads(artifact.read_text(encoding="utf-8"))
            target = tmp_path / plan["file"]
            target.write_text("before\nruntime-e2e\n", encoding="utf-8")
            self.receipt = {"state": "completed"}
            return self.receipt

        def query(self, key):
            assert len(key) == 64
            return self.receipt

    monkeypatch.setattr(runner, "HttpRuntimeTransport", FakeTransport)

    result = runner._runtime_scenario()

    assert result["status"] == "PASS"
    assert result["receipt_state"] == "completed"
    assert result["replay_state"] == "completed"


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


def test_fast_rust_smoke_requires_native_abi_and_never_falls_back(monkeypatch, tmp_path):
    runner = _runner_module()
    monkeypatch.setenv("SIMPLICIO_FAST_NATIVE", "native.exe")
    native = tmp_path / "native.exe"
    native.write_text("placeholder", encoding="utf-8")
    monkeypatch.setenv("SIMPLICIO_FAST_NATIVE", str(native))
    responses = [
        {
            "abi": "simplicio.fast-native/v1",
            "ok": True,
            "result": "8f434346648f6b96df89dda901c5176b10a6d83961dd3c1ac88b59b2dc327aa4",
        },
        {"abi": "simplicio.fast-native/v1", "ok": True, "result": {"add": 3, "keep": 1}},
    ]
    response_iter = iter(responses)
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: runner.subprocess.CompletedProcess(
            args[0], 0, runner.json.dumps(next(response_iter)), ""
        ),
    )

    result = runner._fast_rust_scenario(tmp_path)

    assert result["status"] == "PASS"
    assert result["abi"] == "simplicio.fast-native/v1"
