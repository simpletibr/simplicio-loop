"""Unit tests for the command_started / command_finished producer (issue #1551).

The producer wraps a real command run and appends a ``command_started`` event before it and a matching
``command_finished`` (exit code, duration from a monotonic clock) after it, through the dashboard events API. The
command text is scrubbed and capped before it is written, and a failing writer never breaks the run.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import dashboard_events as de
import pytest

from simplicio_loop import command_events
from simplicio_loop.dashboard import lane_extras

PYTHON = sys.executable
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "contracts" / "dashboard-event" / "v1" / "schema.json"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    for name in ("SIMPLICIO_DASHBOARD_EVENTS", "SIMPLICIO_RUN_DIR", "SIMPLICIO_RUN_ID", "SIMPLICIO_ITERATION"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    monkeypatch.setenv("SIMPLICIO_RUN_DIR", str(run))
    return run


def _events(run: Path) -> list[dict]:
    path = run / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sleep_command(seconds: float, code: int = 0) -> list[str]:
    return [PYTHON, "-c", f"import sys, time; time.sleep({seconds}); sys.exit({code})"]


def _run_tracked(task_id: str, argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    with command_events.track(task_id, " ".join(argv), **kwargs) as span:
        proc = subprocess.run(argv, capture_output=True, text=True)
        span.exit_code = proc.returncode
    return proc


def test_the_event_pair_is_emitted_around_a_real_subprocess(run_dir):
    proc = _run_tracked("T1", _sleep_command(0.2))
    assert proc.returncode == 0
    started, finished = _events(run_dir)
    assert (started["kind"], finished["kind"]) == ("command_started", "command_finished")
    assert started["seq"] < finished["seq"] and started["ts"] <= finished["ts"]
    assert started["payload"]["command_id"] == finished["payload"]["command_id"]
    assert started["payload"]["command"].startswith(PYTHON)
    assert (started["task_id"], started["scope"], started["source"]) == ("T1", "task", "worker")
    assert finished["task_id"] == "T1"
    assert finished["payload"]["exit_code"] == 0 and finished["payload"]["status"] == "pass"
    assert 0.2 <= finished["payload"]["duration_s"] < 10
    assert finished["severity"] == "info"
    for evt in (started, finished):
        assert de.validate_envelope(evt) == [], evt


def test_a_failing_command_is_finished_with_its_exit_code_and_a_warning(run_dir):
    proc = _run_tracked("T1", _sleep_command(0, code=3))
    assert proc.returncode == 3
    finished = _events(run_dir)[1]
    assert (finished["payload"]["exit_code"], finished["payload"]["status"], finished["severity"]) == (3, "fail", "warning")


def test_the_duration_comes_from_the_monotonic_clock_not_the_wall_clock(run_dir, monkeypatch):
    ticks = iter(range(1, 10_000))
    monkeypatch.setattr(time, "time", lambda: 2_000_000_000.0 - next(ticks) * 3600.0)  # the wall clock jumps backwards
    _run_tracked("T1", _sleep_command(0.2))
    finished = _events(run_dir)[1]
    assert 0.2 <= finished["payload"]["duration_s"] < 10


def test_the_start_event_is_written_before_the_command_runs(run_dir):
    with command_events.track("T1", "sleep 1") as span:
        assert [e["kind"] for e in _events(run_dir)] == ["command_started"]
        span.exit_code = 0
    assert [e["kind"] for e in _events(run_dir)] == ["command_started", "command_finished"]


def test_an_exception_in_the_body_still_finishes_the_command_and_propagates(run_dir):
    with pytest.raises(ValueError):
        with command_events.track("T1", "boom"):
            raise ValueError("boom")
    finished = _events(run_dir)[1]
    assert (finished["kind"], finished["payload"]["status"], finished["payload"]["exit_code"]) == (
        "command_finished", "interrupted", None)


def test_a_cancelled_async_run_still_finishes_the_command(run_dir):
    async def scenario():
        task = asyncio.ensure_future(command_events.around("T1", "sleep 9", asyncio.sleep(9)))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    assert [e["kind"] for e in _events(run_dir)] == ["command_started", "command_finished"]
    assert _events(run_dir)[1]["payload"]["status"] == "interrupted"


def test_around_reads_the_exit_code_and_the_reason_from_a_check_result(run_dir):
    async def run(result):
        async def check():
            return result
        return await command_events.around("T1", "pytest -q", check())
    assert asyncio.run(run({"ok": True, "returncode": 0})) == {"ok": True, "returncode": 0}
    asyncio.run(run({"ok": False, "reason_code": "check_timeout"}))
    ok, timeout = [e["payload"] for e in _events(run_dir) if e["kind"] == "command_finished"]
    assert (ok["exit_code"], ok["status"]) == (0, "pass")
    assert (timeout["exit_code"], timeout["status"], timeout["reason"]) == (None, "error", "check_timeout")


def test_secrets_are_scrubbed_before_the_command_is_written(run_dir):
    command = ("API_TOKEN=s3cr3tvalue123 curl https://user:p4ssw0rdvalue@example.com/x "
               "-H 'Authorization: Bearer abcdefghijklmnop' --password hunter2hunter2 mail me@example.com")
    with command_events.track("T1", command) as span:
        span.exit_code = 0
    raw = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    for secret in ("s3cr3tvalue123", "p4ssw0rdvalue", "abcdefghijklmnop", "hunter2hunter2", "me@example.com"):
        assert secret not in raw, secret
    assert "[REDACTED" in raw


def test_a_secret_cut_by_the_length_cap_is_scrubbed_first(run_dir):
    command = "a" * 187 + " password=hunter2hunter2 " + "b" * 400  # a cut first would leave "hun" behind, too short to match
    with command_events.track("T1", command) as span:
        span.exit_code = 0
    started = _events(run_dir)[0]
    assert "hun" not in (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert len(started["payload"]["command"]) <= command_events.COMMAND_MAX == 200


def test_the_scrub_is_applied_to_whatever_the_caller_passes():
    assert command_events.scrub(None) == ""
    assert command_events.scrub(b"pytest -q") == "pytest -q"
    assert "hunter2hunter2" not in command_events.scrub("x --token=hunter2hunter2")
    assert len(command_events.scrub("y" * 10_000)) == command_events.COMMAND_MAX


def test_a_failing_writer_never_breaks_the_run(run_dir, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(de, "emit", boom)
    proc = _run_tracked("T1", _sleep_command(0))
    assert proc.returncode == 0 and _events(run_dir) == []


def test_a_writer_that_fails_only_on_the_finish_never_breaks_the_run(run_dir, monkeypatch):
    real = de.emit

    def flaky(run, kind, **kwargs):
        if kind == "command_finished":
            raise OSError("no space left")
        return real(run, kind, **kwargs)
    monkeypatch.setattr(de, "emit", flaky)
    proc = _run_tracked("T1", _sleep_command(0))
    assert proc.returncode == 0
    assert [e["kind"] for e in _events(run_dir)] == ["command_started"]


def test_the_kill_switch_and_a_missing_run_dir_emit_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _run_tracked("T1", _sleep_command(0))
    assert list(tmp_path.rglob("events.jsonl")) == []
    run = tmp_path / "run"
    run.mkdir()
    monkeypatch.setenv("SIMPLICIO_RUN_DIR", str(run))
    monkeypatch.setenv("SIMPLICIO_DASHBOARD_EVENTS", "0")
    _run_tracked("T1", _sleep_command(0))
    assert _events(run) == []


def test_the_command_kinds_are_part_of_the_v1_catalog_and_the_schema(run_dir):
    assert {"command_started", "command_finished"} <= set(de.LOOP_KINDS)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert {"command_started", "command_finished"} <= set(schema["properties"]["kind"]["anyOf"][0]["enum"])
    jsonschema = pytest.importorskip("jsonschema")
    _run_tracked("T1", _sleep_command(0))
    for evt in _events(run_dir):
        jsonschema.validate(evt, schema)


# --- producer -> events.jsonl -> lane_extras: the dashboard row follows the real run ----------------------------------------
def _running(run: Path) -> dict:
    return lane_extras.extras(run, de.read_events(run), now=time.time())["running_command"]


def test_the_extras_row_shows_the_command_while_it_runs_and_not_after_it_finished(run_dir):
    with command_events.track("T1", "pytest -q tests/x.py") as span:
        during = _running(run_dir)
        span.exit_code = 0
    after = _running(run_dir)
    assert during["state"] == "PASS" and "pytest -q tests/x.py" in during["reason"]
    assert [row["task_id"] for row in during["lanes"]] == ["T1"]
    assert after["lanes"] == [] and "pytest" not in after["reason"]
