"""Reproducible A/B benchmark for structural context efficiency.

The runner measures captured context and accepts provider usage receipts when
available. Missing provider metrics stay ``None`` and never become zero.
"""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BENCHMARK_SCHEMA = "simplicio.structural-benchmark/v1"


def estimate_context_tokens(text: str) -> int:
    return max(1, math.ceil(len(text.encode("utf-8")) / 4)) if text else 0


def quality_score(answer: str, expected_facts: Iterable[str]) -> float:
    facts = tuple(fact.casefold() for fact in expected_facts if fact)
    if not facts:
        return 1.0
    normalized = answer.casefold()
    return sum(fact in normalized for fact in facts) / len(facts)


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    question: str
    repo_sha: str
    baseline_context: str
    mapper_context: str
    baseline_answer: str
    mapper_answer: str
    expected_facts: tuple[str, ...]
    model: str = "unavailable"


@dataclass(frozen=True, slots=True)
class ExecutionMeasurement:
    context_tokens: int
    bytes_returned: int
    tool_calls: int
    files_read: int
    quality: float
    provider_input_tokens: int | None = None
    provider_cached_input_tokens: int | None = None
    provider_output_tokens: int | None = None
    wall_time_ms: float | None = None


@dataclass(frozen=True, slots=True)
class CaseMeasurement:
    case_id: str
    baseline: ExecutionMeasurement
    mapper: ExecutionMeasurement
    context_saving: float | None
    quality_gate: bool


def _measurement(context: str, answer: str, expected_facts: Iterable[str], *, tool_calls: int, files_read: int, provider_usage: dict[str, Any] | None = None) -> ExecutionMeasurement:
    provider_usage = provider_usage or {}
    return ExecutionMeasurement(
        context_tokens=estimate_context_tokens(context),
        bytes_returned=len(context.encode("utf-8")),
        tool_calls=tool_calls,
        files_read=files_read,
        quality=quality_score(answer, expected_facts),
        provider_input_tokens=provider_usage.get("input_tokens"),
        provider_cached_input_tokens=provider_usage.get("cached_input_tokens"),
        provider_output_tokens=provider_usage.get("output_tokens"),
        wall_time_ms=provider_usage.get("wall_time_ms"),
    )


def measure_case(case: BenchmarkCase, *, provider_usage: dict[str, dict[str, Any]] | None = None) -> CaseMeasurement:
    provider_usage = provider_usage or {}
    baseline = _measurement(case.baseline_context, case.baseline_answer, case.expected_facts, tool_calls=1, files_read=max(1, case.baseline_context.count("\n")), provider_usage=provider_usage.get("baseline"))
    mapper = _measurement(case.mapper_context, case.mapper_answer, case.expected_facts, tool_calls=1, files_read=max(1, case.mapper_context.count("\n")), provider_usage=provider_usage.get("mapper"))
    saving = None if baseline.context_tokens == 0 else 1 - mapper.context_tokens / baseline.context_tokens
    return CaseMeasurement(case.case_id, baseline, mapper, saving, mapper.quality >= baseline.quality)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def summarize(cases: Iterable[BenchmarkCase], measurements: Iterable[CaseMeasurement]) -> dict[str, Any]:
    cases = tuple(cases)
    measurements = tuple(measurements)
    savings = [item.context_saving for item in measurements if item.context_saving is not None]
    qualities = [item.mapper.quality for item in measurements]
    quality_pass = bool(measurements) and all(item.quality_gate for item in measurements)
    return {
        "schema": BENCHMARK_SCHEMA,
        "case_count": len(cases),
        "case_ids": [case.case_id for case in cases],
        "repo_shas": sorted({case.repo_sha for case in cases}),
        "models": sorted({case.model for case in cases}),
        "metrics": {
            "context_saving": {"measured_cases": len(savings), "median": statistics.median(savings) if savings else None, "p50": _percentile(savings, 0.50), "p95": _percentile(savings, 0.95), "min": min(savings) if savings else None, "max": max(savings) if savings else None},
            "mapper_quality": {"median": statistics.median(qualities) if qualities else None, "min": min(qualities) if qualities else None},
            "provider_tokens": "unavailable unless receipts are supplied",
        },
        "quality_gate": {"passed": quality_pass, "rule": "mapper quality must be >= baseline quality for every case"},
        "claim_99_percent_enabled": bool(savings) and quality_pass and statistics.median(savings) >= 0.99,
        "measurements": [
            {
                "case_id": item.case_id,
                "baseline": item.baseline.__dict__ if hasattr(item.baseline, "__dict__") else {field: getattr(item.baseline, field) for field in item.baseline.__dataclass_fields__},
                "mapper": item.mapper.__dict__ if hasattr(item.mapper, "__dict__") else {field: getattr(item.mapper, field) for field in item.mapper.__dataclass_fields__},
                "context_saving": item.context_saving,
                "quality_gate": item.quality_gate,
            }
            for item in measurements
        ],
    }


def load_cases(path: str | Path) -> tuple[BenchmarkCase, ...]:
    cases = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        cases.append(BenchmarkCase(**{**raw, "expected_facts": tuple(raw.get("expected_facts", ())) }))
    return tuple(cases)


def run_corpus(path: str | Path, *, provider_receipts: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    cases = load_cases(path)
    measurements = [measure_case(case, provider_usage=provider_receipts.get(case.case_id) if provider_receipts else None) for case in cases]
    return summarize(cases, measurements)


__all__ = ["BENCHMARK_SCHEMA", "BenchmarkCase", "CaseMeasurement", "measure_case", "quality_score", "run_corpus", "summarize"]
