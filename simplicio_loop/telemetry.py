"""Privacy-bounded TelemetryEvent/v1 emission and reconciliation."""
from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

SCHEMA = "simplicio.telemetry-event/v1"
REPORT_SCHEMA = "simplicio.telemetry-report/v1"
ALLOWED_LABELS = frozenset(
    {
        "stage", "status", "executor", "cache_state", "reason_code",
        "project", "component", "operation",
    }
)
LABEL_PRIORITY = (
    "project", "component", "operation", "stage", "status",
    "executor", "cache_state", "reason_code",
)
SENSITIVE_KEY = re.compile(
    r"(secret|token|password|api[_-]?key|authorization|prompt|content|email|pii|"
    r"cookie|credential|private[_-]?key|session|user[_-]?id)",
    re.IGNORECASE,
)
SENSITIVE_VALUE = re.compile(
    r"(Bearer\s+\S+|gh[pousr]_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{12,}|"
    r"AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?:https?|wss?)://[^/\s:@]+:[^@\s]+@|"
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
    re.IGNORECASE,
)
SAFE_COMPONENT = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,63})\Z")
WINDOWS_RESERVED_COMPONENTS = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
     *(f"LPT{i}" for i in range(1, 10))}
)


class TelemetryError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode()).hexdigest()


def _opaque_id(value: Any) -> str:
    return "id:" + hashlib.sha256(str(value).encode()).hexdigest()[:24]


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key):
            ("[REDACTED]" if SENSITIVE_KEY.search(str(key)) else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return SENSITIVE_VALUE.sub("[REDACTED]", value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    # Unknown objects are not serialized or repr()-ed: fail closed rather than
    # risk leaking a secret through a custom object's string representation.
    return "[REDACTED]"


def validate_component(component: Any) -> str:
    """Validate one component/path segment for the default observability path."""
    if not isinstance(component, str) or not SAFE_COMPONENT.fullmatch(component):
        raise TelemetryError("observability_component_invalid")
    if component in {".", ".."} or component[-1] in ". ":
        raise TelemetryError("observability_component_invalid")
    if component.split(".", 1)[0].upper() in WINDOWS_RESERVED_COMPONENTS:
        raise TelemetryError("observability_component_invalid")
    return component


def default_observability_path(
    component: str, *, root: str | Path | None = None
) -> Path:
    """Return the opt-in, repository-relative component event path."""
    base = Path(root) if root is not None else Path(".")
    return (
        base / ".simplicio-loop" / "observability" / validate_component(component)
        / "events.jsonl"
    )


def bounded_labels(labels: Mapping[str, Any], *, max_labels: int = 8) -> dict[str, str]:
    if max_labels < 1:
        raise TelemetryError("max_labels_must_be_positive")
    accepted: list[tuple[str, str]] = []
    dropped = 0
    priority = {key: index for index, key in enumerate(LABEL_PRIORITY)}
    for raw_key, raw_value in sorted(
        labels.items(),
        key=lambda item: (priority.get(str(item[0]), len(priority)), str(item[0])),
    ):
        key = str(raw_key)
        if key not in ALLOWED_LABELS or len(accepted) >= max_labels:
            dropped += 1
            continue
        value = str(redact(raw_value))
        accepted.append((key, value[:64] if len(value) <= 64 else _opaque_id(value)))
    if len(accepted) > max_labels:
        dropped += len(accepted) - max_labels
        accepted = accepted[:max_labels]
    if dropped:
        # Keep the cardinality marker inside the same bound. If all slots were
        # used by accepted labels, deterministically reserve one for the count.
        if len(accepted) >= max_labels:
            dropped += len(accepted) - (max_labels - 1)
            accepted = accepted[: max_labels - 1]
        accepted.append(("_dropped_label_count", str(dropped)))
    return dict(accepted)


def metric(
    value: int | float | None,
    unit: str,
    origin: str,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    if not unit or not origin:
        raise TelemetryError("metric_unit_and_origin_required")
    if value is None and not reason:
        raise TelemetryError("null_metric_reason_required")
    if value is not None and reason is not None:
        raise TelemetryError("observed_metric_cannot_have_null_reason")
    return {"value": value, "unit": unit, "origin": origin, "reason": reason}


def _rss_metric() -> dict[str, Any]:
    try:
        import resource

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports KiB; macOS reports bytes.
        if sys.platform == "darwin":
            value = int(rss)
        elif sys.platform.startswith("linux"):
            value = int(rss) * 1024
        else:
            return metric(
                None, "bytes", "resource.getrusage.ru_maxrss",
                reason="rss_unit_unavailable",
            )
        return metric(value, "bytes", "resource.getrusage.ru_maxrss")
    except (ImportError, AttributeError, OSError):
        return metric(None, "bytes", "resource.getrusage", reason="rss_unavailable")


def _io_metric(field: str) -> dict[str, Any]:
    path = Path("/proc/self/io")
    try:
        values = dict(
            line.split(":", 1) for line in path.read_text(encoding="utf-8").splitlines()
        )
        return metric(int(values[field].strip()), "bytes", f"procfs:{path}:{field}")
    except (OSError, KeyError, ValueError):
        return metric(None, "bytes", "procfs:/proc/self/io", reason="process_io_unavailable")


def resource_snapshot() -> dict[str, dict[str, Any]]:
    return {
        "cpu_process_ns": metric(
            time.process_time_ns(), "nanoseconds", "time.process_time_ns"
        ),
        "rss_peak_bytes": _rss_metric(),
        "io_read_bytes": _io_metric("read_bytes"),
        "io_write_bytes": _io_metric("write_bytes"),
        "process_count": metric(
            None, "count", "process_inventory", reason="portable_process_count_unavailable"
        ),
    }


def usage_metrics(
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_hits: int | None = None,
    cache_misses: int | None = None,
    context_bytes: int | None = None,
) -> dict[str, dict[str, Any]]:
    def optional(value: int | None, name: str, unit: str = "count"):
        return metric(
            value, unit, "provider_usage" if "token" in name else "runtime_observation",
            reason=None if value is not None else f"{name}_unavailable",
        )

    return {
        "input_tokens": optional(input_tokens, "input_tokens"),
        "output_tokens": optional(output_tokens, "output_tokens"),
        "cache_hits": optional(cache_hits, "cache_hits"),
        "cache_misses": optional(cache_misses, "cache_misses"),
        "context_bytes": optional(context_bytes, "context_bytes", "bytes"),
    }


def validate_event(event: Mapping[str, Any]) -> None:
    required = {
        "schema", "event_id", "recorded_at_ns", "correlation", "labels",
        "metrics", "payload", "previous_hash", "event_hash",
    }
    if set(event) != required or event.get("schema") != SCHEMA:
        raise TelemetryError("telemetry_event_shape_invalid")
    for name, row in event["metrics"].items():
        if not row.get("unit") or not row.get("origin"):
            raise TelemetryError(f"metric_metadata_missing:{name}")
        if row.get("value") is None and not row.get("reason"):
            raise TelemetryError(f"null_metric_reason_missing:{name}")
    body = {key: value for key, value in event.items() if key != "event_hash"}
    if _hash(body) != event["event_hash"]:
        raise TelemetryError("telemetry_event_hash_invalid")


class TelemetryWriter:
    """Hash-chained JSONL writer; every emit is crash-durable."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        component: str | None = None,
        root: str | Path | None = None,
        default_labels: Mapping[str, Any] | None = None,
        clock_ns: Callable[[], int] = time.time_ns,
        fail_open: bool = True,
    ) -> None:
        if path is None:
            if component is None:
                raise TelemetryError("telemetry_path_required")
            path = default_observability_path(component, root=root)
        self.path = Path(path)
        self.clock_ns = clock_ns
        self.fail_open = fail_open
        self.default_labels = dict(default_labels or {})
        if component is not None:
            self.default_labels.setdefault("component", component)
        self.last_error: str | None = None
        self.emission_failures = 0
        self._previous_hash = "sha256:" + "0" * 64
        self._sequence = 0
        self._ready = True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                events = load_events(self.path)
                if events:
                    self._previous_hash = events[-1]["event_hash"]
                    self._sequence = len(events)
        except Exception as exc:
            self._ready = False
            self._record_failure(exc)

    @classmethod
    def for_component(
        cls,
        component: str,
        *,
        root: str | Path | None = None,
        project: str | None = None,
        operation: str | None = None,
        default_labels: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> "TelemetryWriter":
        labels = dict(default_labels or {})
        labels["component"] = component
        if project is not None:
            labels["project"] = project
        if operation is not None:
            labels["operation"] = operation
        return cls(
            default_observability_path(component, root=root),
            default_labels=labels,
            **kwargs,
        )

    def _record_failure(self, exc: Exception) -> None:
        self.last_error = type(exc).__name__
        self.emission_failures += 1

    def _emit_failure(self, exc: Exception) -> None:
        if not self.fail_open:
            raise exc
        self._record_failure(exc)

    def emit(
        self,
        *,
        correlation: Mapping[str, Any],
        metrics: Mapping[str, Mapping[str, Any]],
        labels: Mapping[str, Any],
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        try:
            if not self._ready:
                raise OSError("telemetry_writer_unavailable")
            sequence = self._sequence + 1
            event: dict[str, Any] = {
                "schema": SCHEMA,
                "event_id": f"telemetry:{sequence}",
                "recorded_at_ns": int(self.clock_ns()),
                "correlation": {
                    key: _opaque_id(value)
                    for key, value in sorted(correlation.items())
                    if key in {
                        "run_id", "task_id", "attempt_id", "transaction_id",
                        "stage_id", "parent_event_id",
                    }
                    and value is not None
                },
                "labels": bounded_labels(
                    {**self.default_labels, **dict(labels)}
                ),
                "metrics": {str(key): dict(value) for key, value in sorted(metrics.items())},
                "payload": redact(dict(payload or {})),
                "previous_hash": self._previous_hash,
            }
            event["event_hash"] = _hash(event)
            validate_event(event)
            write_started = False
            with self.path.open("a", encoding="utf-8") as stream:
                write_started = True
                stream.write(_canonical(event) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._sequence = sequence
            self._previous_hash = event["event_hash"]
            return event
        except Exception as exc:
            if "write_started" in locals() and write_started:
                # A failed flush/fsync may have left a valid or partial line on
                # disk; do not append another event against ambiguous state.
                self._ready = False
            self._emit_failure(exc)
            return None

    @contextmanager
    def stage(
        self,
        stage_id: str,
        *,
        correlation: Mapping[str, Any],
        queue_wait_ns: int | None = None,
        retry_count: int = 0,
        cache_state: str | None = None,
        usage: Mapping[str, int | None] | None = None,
    ) -> Iterator[None]:
        wall_start, cpu_start = time.perf_counter_ns(), time.process_time_ns()
        status, reason = "passed", None
        try:
            yield
        except BaseException as exc:
            status, reason = "failed", type(exc).__name__
            raise
        finally:
            duration = time.perf_counter_ns() - wall_start
            cpu = time.process_time_ns() - cpu_start
            metrics = {
                "queue_wait_ns": metric(
                    queue_wait_ns, "nanoseconds", "scheduler",
                    reason=None if queue_wait_ns is not None else "queue_timestamp_unavailable",
                ),
                "execution_ns": metric(duration, "nanoseconds", "time.perf_counter_ns"),
                "retry_count": metric(retry_count, "count", "scheduler"),
                "cpu_stage_ns": metric(cpu, "nanoseconds", "time.process_time_ns"),
                **resource_snapshot(),
                **usage_metrics(**dict(usage or {})),
            }
            self.emit(
                correlation={**dict(correlation), "stage_id": stage_id},
                metrics=metrics,
                labels={
                    "stage": stage_id, "status": status,
                    "reason_code": reason or "ok",
                    "cache_state": cache_state or "unknown",
                },
            )


def load_events(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    events, previous = [], "sha256:" + "0" * 64
    for line in target.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        validate_event(event)
        if event["previous_hash"] != previous:
            raise TelemetryError("telemetry_chain_invalid")
        previous = event["event_hash"]
        events.append(event)
    return events


def reconcile(path: str | Path) -> dict[str, Any]:
    events = load_events(path)
    totals: dict[str, dict[str, Any]] = {}
    nulls: dict[str, dict[str, int]] = {}
    for event in events:
        for name, row in event["metrics"].items():
            if row["value"] is None:
                reasons = nulls.setdefault(name, {})
                reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
                continue
            total = totals.setdefault(
                name, {"value": 0, "unit": row["unit"], "origins": []}
            )
            if total["unit"] != row["unit"]:
                raise TelemetryError(f"metric_unit_conflict:{name}")
            total["value"] += row["value"]
            total["origins"] = sorted(set(total["origins"]) | {row["origin"]})
    report = {
        "schema": REPORT_SCHEMA,
        "event_count": len(events),
        "totals": totals,
        "null_reasons": nulls,
        "head_hash": events[-1]["event_hash"] if events else None,
        "reconciled": True,
    }
    report["report_hash"] = _hash(report)
    return report


def benchmark_overhead(
    directory: str | Path, *, iterations: int = 100, samples: int = 7
) -> dict[str, Any]:
    """Measure no-op span overhead including durable fsync."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    observed = []
    for sample in range(samples):
        start = time.perf_counter_ns()
        for _ in range(iterations):
            pass
        baseline = time.perf_counter_ns() - start
        writer = TelemetryWriter(directory / f"sample-{sample}.jsonl")
        start = time.perf_counter_ns()
        for index in range(iterations):
            with writer.stage(
                "benchmark", correlation={"run_id": f"sample-{sample}"},
                queue_wait_ns=0,
            ):
                pass
        instrumented = time.perf_counter_ns() - start
        observed.append(max(0, instrumented - baseline) / iterations)
    receipt = {
        "schema": "simplicio.telemetry-overhead/v1",
        "iterations_per_sample": iterations,
        "samples": samples,
        "overhead_ns_per_event_median": statistics.median(observed),
        "overhead_ns_per_event_min": min(observed),
        "overhead_ns_per_event_max": max(observed),
        "measurement_origin": "time.perf_counter_ns",
        "includes_flush_fsync": True,
    }
    receipt["receipt_hash"] = _hash(receipt)
    return receipt
