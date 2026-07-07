"""Tests for observability.py's canonical estimator + savings-event ledger
producer (issue #88 AC3/AC4), and the central output/logging layer that
separates stdout (machine data) from stderr (human status), issue #106."""

import io
import json
import logging

import pytest

from simplicio import observability as obs
from simplicio.observability import (
    SAVINGS_EVENT_SCHEMA,
    emit_data,
    error,
    estimate_tokens,
    info,
    record_savings_event,
    warn,
)


@pytest.fixture(autouse=True)
def _reset_logging_state():
    """Isolate each test from the module-level logger singleton.

    `configure_logging` deliberately only attaches a handler once (so
    repeated CLI-internal calls don't duplicate output); tests need a clean
    slate each time to assert on a specific stream.
    """
    obs._configured = False
    obs._logger.handlers.clear()
    obs._logger.setLevel(logging.NOTSET)
    yield
    obs._configured = False
    obs._logger.handlers.clear()
    obs._logger.setLevel(logging.NOTSET)


def test_estimate_tokens_empty_is_zero():
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0


def test_estimate_tokens_positive_for_text():
    assert estimate_tokens("hello world this is a prompt") > 0


def test_record_savings_event_writes_ledger(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    out = record_savings_event(
        tmp_path,
        source="toon",
        baseline_tokens=100,
        actual_tokens=60,
        note="test block",
    )
    assert out is not None
    assert out == tmp_path / ".simplicio" / "ledger" / "savings-events.jsonl"
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 1
    event = lines[0]
    assert event["schema"] == SAVINGS_EVENT_SCHEMA
    assert event["source"] == "toon"
    assert event["tokens"]["baseline"] == 100
    assert event["tokens"]["actual"] == 60
    assert event["tokens"]["saved"] == 40
    assert event["tokens"]["pct_saved"] == 40.0
    assert event["note"] == "test block"
    assert "estimator" in event


def test_record_savings_event_appends(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    record_savings_event(tmp_path, source="toon", baseline_tokens=10, actual_tokens=5)
    record_savings_event(tmp_path, source="autoresearch", baseline_tokens=20, actual_tokens=18)
    out = tmp_path / ".simplicio" / "ledger" / "savings-events.jsonl"
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 2
    assert {e["source"] for e in lines} == {"toon", "autoresearch"}


def test_record_savings_event_disabled_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DISABLE_RUN_LOG", "1")
    out = record_savings_event(tmp_path, source="toon", baseline_tokens=10, actual_tokens=5)
    assert out is None
    assert not (tmp_path / ".simplicio" / "ledger").exists()


def test_record_savings_event_zero_baseline_no_division_error(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    out = record_savings_event(tmp_path, source="toon", baseline_tokens=0, actual_tokens=0)
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
    assert lines[0]["tokens"]["pct_saved"] == 0.0


# --------------------------------------------------------------------------- #
# Output / logging separation (#106)
# --------------------------------------------------------------------------- #


def test_emit_data_writes_json_to_stdout():
    buf = io.StringIO()
    emit_data({"a": 1}, stream=buf)
    assert json.loads(buf.getvalue()) == {"a": 1}
    assert buf.getvalue().endswith("\n")


def test_emit_data_writes_str_verbatim_to_stdout():
    buf = io.StringIO()
    emit_data("already-a-string", stream=buf)
    assert buf.getvalue() == "already-a-string\n"


def test_configure_logging_default_shows_info(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(obs.sys, "stderr", buf)
    monkeypatch.delenv("SIMPLICIO_LOG_LEVEL", raising=False)
    obs.configure_logging()
    info("hello info")
    warn("hello warn")
    error("hello error")
    out = buf.getvalue()
    assert "hello info" in out
    assert "hello warn" in out
    assert "hello error" in out


def test_configure_logging_quiet_suppresses_info_not_warn_or_error(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(obs.sys, "stderr", buf)
    monkeypatch.delenv("SIMPLICIO_LOG_LEVEL", raising=False)
    obs.configure_logging(quiet=True)
    info("suppressed info")
    warn("visible warn")
    error("visible error")
    out = buf.getvalue()
    assert "suppressed info" not in out
    assert "visible warn" in out
    assert "visible error" in out


def test_configure_logging_verbose_enables_debug(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_LOG_LEVEL", raising=False)
    obs.configure_logging(verbose=True)
    assert obs.get_logger().getEffectiveLevel() == logging.DEBUG


def test_configure_logging_respects_simplicio_log_level_env(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOG_LEVEL", "ERROR")
    obs.configure_logging()
    assert obs.get_logger().getEffectiveLevel() == logging.ERROR


def test_configure_logging_explicit_args_win_over_env(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOG_LEVEL", "ERROR")
    obs.configure_logging(verbose=True)
    assert obs.get_logger().getEffectiveLevel() == logging.DEBUG


def test_configure_logging_does_not_duplicate_handlers(monkeypatch):
    # Handler count is compared as a delta rather than an absolute 1: a test
    # runner's own logging plugin (e.g. pytest's live-log capture) may attach
    # its own handler(s) to any non-propagating logger it discovers, which
    # is orthogonal to what `configure_logging` itself is responsible for.
    monkeypatch.delenv("SIMPLICIO_LOG_LEVEL", raising=False)
    obs.configure_logging()
    after_first = len(obs.get_logger().handlers)
    obs.configure_logging()
    obs.configure_logging(verbose=True)
    assert len(obs.get_logger().handlers) == after_first


def test_info_warn_error_never_write_to_stdout(monkeypatch):
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    monkeypatch.setattr(obs.sys, "stdout", stdout_buf)
    monkeypatch.setattr(obs.sys, "stderr", stderr_buf)
    monkeypatch.delenv("SIMPLICIO_LOG_LEVEL", raising=False)
    obs.configure_logging()
    info("info goes to stderr only")
    warn("warn goes to stderr only")
    error("error goes to stderr only")
    assert stdout_buf.getvalue() == ""
    assert "info goes to stderr only" in stderr_buf.getvalue()
