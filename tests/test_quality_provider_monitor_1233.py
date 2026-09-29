"""Focused real-child regressions for quality-provider physical admission (#1233)."""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import simplicio_loop.quality_provider as boundary
import simplicio_loop.quality_providers.simplicio_loop_quality as provider


def _write_check(repo: Path, body: str) -> Path:
    script = repo / "scripts" / "check.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(body, encoding="utf-8")
    return script


class _AdmittedMonitor:
    def __init__(self, _repo: Path):
        self.refreshes = 0

    def refresh(self, *, force=False):
        self.refreshes += 1
        return self

    def due(self):
        return False

    def admission_status(self):
        return {"admitted": True, "action": "admit", "reason_code": "PHYSICAL_CAPACITY_AVAILABLE"}

    def status(self):
        return {"refreshes": self.refreshes, "admission": self.admission_status()}


def test_quality_provider_denies_before_spawn_when_physical_signal_missing(monkeypatch, tmp_path):
    script = _write_check(tmp_path, "raise SystemExit('must not run')\n")

    class Denied(_AdmittedMonitor):
        def admission_status(self):
            return {"admitted": False, "action": "suspend_new", "reason_code": "PHYSICAL_SIGNAL_UNAVAILABLE"}

    calls = []
    monkeypatch.setattr(provider, "_build_monitor", lambda _repo: Denied(tmp_path))
    monkeypatch.setattr(provider, "run_bounded", lambda *args, **kwargs: calls.append(True))
    result = provider.run(run_id="r", tasks=[], attempt=1, repo=str(tmp_path), worktree=str(tmp_path), head="h", diff_hash="d", policy="strict-default")
    assert result["status"] == "BLOCKED"
    assert result["findings"][0]["reason_code"] == "PHYSICAL_SIGNAL_UNAVAILABLE"
    assert calls == []
    assert script.exists()




def test_quality_provider_routes_core_gate_with_existing_900_second_bound(monkeypatch, tmp_path):
    _write_check(tmp_path, "print('core-route-ok')\n")
    captured = {}
    monkeypatch.setattr(provider, "_build_monitor", lambda _repo: _AdmittedMonitor(tmp_path))

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        captured.update(kwargs)
        from scripts.check_runtime import CommandResult
        return CommandResult(0, stdout="core-route-ok\n")

    monkeypatch.setattr(provider, "run_bounded", fake_run)
    result = provider.run(run_id="r", tasks=[], attempt=1, repo=str(tmp_path), worktree=str(tmp_path), head="h", diff_hash="d", policy="strict-default")
    assert result["status"] == "PASS"
    assert captured["argv"][-1] == "--core-gate"
    assert captured["timeout_seconds"] == provider.CORE_GATE_TIMEOUT_SECONDS == 900.0


def test_quality_provider_keeps_active_child_on_suspend_new(monkeypatch, tmp_path):
    _write_check(tmp_path, "import time; time.sleep(0.15); print('completed', flush=True)\n")

    class SuspendNew(_AdmittedMonitor):
        def __init__(self, repo):
            super().__init__(repo)
            self.polls = 0

        def due(self):
            self.polls += 1
            return self.polls >= 2

        def admission_status(self):
            if self.refreshes >= 2:
                return {"admitted": False, "action": "suspend_new", "reason_code": "PHYSICAL_PRESSURE_NO_NEW"}
            return {"admitted": True, "action": "admit", "reason_code": "PHYSICAL_CAPACITY_AVAILABLE"}

    monkeypatch.setattr(provider, "_build_monitor", lambda _repo: SuspendNew(tmp_path))
    result = provider.run(run_id="r", tasks=[], attempt=1, repo=str(tmp_path), worktree=str(tmp_path), head="h", diff_hash="d", policy="strict-default")
    assert result["status"] == "PASS"
    assert "completed" in result["detail"]


def test_builtin_provider_outer_boundary_allows_real_small_core_child(monkeypatch, tmp_path):
    _write_check(tmp_path, "import sys; assert '--core-gate' in sys.argv[1:]; print('small-core-ok')\n")
    monkeypatch.setattr(provider, "_build_monitor", lambda _repo: _AdmittedMonitor(tmp_path))
    spec = boundary.load_quality_provider("simplicio_loop_quality", "strict-default")
    result = boundary.run_quality_gate(str(tmp_path), "run-small-core", spec)
    assert result.status == "PASS"
    assert "small-core-ok" in result.detail
    assert spec.capabilities["quality_gate_outer_timeout_seconds"] > boundary.PROVIDER_TIMEOUT_SECONDS


def test_quality_provider_cancels_real_owned_child_under_fake_pressure(monkeypatch, tmp_path):
    _write_check(tmp_path, "import time; print('started', flush=True); time.sleep(30)\n")

    class Pressure(_AdmittedMonitor):
        def __init__(self, repo):
            super().__init__(repo)
            self.polls = 0

        def due(self):
            self.polls += 1
            return self.polls >= 2

        def admission_status(self):
            if self.refreshes >= 2:
                return {"admitted": False, "action": "terminate_owned", "reason_code": "PHYSICAL_PRESSURE_TERMINATE", "evidence": {"fake": True}}
            return {"admitted": True, "action": "admit", "reason_code": "PHYSICAL_CAPACITY_AVAILABLE"}

    monkeypatch.setattr(provider, "_build_monitor", lambda _repo: Pressure(tmp_path))
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    started = time.monotonic()
    try:
        result = provider.run(run_id="r", tasks=[], attempt=1, repo=str(tmp_path), worktree=str(tmp_path), head="h", diff_hash="d", policy="strict-default")
        elapsed = time.monotonic() - started
        assert result["status"] == "BLOCKED"
        assert result["findings"][0]["reason_code"].startswith("PHYSICAL_PRESSURE_TERMINATE")
        assert elapsed < 10
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=3)


def test_quality_provider_preserves_successful_check_output_and_receipt(monkeypatch, tmp_path):
    script = _write_check(tmp_path, "print('quality-ok')\n")
    monkeypatch.setattr(provider, "_build_monitor", lambda _repo: _AdmittedMonitor(tmp_path))
    result = provider.run(run_id="r", tasks=[], attempt=1, repo=str(tmp_path), worktree=str(tmp_path), head="h", diff_hash="d", policy="strict-default")
    assert result["status"] == "PASS"
    assert str(script) in result["receipts"]
    assert "evidence=" in result["detail"]


def test_quality_provider_honours_stop_before_spawn(monkeypatch, tmp_path):
    _write_check(tmp_path, "raise SystemExit('must not run')\n")
    stop = threading.Event()
    stop.set()
    monkeypatch.setattr(provider, "run_bounded", lambda *args, **kwargs: pytest.fail("spawned after STOP"))
    result = provider.run(run_id="r", tasks=[], attempt=1, repo=str(tmp_path), worktree=str(tmp_path), head="h", diff_hash="d", policy="strict-default", cancel_token=stop)
    assert result["status"] == "BLOCKED"
    assert result["findings"][0]["reason_code"] == "QUALITY_CANCELLED_BEFORE_ADMISSION"


def test_the_quality_monitor_honors_the_documented_pressure_profile(tmp_path, monkeypatch):
    """SIMPLICIO_LOOP_*_PRESSURE_PERCENT is the one physical-admission profile: dispatch and the quality gate share it."""
    monkeypatch.setenv("SIMPLICIO_LOOP_TARGET_PRESSURE_PERCENT", "99.1")
    monkeypatch.setenv("SIMPLICIO_LOOP_NO_NEW_PRESSURE_PERCENT", "99.3")
    monkeypatch.setenv("SIMPLICIO_LOOP_CHECKPOINT_PRESSURE_PERCENT", "99.5")
    monkeypatch.setenv("SIMPLICIO_LOOP_TERMINATE_PRESSURE_PERCENT", "99.9")
    monitor = provider._build_monitor(tmp_path)
    assert (monitor.target_pressure_percent, monitor.terminate_pressure_percent) == (99.1, 99.9)
    monkeypatch.delenv("SIMPLICIO_LOOP_TERMINATE_PRESSURE_PERCENT")
    monkeypatch.delenv("SIMPLICIO_LOOP_TARGET_PRESSURE_PERCENT")
    monkeypatch.delenv("SIMPLICIO_LOOP_NO_NEW_PRESSURE_PERCENT")
    monkeypatch.delenv("SIMPLICIO_LOOP_CHECKPOINT_PRESSURE_PERCENT")
    assert provider._build_monitor(tmp_path).terminate_pressure_percent == 88.0
