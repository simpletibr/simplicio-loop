"""Tests for observability.py's canonical estimator + savings-event ledger
producer (issue #88 AC3/AC4), the central output/logging layer that
separates stdout (machine data) from stderr (human status) (issue #106),
and the structured event stream a host loop's journal can consume
(issue #107)."""

import io
import json
import logging

import pytest

from simplicio import observability as obs
from simplicio.observability import (
    EVENT_SCHEMA,
    EVENT_TYPES,
    SAVINGS_EVENT_SCHEMA,
    emit_data,
    emit_event,
    error,
    estimate_token_details,
    estimate_tokens,
    events_summary,
    info,
    native_delegation_summary,
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


def test_estimate_token_details_uses_tiktoken_for_unknown_model(monkeypatch):
    """The BPE encoding lookup (tiktoken.get_encoding) is an external network
    dependency the first time a given encoding's data file is not already
    cached -- it must not be exercised for real here (this test has to pass
    hermetically, e.g. under scripts/check.py's network-stripped gate
    subprocess). We monkeypatch tiktoken's encoding getters with a small
    deterministic fake so the test proves the documented behavior of
    estimate_token_details (unknown model -> o200k_base fallback, source
    "tiktoken") without ever touching the network."""
    monkeypatch.setenv("SIMPLICIO_MODEL", "provider/unknown-model")
    text = "Olá 👋\\nconst value = { key: 1 };"

    import tiktoken

    class _FakeEncoding:
        name = "o200k_base"

        def encode(self, text, disallowed_special=()):
            return list(text.encode("utf-8"))

    def _fake_encoding_for_model(model):
        # Unknown model: mirrors tiktoken's real behavior of raising KeyError
        # so estimate_token_details falls through to get_encoding().
        raise KeyError(model)

    def _fake_get_encoding(name):
        assert name == "o200k_base"
        return _FakeEncoding()

    monkeypatch.setattr(tiktoken, "encoding_for_model", _fake_encoding_for_model)
    monkeypatch.setattr(tiktoken, "get_encoding", _fake_get_encoding)

    details = estimate_token_details(text)
    assert details["source"] == "tiktoken"
    assert details["encoding"] == "o200k_base"
    assert details["tokens"] == len(text.encode("utf-8"))
    assert details["tokens"] == estimate_tokens(text)


def test_estimate_token_details_fails_open_when_tokenizer_fails(monkeypatch):
    monkeypatch.setattr(obs, "_heuristic_token_count", lambda _: 7)
    monkeypatch.setitem(__import__("sys").modules, "tiktoken", None)
    details = estimate_token_details("fallback text")
    assert details["tokens"] == 7
    assert details["source"] == "heuristic-fallback"


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
# proof_kind (issue #111)
# --------------------------------------------------------------------------- #


def test_record_savings_event_defaults_to_estimated_proof_kind(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    out = record_savings_event(tmp_path, source="toon", baseline_tokens=10, actual_tokens=5)
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
    assert lines[0]["proof_kind"] == "estimated"


def test_record_savings_event_accepts_measured_proof_kind(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    out = record_savings_event(
        tmp_path, source="toon", baseline_tokens=10, actual_tokens=5, proof_kind="measured"
    )
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
    assert lines[0]["proof_kind"] == "measured"


def test_record_savings_event_rejects_unknown_proof_kind(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    with pytest.raises(ValueError, match="proof_kind"):
        record_savings_event(tmp_path, source="toon", baseline_tokens=10, actual_tokens=5, proof_kind="vibes")


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


def test_configure_logging_rebinds_stderr_when_previous_stream_is_broken(monkeypatch):
    class BrokenStream:
        def write(self, _: str) -> int:
            raise OSError(6, "The handle is invalid")

        def flush(self) -> None:
            raise OSError(6, "The handle is invalid")

    handler = logging.StreamHandler(stream=BrokenStream())
    handler._simplicio_stderr_handler = True
    handler.setFormatter(logging.Formatter("%(message)s"))
    obs._logger.addHandler(handler)
    obs._configured = True

    buf = io.StringIO()
    monkeypatch.setattr(obs.sys, "stderr", buf)
    monkeypatch.delenv("SIMPLICIO_LOG_LEVEL", raising=False)

    obs.configure_logging()
    info("stderr rebound")

    assert "stderr rebound" in buf.getvalue()


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


# --------------------------------------------------------------------------- #
# Structured event stream for a host loop's journal (#107)
# --------------------------------------------------------------------------- #


def test_emit_event_writes_stderr_line_and_never_stdout(tmp_path, monkeypatch):
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    monkeypatch.setattr(obs.sys, "stdout", stdout_buf)
    monkeypatch.setattr(obs.sys, "stderr", stderr_buf)
    monkeypatch.delenv("SIMPLICIO_LOG_LEVEL", raising=False)
    obs.configure_logging()

    emit_event("task_start", {"target": "x.py"}, root=str(tmp_path))

    assert stdout_buf.getvalue() == ""
    assert "task_start" in stderr_buf.getvalue()


def test_emit_event_appends_jsonl_with_documented_schema(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    record = emit_event(
        "edit_applied",
        {"tool": "dev_cli_edit"},
        root=str(tmp_path),
        tokens_saved=42,
    )

    assert record["schema"] == EVENT_SCHEMA
    assert record["event"] == "edit_applied"
    assert record["level"] == "info"
    assert record["payload"] == {"tool": "dev_cli_edit"}
    assert record["tokens_saved"] == 42
    assert "ts" in record

    out = tmp_path / ".simplicio" / "events.jsonl"
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 1
    assert lines[0] == record


def test_emit_event_without_root_only_logs_no_file_write(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    emit_event("handoff", {"tool": "dev_cli_memory"})
    assert not (tmp_path / ".simplicio" / "events.jsonl").exists()


def test_emit_event_disabled_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DISABLE_RUN_LOG", "1")
    emit_event("task_start", {}, root=str(tmp_path))
    assert not (tmp_path / ".simplicio").exists()


def test_emit_event_appends_multiple_events(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    emit_event("task_start", {"n": 1}, root=str(tmp_path))
    emit_event("task_complete", {"n": 2}, root=str(tmp_path))
    out = tmp_path / ".simplicio" / "events.jsonl"
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
    assert [x["event"] for x in lines] == ["task_start", "task_complete"]


def test_events_summary_missing_file(tmp_path):
    summary = events_summary(str(tmp_path))
    assert summary["exists"] is False
    assert summary["count"] == 0
    assert summary["recent"] == []


def test_events_summary_reports_count_and_recent(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    for i in range(7):
        emit_event("task_start", {"n": i}, root=str(tmp_path))

    summary = events_summary(str(tmp_path), limit=3)
    assert summary["exists"] is True
    assert summary["count"] == 7
    assert len(summary["recent"]) == 3
    assert summary["recent"][-1]["payload"]["n"] == 6


def test_events_summary_tolerates_corrupt_trailing_line(tmp_path):
    events_dir = tmp_path / ".simplicio"
    events_dir.mkdir()
    (events_dir / "events.jsonl").write_text(
        '{"schema": "simplicio.dev-cli-event/v1", "event": "task_start", "payload": {}}\nnot json\n',
        encoding="utf-8",
    )
    summary = events_summary(str(tmp_path))
    assert summary["count"] == 1


def test_emit_event_rotates_large_jsonl(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    monkeypatch.setenv("SIMPLICIO_EVENTS_MAX_BYTES", "100")
    events_dir = tmp_path / ".simplicio"
    events_dir.mkdir()
    (events_dir / "events.jsonl").write_text("x" * 101, encoding="utf-8")

    emit_event("task_start", {"n": 1}, root=str(tmp_path))

    assert (events_dir / "events.jsonl.1").exists()
    summary = events_summary(str(tmp_path))
    assert summary["count"] == 1


def test_events_summary_streams_large_file_and_skips_corrupt_lines(tmp_path):
    events_dir = tmp_path / ".simplicio"
    events_dir.mkdir()
    out = events_dir / "events.jsonl"
    with out.open("w", encoding="utf-8") as handle:
        for i in range(200):
            handle.write(
                json.dumps({"schema": EVENT_SCHEMA, "event": "task_start", "payload": {"n": i}}) + "\n"
            )
        handle.write("not-json\n")

    summary = events_summary(str(tmp_path), limit=2)

    assert summary["count"] == 200
    assert [row["payload"]["n"] for row in summary["recent"]] == [198, 199]


# --------------------------------------------------------------------------- #
# native_delegation_summary (issue #111)
# --------------------------------------------------------------------------- #


def test_native_delegation_summary_missing_file(tmp_path):
    summary = native_delegation_summary(str(tmp_path))
    assert summary["exists"] is False
    assert summary["total"] == 0
    assert summary["native_pct"] == 0.0
    assert summary["verbs"] == {}


def test_native_delegation_summary_aggregates_per_verb_and_overall(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    root = str(tmp_path)
    emit_event("native_delegation", {"verb": "gate", "route": "native"}, root=root)
    emit_event("native_delegation", {"verb": "gate", "route": "native"}, root=root)
    emit_event("native_delegation", {"verb": "gate", "route": "python-fallback", "reason": "x"}, root=root)
    emit_event("native_delegation", {"verb": "edit", "route": "python-forced", "reason": "y"}, root=root)
    # Non-delegation events in the same stream must be ignored.
    emit_event("task_start", {"target": "x.py"}, root=root)

    summary = native_delegation_summary(root)

    assert summary["exists"] is True
    assert summary["total"] == 4
    assert summary["native_pct"] == 50.0
    assert summary["verbs"]["gate"] == {
        "native": 2,
        "python-fallback": 1,
        "total": 3,
        "native_pct": round(100 * 2 / 3, 1),
    }
    assert summary["verbs"]["edit"] == {"python-forced": 1, "total": 1, "native_pct": 0.0}


def test_native_delegation_summary_tolerates_corrupt_trailing_line(tmp_path):
    events_dir = tmp_path / ".simplicio"
    events_dir.mkdir()
    (events_dir / "events.jsonl").write_text(
        json.dumps(
            {
                "schema": EVENT_SCHEMA,
                "event": "native_delegation",
                "payload": {"verb": "file", "route": "native"},
            }
        )
        + "\nnot json\n",
        encoding="utf-8",
    )
    summary = native_delegation_summary(str(tmp_path))
    assert summary["total"] == 1
    assert summary["verbs"]["file"]["native"] == 1


def test_native_delegation_is_a_documented_event_type():
    assert "native_delegation" in EVENT_TYPES
