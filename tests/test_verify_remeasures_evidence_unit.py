"""verify re-measures evidence on the final tree before the watcher runs, so a
receipt written mid-wave by a parallel lane cannot carry a stale diff hash."""
from __future__ import annotations

from simplicio_loop import runner
from tests.runner_patch import patch_runner
from tests.runner_patch import patch_runner
from tests.runner_patch import patch_runner


def test_verify_rebuilds_evidence_before_watching(tmp_path, monkeypatch):
    calls = []
    patch_runner(monkeypatch, "read_status", lambda repo, run_id: {
        "run_dir": str(tmp_path), "manifest": {"repo": str(tmp_path)}, "state": {"phase": "validating"}})
    patch_runner(monkeypatch, "build_evidence_receipt", lambda run_dir: calls.append("evidence") or {"run": {}})
    patch_runner(monkeypatch, "_transition", lambda *a, **k: calls.append("watching"))

    class Stop(Exception):
        pass

    def fake_run(*a, **k):
        raise Stop

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    try:
        runner.verify_run(str(tmp_path), "run-1")
    except Stop:
        pass
    assert calls[:2] == ["evidence", "watching"]
