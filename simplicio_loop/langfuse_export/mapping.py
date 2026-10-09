"""Loop records -> Langfuse observations and scores (issue #1595, the mapping table).

run = trace root span; task = span under it; gate = span under its task plus a BOOLEAN score;
other dashboard events = span events on their task (or the run); a generation exists only for a
task whose tokens came from a measured receipt (``tokens.source == "cli_measured"``). Anything else
is labelled ``simplicio.tokens.status = UNVERIFIED`` and never becomes a usage number.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .ids import span_id, trace_id
from .redact import export_payload

ROOT_NAME = "simplicio-loop run"
TYPE_KEY = "langfuse.observation.type"


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    start_ns: int
    end_ns: int
    attributes: dict[str, str] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class Plan:
    spans: list[Span]
    scores: list[dict[str, Any]]


def _ns(seconds: float) -> int:
    return int(seconds * 1_000_000_000)


def _ts_ns(text: Any, fallback: int) -> int:
    if not isinstance(text, str):
        return fallback
    try:
        return _ns(datetime.fromisoformat(text).timestamp())
    except ValueError:
        return fallback


def _flatten(payload: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, val in payload.items():
        name = f"payload.{key}"
        if isinstance(val, (str, int, float, bool)) or val is None:
            out[name] = str(val)
        else:
            out[name] = json.dumps(val, sort_keys=True, default=str)[:500]
    return out


def _measured(tokens: Mapping[str, Any]) -> bool:
    return tokens.get("source") == "cli_measured" and (
        tokens.get("tokens_in") is not None or tokens.get("tokens_out") is not None
    )


def _usage(tokens: Mapping[str, Any]) -> dict[str, int]:
    usage: dict[str, int] = {}
    if tokens.get("tokens_in") is not None:
        usage["input"] = int(tokens["tokens_in"])
    if tokens.get("tokens_out") is not None:
        usage["output"] = int(tokens["tokens_out"])
    return usage


def plan(
    report: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    *,
    capture_content: bool,
) -> Plan:
    run_id = str(report["run_id"])
    tid = trace_id(run_id)
    root_id = span_id(run_id, "run")
    start = _ns(float(report.get("started_at_unix") or 0))
    wall = report.get("wall_ms")
    end = (
        _ns(float(report["finished_at_unix"]))
        if report.get("finished_at_unix")
        else start + int((wall or 0) * 1_000_000)
    )
    root = Span(
        tid,
        root_id,
        None,
        ROOT_NAME,
        start,
        end,
        {
            TYPE_KEY: "span",
            "langfuse.trace.name": ROOT_NAME,
            "simplicio.run_id": run_id,
        },
    )
    spans: list[Span] = [root]
    scores: list[dict[str, Any]] = []
    tasks: dict[str, Span] = {}

    for task in report.get("tasks") or []:
        task_id = str(task["task_id"])
        t_end = start + int((task.get("wall_ms") or 0) * 1_000_000)
        attrs = {
            TYPE_KEY: "span",
            "simplicio.task_id": task_id,
            "simplicio.outcome": str(task.get("outcome") or ""),
            "simplicio.task.title": str(task.get("title") or ""),
        }
        if task.get("issue"):
            attrs["simplicio.issue"] = str(task["issue"])
        tokens = task.get("tokens") or {}
        task_span = Span(
            tid,
            span_id(run_id, "task", task_id),
            root_id,
            f"task {task_id}",
            start,
            t_end,
            attrs,
        )
        spans.append(task_span)
        tasks[task_id] = task_span
        if _measured(tokens):
            model = str((task.get("agent") or {}).get("model") or "unknown")
            spans.append(
                Span(
                    tid,
                    span_id(run_id, "generation", task_id),
                    task_span.span_id,
                    f"generation {task_id}",
                    start,
                    t_end,
                    {
                        TYPE_KEY: "generation",
                        "langfuse.observation.model.name": model,
                        "langfuse.observation.usage_details": json.dumps(
                            _usage(tokens), sort_keys=True
                        ),
                    },
                )
            )
        else:
            task_span.attributes["simplicio.tokens.status"] = "UNVERIFIED"

    for event in sorted(events, key=lambda e: int(e.get("seq") or 0)):
        ev_id = str(event.get("event_id") or event.get("seq"))
        ts = _ts_ns(event.get("ts"), start)
        payload = export_payload(event.get("payload") or {}, capture_content)
        parent = tasks.get(str(event.get("task_id") or ""), root)
        kind = str(event.get("kind") or "")
        if kind == "gate_evaluated" and isinstance(payload.get("gate"), str):
            gate = payload["gate"]
            gate_span = Span(
                tid,
                span_id(run_id, "gate", ev_id),
                parent.span_id,
                f"gate {gate}",
                ts,
                ts,
                {TYPE_KEY: "span", "simplicio.gate": gate, **_flatten(payload)},
            )
            spans.append(gate_span)
            passed = payload.get("passed")
            if isinstance(passed, bool):
                gate_span.attributes["simplicio.gate.passed"] = str(passed)
                scores.append(
                    {
                        "id": span_id(run_id, "score", ev_id),
                        "traceId": tid,
                        "observationId": gate_span.span_id,
                        "name": f"gate:{gate}",
                        "value": 1 if passed else 0,
                        "dataType": "BOOLEAN",
                        "comment": "passed" if passed else "failed",
                        "metadata": {"run_id": run_id, "gate": gate},
                    }
                )
            continue
        parent.events.append(
            {"name": kind, "time_ns": ts, "attributes": _flatten(payload)}
        )

    return Plan(spans=spans, scores=scores)
