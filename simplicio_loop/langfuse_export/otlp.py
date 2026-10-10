"""OTLP/HTTP JSON encoding of planned spans, for Langfuse's ``/api/public/otel/v1/traces``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

SCOPE = "simplicio_loop.langfuse_export"


def _kv(key: str, value: str) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": value}}


def _span(span: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "traceId": span["trace_id"],
        "spanId": span["span_id"],
        "name": span["name"],
        "kind": 1,  # SPAN_KIND_INTERNAL
        "startTimeUnixNano": str(span["start_ns"]),
        "endTimeUnixNano": str(span["end_ns"]),
        "attributes": [_kv(k, str(v)) for k, v in span["attributes"].items()],
        "events": [
            {
                "name": ev["name"],
                "timeUnixNano": str(ev["time_ns"]),
                "attributes": [_kv(k, str(v)) for k, v in ev["attributes"].items()],
            }
            for ev in span.get("events") or []
        ],
        "status": {"code": 1},  # STATUS_CODE_OK
    }
    if span.get("parent_id"):
        out["parentSpanId"] = span["parent_id"]
    return out


def encode(spans: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """One resource, one scope, every span: the body of one OTLP/HTTP JSON export request."""
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_kv("service.name", "simplicio-loop")]},
                "scopeSpans": [
                    {"scope": {"name": SCOPE}, "spans": [_span(s) for s in spans]}
                ],
            }
        ]
    }
