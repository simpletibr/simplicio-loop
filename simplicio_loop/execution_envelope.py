"""Pure, fail-closed universal execution envelope.

``simplicio.loop-execution/v1`` is the published verified-success receipt for the
original Loop chain.  Its result is intentionally too narrow for intermediate
and governor outcomes.  This module owns the explicit successor used by every
execution transport (run, tick, batch, single-task-fast, wave, and Prism).

The module does not execute providers, read files, create timestamps, or mutate
inputs.  It only canonicalizes supplied observations and validates the resulting
JSON-shaped value.  Missing observations remain ``None`` or ``provider_called:
false``; they are never turned into a successful result.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from .execution_report import SCHEMA as EXECUTION_REPORT_SCHEMA

SCHEMA = "simplicio.loop-execution/v2"
V1_SCHEMA = "simplicio.loop-execution/v1"

EXECUTION_FLOWS = frozenset(
    {"run", "tick", "batch", "single-task-fast", "wave", "prism"}
)
EXECUTION_STATUSES = frozenset(
    {"complete", "partial", "blocked", "error", "expected_governor_blocked"}
)
PHASES = ("mapper", "fast", "dev_cli", "loop")
PHASE_STATUSES = frozenset(
    {"not_run", "running", "complete", "partial", "blocked", "error"}
)
TASK_STATUSES = frozenset(
    {"queued", "running", "complete", "partial", "blocked", "error", "cancelled"}
)
METRIC_NAMES = (
    "wall_ms",
    "latency_ms",
    "cpu_percent",
    "ram_mb",
    "tokens_in",
    "tokens_out",
    "tokens_total",
    "items_per_hour",
)

_SENSITIVE_KEY_NAMES = frozenset(
    {
        "credential",
        "credentials",
        "token",
        "secret",
        "secrets",
        "apikey",
        "api_key",
        "access_token",
        "refresh_token",
        "auth_token",
        "password",
        "private_key",
        "authorization",
        "bearer",
    }
)


class EnvelopeValidationError(ValueError):
    """Raised when an envelope cannot be trusted as an execution observation."""


def _error(message: str) -> None:
    raise EnvelopeValidationError(message)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _error(f"{field} must be a non-empty string")
    return value.strip()


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise EnvelopeValidationError(f"payload is not canonical JSON: {exc}") from exc


def _contains_sensitive_key(value: Any, path: str = "payload") -> str | None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            if not isinstance(raw_key, str):
                return f"{path} contains a non-string object key"
            normalized = raw_key.strip().lower().replace("-", "_")
            if (
                normalized in _SENSITIVE_KEY_NAMES
                or normalized.endswith("_secret")
                or normalized.endswith("_credential")
                or normalized.endswith("_api_key")
                or normalized.endswith("_access_token")
                or normalized.endswith("_refresh_token")
                or normalized.endswith("_password")
                or normalized.endswith("_private_key")
                or normalized.startswith("auth_")
            ):
                return f"sensitive field {path}.{raw_key} is forbidden"
            found = _contains_sensitive_key(child, f"{path}.{raw_key}")
            if found:
                return found
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            found = _contains_sensitive_key(child, f"{path}[{index}]")
            if found:
                return found
    return None


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _error(f"{field} must be an object")
    return value


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        _error(f"{field} must be an array")
    return value


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        _error(f"{field} must be boolean")
    return value


def _metric(value: Any, field: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _error(f"metrics.{field} must be an observed number or null")
    if not math.isfinite(float(value)) or float(value) < 0:
        _error(f"metrics.{field} must be a finite non-negative observed number or null")


def _validate_evidence(value: Any, field: str, *, required: bool) -> None:
    items = _list(value, field)
    if required and not items:
        _error(f"{field} is required for completion evidence")
    for index, item in enumerate(items):
        if isinstance(item, str):
            if not item.strip():
                _error(f"{field}[{index}] must not be empty")
            continue
        evidence = _mapping(item, f"{field}[{index}]")
        _text(evidence.get("ref"), f"{field}[{index}].ref")
        _text(evidence.get("kind"), f"{field}[{index}].kind")


def _validate_tasks(tasks: Any, task_order: Any) -> None:
    rows = _list(tasks, "tasks")
    if not rows:
        _error("tasks must contain at least one task")
    order = _list(task_order, "task_order")
    if len(order) != len(rows):
        _error("task_order must contain every task exactly once")

    ids: list[str] = []
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, raw_task in enumerate(rows):
        task = _mapping(raw_task, f"tasks[{index}]")
        task_id = _text(task.get("task_id"), f"tasks[{index}].task_id")
        if task_id in by_id:
            _error(f"duplicate task_id: {task_id}")
        by_id[task_id] = task
        ids.append(task_id)
        raw_order = task.get("order")
        if isinstance(raw_order, bool) or not isinstance(raw_order, int) or raw_order != index:
            _error(f"tasks[{index}].order must equal canonical order {index}")
        status = str(task.get("status") or "").strip().lower()
        if status not in TASK_STATUSES:
            _error(f"tasks[{index}].status is unsupported: {status!r}")
        dependencies = _list(task.get("depends_on"), f"tasks[{index}].depends_on")
        seen_dependencies: set[str] = set()
        for dependency in dependencies:
            dependency_id = _text(dependency, f"tasks[{index}].depends_on item")
            if dependency_id in seen_dependencies:
                _error(f"duplicate dependency {dependency_id} for task {task_id}")
            seen_dependencies.add(dependency_id)
        _validate_evidence(task.get("evidence"), f"tasks[{index}].evidence", required=False)

    if order != ids or len(set(order)) != len(order):
        _error("task_order must match the ordered unique task_id list")

    graph: dict[str, list[str]] = {}
    for task_id, task in by_id.items():
        dependencies = [str(item).strip() for item in task["depends_on"]]
        unknown = [item for item in dependencies if item not in by_id]
        if unknown:
            _error(f"unknown dependency {unknown[0]} for task {task_id}")
        graph[task_id] = dependencies

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            _error(f"dependency cycle detected at task {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in graph[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in ids:
        visit(task_id)

    positions = {task_id: index for index, task_id in enumerate(ids)}
    for task_id, dependencies in graph.items():
        if any(positions[dependency] >= positions[task_id] for dependency in dependencies):
            _error(f"dependency order must precede task {task_id}")


def _validate_phases(phases: Any) -> None:
    phase_map = _mapping(phases, "phases")
    if set(phase_map) != set(PHASES):
        _error(f"phases must contain exactly {list(PHASES)}")
    for phase in PHASES:
        item = _mapping(phase_map[phase], f"phases.{phase}")
        status = str(item.get("status") or "").strip().lower()
        if status not in PHASE_STATUSES:
            _error(f"phases.{phase}.status is unsupported: {status!r}")
        called = _bool(item.get("provider_called"), f"phases.{phase}.provider_called")
        receipt = item.get("receipt")
        if called and (not isinstance(receipt, Mapping) or not receipt):
            _error(f"phases.{phase}.provider_called=true requires a receipt")
        if not called and receipt is not None:
            _error(f"phases.{phase}.receipt requires provider_called=true")
        if status == "not_run" and (called or receipt is not None):
            _error(f"phases.{phase}.not_run cannot have provider_called or receipt")
        _validate_evidence(item.get("evidence"), f"phases.{phase}.evidence", required=False)


def _validate_report(report: Any, run_id: str) -> None:
    value = _mapping(report, "execution_report")
    if value.get("schema") != EXECUTION_REPORT_SCHEMA:
        _error("execution_report must use simplicio.execution-report/v1")
    report_run_id = _text(value.get("run_id"), "execution_report.run_id")
    if report_run_id != run_id:
        _error("execution_report.run_id must match run_id")
    tasks = value.get("tasks")
    if tasks is not None and not isinstance(tasks, list):
        _error("execution_report.tasks must be an array")
    consolidated = value.get("consolidated")
    if consolidated is not None and not isinstance(consolidated, Mapping):
        _error("execution_report.consolidated must be an object")


def validate_execution_envelope(envelope: Mapping[str, Any]) -> bool:
    """Validate one v2 envelope, raising on every unverifiable condition.

    Returning ``True`` on success makes the function convenient for gates while
    the exception carries the fail-closed reason for callers and receipts.
    """
    value = _mapping(envelope, "envelope")
    sensitive = _contains_sensitive_key(value)
    if sensitive:
        _error(sensitive)

    required = {
        "schema",
        "contract_version",
        "envelope_id",
        "run_id",
        "flow",
        "status",
        "tasks",
        "task_order",
        "phases",
        "evidence",
        "metrics",
        "execution_report",
        "completion",
    }
    missing = sorted(required - set(value))
    if missing:
        _error(f"missing required field(s): {', '.join(missing)}")
    if value.get("schema") != SCHEMA or value.get("contract_version") != "v2":
        _error(f"schema must be {SCHEMA}")
    allowed = required | {"reason_code", "governor"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        _error(f"unknown envelope field(s): {', '.join(unknown)}")
    envelope_id = _text(value.get("envelope_id"), "envelope_id")
    if "/" in envelope_id or "\\" in envelope_id:
        _error("envelope_id must be a portable identifier")
    run_id = _text(value.get("run_id"), "run_id")
    flow = value.get("flow")
    if not isinstance(flow, str) or flow not in EXECUTION_FLOWS:
        _error(f"flow is unsupported: {flow!r}")
    status = value.get("status")
    if not isinstance(status, str) or status not in EXECUTION_STATUSES:
        _error(f"status is unsupported: {status!r}")

    _validate_tasks(value["tasks"], value["task_order"])
    _validate_phases(value["phases"])
    _validate_evidence(value["evidence"], "evidence", required=status == "complete")
    metrics = _mapping(value["metrics"], "metrics")
    unknown_metrics = sorted(set(metrics) - set(METRIC_NAMES))
    if unknown_metrics:
        _error(f"unknown metric field(s): {', '.join(unknown_metrics)}")
    for name in METRIC_NAMES:
        if name in metrics:
            _metric(metrics[name], name)
    _validate_report(value["execution_report"], run_id)

    completion = _mapping(value["completion"], "completion")
    verified = _bool(completion.get("verified"), "completion.verified")
    _text(completion.get("oracle"), "completion.oracle")
    if status == "complete":
        if verified is not True or completion.get("oracle") != "MEASURED":
            _error("completion requires verified=true and oracle=MEASURED")
        if any(task["status"] != "complete" for task in value["tasks"]):
            _error("complete envelope contains incomplete task")
        if any(value["phases"][phase]["status"] != "complete" for phase in PHASES):
            _error("complete envelope contains an incomplete phase")
    elif verified:
        _error("non-complete envelope cannot claim completion.verified=true")

    if status == "partial":
        task_partial = any(task["status"] != "complete" for task in value["tasks"])
        phase_partial = any(value["phases"][phase]["status"] != "complete" for phase in PHASES)
        if not (task_partial or phase_partial):
            _error("partial envelope must identify incomplete work")

    if status in {"blocked", "error", "expected_governor_blocked"}:
        _text(value.get("reason_code"), "reason_code")

    if status == "expected_governor_blocked":
        governor = _mapping(value.get("governor"), "governor")
        if governor.get("decision") != "blocked" or governor.get("expected") is not True:
            _error("expected_governor_blocked requires expected blocked governor decision")
        _text(governor.get("reason_code"), "governor.reason_code")
        if any(value["phases"][phase]["provider_called"] for phase in PHASES):
            _error("expected_governor_blocked cannot call a provider")

    return True


def _normalize_task(raw_task: Any, index: int) -> dict[str, Any]:
    task = dict(_mapping(raw_task, f"tasks[{index}]"))
    if "task_id" not in task and "id" in task:
        task["task_id"] = task.pop("id")
    task.setdefault("order", index)
    task.setdefault("depends_on", [])
    task.setdefault("evidence", [])
    return task


def _normalize_phase(raw_phase: Any, phase: str) -> dict[str, Any]:
    phase_value = dict(_mapping(raw_phase, f"phases.{phase}"))
    phase_value.setdefault("evidence", [])
    phase_value.setdefault("receipt", None)
    phase_value.setdefault("provider_called", False)
    phase_value.setdefault("status", "not_run")
    return phase_value


def _report_metrics(report: Mapping[str, Any]) -> dict[str, Any]:
    consolidated = report.get("consolidated")
    consolidated = consolidated if isinstance(consolidated, Mapping) else {}
    return {
        "wall_ms": report.get("wall_ms"),
        "latency_ms": None,
        "cpu_percent": None,
        "ram_mb": consolidated.get("ram_mb_peak"),
        "tokens_in": consolidated.get("tokens_in_sum"),
        "tokens_out": consolidated.get("tokens_out_sum"),
        "tokens_total": consolidated.get("tokens_total_sum"),
        "items_per_hour": consolidated.get("speed_items_per_hour"),
    }


def build_execution_envelope(
    *,
    run_id: str,
    flow: str,
    tasks: Sequence[Mapping[str, Any]],
    phases: Mapping[str, Mapping[str, Any]],
    status: str,
    evidence: Sequence[Any],
    execution_report: Mapping[str, Any],
    completion: Mapping[str, Any],
    metrics: Mapping[str, Any] | None = None,
    envelope_id: str | None = None,
    reason_code: str | None = None,
    governor: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and validate a deterministic v2 envelope without side effects."""
    if isinstance(tasks, (str, bytes, bytearray)) or not isinstance(tasks, Sequence):
        _error("tasks must be an array")
    if isinstance(evidence, (str, bytes, bytearray)) or not isinstance(evidence, Sequence):
        _error("evidence must be an array")
    report = {
        key: copy.deepcopy(item)
        for key, item in _mapping(execution_report, "execution_report").items()
        if not str(key).startswith("_")
    }
    normalized_metrics = _report_metrics(report)
    if metrics is not None:
        normalized_metrics.update(copy.deepcopy(dict(_mapping(metrics, "metrics"))))
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "contract_version": "v2",
        "run_id": _text(run_id, "run_id"),
        "flow": flow,
        "status": status,
        "tasks": [_normalize_task(task, index) for index, task in enumerate(tasks)],
        "task_order": [],
        "phases": {
            phase: _normalize_phase(phases.get(phase), phase) for phase in PHASES
        },
        "evidence": copy.deepcopy(list(evidence)),
        "metrics": normalized_metrics,
        "execution_report": report,
        "completion": copy.deepcopy(dict(_mapping(completion, "completion"))),
    }
    payload["task_order"] = [task.get("task_id") for task in payload["tasks"]]
    if reason_code is not None:
        payload["reason_code"] = reason_code
    if governor is not None:
        payload["governor"] = copy.deepcopy(dict(_mapping(governor, "governor")))
    if envelope_id is None:
        envelope_id = "env-" + hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:24]
    payload["envelope_id"] = envelope_id
    validate_execution_envelope(payload)
    return payload


def is_v1_receipt_compatible(value: Mapping[str, Any]) -> bool:
    """Return whether *value* has the legacy v1 receipt identity and success shape.

    This is an explicit compatibility predicate, not a fallback validator.  A
    v1 receipt remains readable as-is; a v2 universal envelope never masquerades
    as a v1 receipt.
    """
    if not isinstance(value, Mapping) or value.get("schema") != V1_SCHEMA:
        return False
    result = value.get("result")
    return (
        isinstance(result, Mapping)
        and result.get("verified") is True
        and result.get("status") in {"COMPLETE", "VERIFIED", "PASSED"}
    )


# Descriptive aliases keep the public API discoverable without introducing a
# second contract or second schema identifier.
build_universal_execution_envelope = build_execution_envelope
validate_universal_execution_envelope = validate_execution_envelope
build_envelope = build_execution_envelope
validate_envelope = validate_execution_envelope
build_universal_envelope = build_execution_envelope
validate_universal_envelope = validate_execution_envelope
UniversalExecutionEnvelopeError = EnvelopeValidationError


__all__ = [
    "EXECUTION_FLOWS",
    "EXECUTION_REPORT_SCHEMA",
    "EXECUTION_STATUSES",
    "EnvelopeValidationError",
    "METRIC_NAMES",
    "PHASES",
    "SCHEMA",
    "V1_SCHEMA",
    "build_execution_envelope",
    "build_envelope",
    "build_universal_envelope",
    "build_universal_execution_envelope",
    "is_v1_receipt_compatible",
    "validate_execution_envelope",
    "validate_envelope",
    "validate_universal_envelope",
    "validate_universal_execution_envelope",
    "UniversalExecutionEnvelopeError",
]
