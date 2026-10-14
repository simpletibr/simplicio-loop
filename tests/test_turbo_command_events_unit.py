"""The turbo ``--verify`` command emits ``command_started`` / ``command_finished`` (dashboard-event/v1).

Red first: the verify command ran without dashboard events, so the panel's running-command line could not show it.
The events come from the runner (source ``runner``, collection scope, no task), share a ``command_id``, and the
panel reducer (``lane_extras``) reads them while the command runs and clears them once it finishes.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from simplicio_loop import dashboard_events, turbo, turbo_cli
from simplicio_loop.dashboard import lane_extras
from simplicio_loop.turbo_run import TurboRun

RECEIPT = {"schema": "simplicio.dev-cli.edit-receipt/v1", "applied": True, "receipt_digest": "deadbeef"}
PLAN = {"operations": [{"path": "hello.txt", "find": "", "replace": "hi\n"}]}


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    for name in ("SIMPLICIO_DASHBOARD_EVENTS", "SIMPLICIO_RUN_DIR", "SIMPLICIO_RUN_ID", "SIMPLICIO_ITERATION"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"]):
        subprocess.run(["git", *args], cwd=root, check=True)
    (root / "hello.txt").write_text("", encoding="utf-8")
    state = root / ".simplicio-loop"
    state.mkdir()
    (state / "project-map.json").write_text(
        json.dumps({"schema": "simplicio.project-map/v1", "files": [{"path": "hello.txt", "symbols": []}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", AsyncMock(return_value=None))
    return root


def _stub_dev_cli(tmp_path: Path, apply_stdout: str) -> Path:
    """A dev-cli stand-in: `edit --apply` prints ``apply_stdout``; compile always succeeds."""
    path = tmp_path / "stub-dev-cli"
    path.write_text(f"#!/bin/sh\ncase \"$*\" in *--apply*)\n  printf '%s\\n' '{apply_stdout}' ;;\nesac\nexit 0\n",
                    encoding="utf-8")
    path.chmod(0o755)
    return path


def _apply_host(repo: Path, tmp_path: Path, monkeypatch, capsys, **kwargs) -> dict:
    monkeypatch.setattr(turbo, "_dev_cli_bin", lambda: str(_stub_dev_cli(tmp_path, json.dumps(RECEIPT))))
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(PLAN), encoding="utf-8")
    turbo_cli.run(str(repo), [], apply=str(plan), **kwargs)
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    return json.loads(lines[-1])


def _run_dir(repo: Path, doc: dict) -> Path:
    return repo / ".simplicio-loop" / "orchestrator" / "runs" / doc["run_id"]


def _command_events(run_dir: Path) -> list[dict]:
    return [e for e in dashboard_events.read_events(run_dir) if e["kind"] in ("command_started", "command_finished")]


def test_verify_emits_started_then_finished_from_the_runner(repo, tmp_path, monkeypatch, capsys):
    doc = _apply_host(repo, tmp_path, monkeypatch, capsys, verify="exit 0")

    started, finished = _command_events(_run_dir(repo, doc))
    assert started["kind"] == "command_started" and finished["kind"] == "command_finished"
    assert started["source"] == "runner" and finished["source"] == "runner"
    assert started["scope"] == "collection" and started["task_id"] is None
    assert started["payload"]["command"] == "exit 0"
    assert started["phase"] == "verify" and finished["phase"] == "verify"
    assert finished["payload"]["command_id"] == started["payload"]["command_id"]
    assert finished["payload"]["exit_code"] == 0
    assert finished["payload"]["status"] == "pass"
    assert finished["payload"]["duration_s"] >= 0
    assert finished["severity"] == "info"


def test_a_failing_verify_is_finished_as_fail_with_its_exit_code(repo, tmp_path, monkeypatch, capsys):
    doc = _apply_host(repo, tmp_path, monkeypatch, capsys, verify="exit 3")

    _started, finished = _command_events(_run_dir(repo, doc))
    assert finished["payload"]["exit_code"] == 3
    assert finished["payload"]["status"] == "fail"
    assert finished["severity"] == "warning"


def test_a_timed_out_verify_is_finished_as_error_without_an_exit_code(repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(turbo_cli, "VERIFY_TIMEOUT_S", 0.5)
    doc = _apply_host(repo, tmp_path, monkeypatch, capsys, verify="sleep 5")

    _started, finished = _command_events(_run_dir(repo, doc))
    assert finished["payload"]["exit_code"] is None
    assert finished["payload"]["status"] == "error"
    assert finished["payload"]["reason"] == "timeout"


def test_the_verify_command_text_is_scrubbed_before_it_is_written(repo, tmp_path, monkeypatch, capsys):
    doc = _apply_host(repo, tmp_path, monkeypatch, capsys, verify="true --token SUPERSECRET123")

    started, _finished = _command_events(_run_dir(repo, doc))
    assert "SUPERSECRET123" not in json.dumps(started)


def test_the_kill_switch_leaves_the_verify_result_untouched(repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_DASHBOARD_EVENTS", "0")
    doc = _apply_host(repo, tmp_path, monkeypatch, capsys, verify="exit 0")

    assert doc["verify"]["passed"] is True
    assert _command_events(_run_dir(repo, doc)) == []


def test_the_panel_reducer_shows_the_verify_while_it_runs_and_clears_it_after(tmp_path):
    run = TurboRun(tmp_path, "host")

    with run.command("pytest -q") as span:
        running = lane_extras.extras(run.run_dir, dashboard_events.read_events(run.run_dir))["running_command"]
        assert running["state"] == "PASS"
        (row,) = running["lanes"]
        assert row["state"] == "MEASURED" and row["command"] == "pytest -q" and row["age_s"] >= 0
        span.exit_code = 0

    finished = lane_extras.extras(run.run_dir, dashboard_events.read_events(run.run_dir))["running_command"]
    assert finished["lanes"] == []
    assert finished["reason"] == lane_extras.IDLE_REASON
