"""Versioned evidence and benchmark receipt contracts for Fast operators."""

from __future__ import annotations

import json
from typing import Any, Mapping

EXECUTION_REPORT_SCHEMA = "simplicio.execution-report/v1"
CLASSIFICATIONS = frozenset({"MEASURED", "REPLAYED", "ESTIMATED", "BLOCKED"})


class ReceiptError(ValueError):
    """Raised when an evidence receipt is incomplete or claims unsupported facts."""


def _required(mapping: Mapping[str, Any], key: str) -> Any:
    value = mapping.get(key)
    if value is None or value == "":
        raise ReceiptError(f"missing {key}")
    return value


def benchmark_receipt(
    *,
    repository_id: str,
    source_commit: str,
    generation: str,
    fixture: Mapping[str, Any],
    workload: Mapping[str, Any],
    hardware: Mapping[str, Any],
    cache_policy: str,
    repetitions: int,
    baseline: Mapping[str, Any],
    classification: str,
    evidence: Mapping[str, Any],
    metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the shared execution-report shape without inventing measurements."""
    receipt = {
        "schema": EXECUTION_REPORT_SCHEMA,
        "kind": "benchmark",
        "repository_id": repository_id,
        "source_commit": source_commit,
        "generation": generation,
        "fixture": dict(fixture),
        "workload": dict(workload),
        "hardware": dict(hardware),
        "cache_policy": cache_policy,
        "repetitions": repetitions,
        "baseline": dict(baseline),
        "classification": classification,
        "metrics": dict(metrics) if metrics is not None else None,
        "evidence": dict(evidence),
    }
    return validate_execution_report(receipt)


def validate_execution_report(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the common receipt contract and reject unsubstantiated metrics."""
    if not isinstance(receipt, Mapping):
        raise ReceiptError("receipt must be an object")
    if receipt.get("schema") != EXECUTION_REPORT_SCHEMA:
        raise ReceiptError("unsupported execution report schema")
    if receipt.get("kind") not in {"validation", "benchmark"}:
        raise ReceiptError("unsupported receipt kind")
    for key in (
        "repository_id",
        "source_commit",
        "generation",
        "fixture",
        "workload",
        "hardware",
        "cache_policy",
        "baseline",
        "evidence",
    ):
        _required(receipt, key)
    classification = receipt.get("classification")
    if classification not in CLASSIFICATIONS:
        raise ReceiptError("unsupported classification")
    repetitions = receipt.get("repetitions")
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions < 0:
        raise ReceiptError("repetitions must be a non-negative integer")
    if receipt.get("kind") == "benchmark" and classification == "MEASURED" and repetitions < 10:
        raise ReceiptError("measured benchmark requires at least ten repetitions")
    metrics = receipt.get("metrics")
    if classification == "MEASURED":
        evidence = receipt["evidence"]
        if not isinstance(evidence, Mapping) or evidence.get("command") in {None, ""}:
            raise ReceiptError("measured evidence requires command")
        if metrics is None or not metrics:
            raise ReceiptError("measured evidence requires metrics")
    elif metrics is not None and not isinstance(metrics, Mapping):
        raise ReceiptError("metrics must be an object or null")
    return dict(receipt)


__all__ = [
    "CLASSIFICATIONS",
    "EXECUTION_REPORT_SCHEMA",
    "ReceiptError",
    "benchmark_receipt",
    "validate_execution_report",
]
