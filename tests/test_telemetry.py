from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop.telemetry import (
    TelemetryError, TelemetryWriter, benchmark_overhead, bounded_labels,
    default_observability_path, load_events, metric, reconcile, usage_metrics,
    validate_event,
)


def test_schema_requires_unit_origin_and_null_reason(tmp_path):
    with pytest.raises(TelemetryError, match="null_metric_reason_required"):
        metric(None, "count", "provider")
    writer = TelemetryWriter(tmp_path / "events.jsonl", clock_ns=lambda: 100)
    event = writer.emit(
        correlation={"run_id": "run-1"},
        metrics={"queue": metric(3, "milliseconds", "scheduler")},
        labels={"stage": "plan"},
    )
    assert event["metrics"]["queue"]["unit"] == "milliseconds"
    assert event["metrics"]["queue"]["origin"] == "scheduler"


def test_unavailable_usage_is_null_with_reason():
    values = usage_metrics()
    assert all(row["value"] is None and row["reason"] for row in values.values())


def test_project_component_operation_labels_are_bounded():
    labels = bounded_labels(
        {
            "project": "simplicio-loop",
            "component": "telemetry",
            "operation": "emit",
            **{f"custom_{index}": index for index in range(20)},
        },
        max_labels=5,
    )
    assert len(labels) <= 5
    assert labels["project"] == "simplicio-loop"
    assert labels["component"] == "telemetry"
    assert labels["operation"] == "emit"
    assert labels["_dropped_label_count"] == "20"


@pytest.mark.parametrize(
    "component",
    ["", ".", "..", "../escape", r"..\escape", "C:drive", "CON", "Lpt1", "trailing."],
)
def test_default_observability_path_rejects_unsafe_windows_components(tmp_path, component):
    with pytest.raises(TelemetryError, match="observability_component_invalid"):
        default_observability_path(component, root=tmp_path)


def test_component_writer_uses_opt_in_default_path_and_labels(tmp_path):
    path = default_observability_path("telemetry", root=tmp_path)
    writer = TelemetryWriter.for_component(
        "telemetry",
        root=tmp_path,
        project="simplicio-loop",
        operation="emit",
        clock_ns=lambda: 100,
    )
    event = writer.emit(
        correlation={"run_id": "run-1"},
        metrics={"count": metric(1, "count", "test")},
        labels={"stage": "plan"},
    )
    assert writer.path == path
    assert path == tmp_path / ".simplicio-loop" / "observability" / "telemetry" / "events.jsonl"
    assert event["labels"]["project"] == "simplicio-loop"
    assert event["labels"]["component"] == "telemetry"
    assert event["labels"]["operation"] == "emit"


def test_transaction_correlation_is_opaque_and_v1_compatible(tmp_path):
    path = tmp_path / "events.jsonl"
    writer = TelemetryWriter(path, clock_ns=lambda: 100)
    event = writer.emit(
        correlation={"transaction_id": "transaction-secret", "run_id": "run-1"},
        metrics={"count": metric(1, "count", "test")},
        labels={"operation": "emit"},
    )
    assert "transaction-secret" not in path.read_text()
    assert event["correlation"]["transaction_id"].startswith("id:")
    validate_event(event)


def test_redaction_and_cardinality_never_store_raw_prompt_secret_or_pii(tmp_path):
    path = tmp_path / "events.jsonl"
    writer = TelemetryWriter(path, clock_ns=lambda: 100)
    writer.emit(
        correlation={"run_id": "customer@example.com", "task_id": "secret-task"},
        metrics={"count": metric(1, "count", "test")},
        labels={
            "stage": "execute", "email": "customer@example.com",
            "user_id": "123", "executor": "x" * 100,
            **{f"custom_{i}": i for i in range(100)},
        },
        payload={
            "prompt": "raw private prompt", "api_key": "top-secret",
            "note": "Bearer abcdef", "nested": {"password": "123"},
        },
    )
    raw = path.read_text()
    assert "customer@example.com" not in raw
    assert "raw private prompt" not in raw
    assert "top-secret" not in raw
    assert "Bearer abcdef" not in raw
    event = load_events(path)[0]
    assert event["labels"]["_dropped_label_count"] == "102"
    assert event["payload"]["prompt"] == "[REDACTED]"


def test_redaction_fails_closed_for_email_and_unknown_values(tmp_path):
    path = tmp_path / "events.jsonl"
    writer = TelemetryWriter(path, clock_ns=lambda: 100)
    writer.emit(
        correlation={"run_id": "r"},
        metrics={"count": metric(1, "count", "test")},
        labels={"operation": "send"},
        payload={
            "note": "contact customer@example.com",
            "nested": {"session_id": "session-value"},
            "unknown_object": object(),
        },
    )
    raw = path.read_text()
    assert "customer@example.com" not in raw
    assert "session-value" not in raw
    assert "object at 0x" not in raw
    event = load_events(path)[0]
    assert event["payload"]["nested"]["session_id"] == "[REDACTED]"
    assert event["payload"]["unknown_object"] == "[REDACTED]"


def test_stage_records_duration_cpu_rss_and_bytes_with_reasons(tmp_path):
    path = tmp_path / "events.jsonl"
    writer = TelemetryWriter(path)
    with writer.stage("execute", correlation={"run_id": "r"}):
        pass
    metrics = load_events(path)[0]["metrics"]
    for name in (
        "execution_ns", "cpu_stage_ns", "cpu_process_ns",
        "rss_peak_bytes", "io_read_bytes", "io_write_bytes",
    ):
        assert name in metrics
        assert metrics[name]["value"] is not None or metrics[name]["reason"]


def test_emission_is_fail_open_and_does_not_raise(tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("occupied", encoding="utf-8")
    writer = TelemetryWriter(blocker / "events.jsonl")
    event = writer.emit(
        correlation={"run_id": "r"},
        metrics={"count": metric(1, "count", "test")},
        labels={"operation": "emit"},
    )
    assert event is None
    assert writer.emission_failures >= 1
    assert writer.last_error in {"OSError", "FileNotFoundError", "NotADirectoryError"}


def test_stage_tracing_preserves_return_and_exception_semantics(tmp_path):
    writer = TelemetryWriter(tmp_path / "events.jsonl")
    result = []
    with writer.stage("execute", correlation={"run_id": "r"}, queue_wait_ns=2):
        result.append("same")
    assert result == ["same"]
    with pytest.raises(RuntimeError, match="boom"):
        with writer.stage("execute", correlation={"run_id": "r"}):
            raise RuntimeError("boom")
    events = load_events(tmp_path / "events.jsonl")
    assert [event["labels"]["status"] for event in events] == ["passed", "failed"]


def test_totals_reconcile_events_and_null_reasons(tmp_path):
    path = tmp_path / "events.jsonl"
    writer = TelemetryWriter(path, clock_ns=iter([1, 2]).__next__)
    for value in (2, 3):
        writer.emit(
            correlation={"run_id": "r"},
            metrics={
                "jobs": metric(value, "count", "scheduler"),
                "tokens": metric(
                    None, "count", "provider_usage", reason="provider_usage_unavailable"
                ),
            },
            labels={"stage": "execute"},
        )
    report = reconcile(path)
    assert report["event_count"] == 2
    assert report["totals"]["jobs"]["value"] == 5
    assert report["null_reasons"]["tokens"] == {
        "provider_usage_unavailable": 2
    }


def test_crash_flush_survives_os_exit(tmp_path):
    path = tmp_path / "crash.jsonl"
    script = (
        "import os;"
        "from simplicio_loop.telemetry import TelemetryWriter,metric;"
        f"w=TelemetryWriter({str(path)!r});"
        "w.emit(correlation={'run_id':'r'},metrics={'x':metric(1,'count','test')},labels={'stage':'x'});"
        "os._exit(17)"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).parents[1])
    result = subprocess.run([sys.executable, "-c", script], env=env)
    assert result.returncode == 17
    assert load_events(path)[0]["metrics"]["x"]["value"] == 1


def test_hash_chain_tamper_fails_reconciliation(tmp_path):
    path = tmp_path / "events.jsonl"
    writer = TelemetryWriter(path, clock_ns=lambda: 1)
    writer.emit(
        correlation={"run_id": "r"}, metrics={"x": metric(1, "count", "test")},
        labels={"stage": "x"},
    )
    raw = json.loads(path.read_text())
    raw["metrics"]["x"]["value"] = 99
    path.write_text(json.dumps(raw) + "\n")
    with pytest.raises(TelemetryError, match="hash"):
        reconcile(path)


def test_overhead_is_measured_not_estimated(tmp_path):
    receipt = benchmark_overhead(tmp_path / "benchmark", iterations=10, samples=3)
    assert receipt["samples"] == 3
    assert receipt["iterations_per_sample"] == 10
    assert receipt["overhead_ns_per_event_median"] >= 0
    assert receipt["measurement_origin"] == "time.perf_counter_ns"
    assert receipt["includes_flush_fsync"] is True


def test_event_fixture_is_reproducible(tmp_path):
    writer = TelemetryWriter(tmp_path / "events.jsonl", clock_ns=lambda: 100)
    event = writer.emit(
        correlation={
            "run_id": "run-fixture", "task_id": "task-fixture",
            "stage_id": "plan",
        },
        metrics={
            "queue_wait_ns": metric(
                None, "nanoseconds", "scheduler",
                reason="queue_timestamp_unavailable",
            ),
            "retry_count": metric(0, "count", "scheduler"),
        },
        labels={"stage": "plan", "status": "passed"},
        payload={"prompt": "must redact", "note": "ok"},
    )
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "telemetry_event.json").read_text()
    )
    assert event == fixture


def test_existing_fixture_remains_v1_compatible():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "telemetry_event.json").read_text()
    )
    validate_event(fixture)
