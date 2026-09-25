"""Deterministic hot-path evidence for issue #497."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

try:
    import tracemalloc
except ImportError:  # pragma: no cover - Python builds can omit tracemalloc.
    tracemalloc = None  # type: ignore[assignment]

from simplicio_fast.capability_ranking import (
    CapabilityCandidate,
    _split_required_capabilities,
    rank_capabilities,
)

SCHEMA = "simplicio.fast.hot-path-benchmark/v1"
REQUIRED = tuple(f"cap-{index:02d}" for index in range(8))
DEFAULT_SCALES = (1, 8, 64, 256, 1_024)
DEFAULT_REPETITIONS = 15


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _build_candidates(count: int) -> tuple[CapabilityCandidate, ...]:
    return tuple(
        CapabilityCandidate(
            handle=f"worker:{index:05d}",
            kind="worker",
            version="1",
            capabilities=tuple(
                f"cap-{(index * 5 + offset) % 32:02d}" for offset in range(12)
            ),
            policy_eligible=True,
        )
        for index in range(count)
    )


def _legacy_match(
    required_set: set[str], candidate: CapabilityCandidate
) -> tuple[list[str], list[str]]:
    """The pre-#497 per-candidate kernel, retained only as a benchmark baseline."""
    return (
        sorted(required_set.intersection(candidate.capabilities)),
        sorted(required_set.difference(candidate.capabilities)),
    )


def _cached_match(
    ordered_required: Sequence[str], candidate: CapabilityCandidate
) -> tuple[list[str], list[str]]:
    return _split_required_capabilities(ordered_required, candidate._capability_set)


def _measure(
    operation: Callable[[], Any], *, repetitions: int
) -> tuple[dict[str, int], Any, str]:
    for _ in range(3):
        operation()
    samples: list[int] = []
    result: Any = None
    for _ in range(repetitions):
        started = time.perf_counter_ns()
        result = operation()
        samples.append(time.perf_counter_ns() - started)
    ordered = sorted(samples)
    return (
        {
            "repetitions": repetitions,
            "wall_ns_min": min(samples),
            "wall_ns_median": int(statistics.median(samples)),
            "wall_ns_p95": ordered[max(0, int(repetitions * 0.95) - 1)],
        },
        result,
        _digest(samples),
    )


def _peak_traced_bytes(operation: Callable[[], Any]) -> int | None:
    if tracemalloc is None:
        return None
    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        operation()
        return tracemalloc.get_traced_memory()[1]
    finally:
        if not was_tracing:
            tracemalloc.stop()


def _kernel_receipt(
    candidates: Sequence[CapabilityCandidate], *, repetitions: int
) -> dict[str, Any]:
    required_set = set(REQUIRED)
    ordered_required = sorted(required_set)

    def legacy() -> tuple[tuple[str, ...], ...]:
        return tuple(
            tuple(item)
            for candidate in candidates
            for item in _legacy_match(required_set, candidate)
        )

    def cached() -> tuple[tuple[str, ...], ...]:
        return tuple(
            tuple(item)
            for candidate in candidates
            for item in _cached_match(ordered_required, candidate)
        )

    legacy_timing, legacy_result, legacy_sample_digest = _measure(
        legacy, repetitions=repetitions
    )
    cached_timing, cached_result, cached_sample_digest = _measure(
        cached, repetitions=repetitions
    )
    if legacy_result != cached_result:
        raise AssertionError("cached capability matching changed the result")
    baseline = legacy_timing["wall_ns_median"]
    optimized = cached_timing["wall_ns_median"]
    baseline_peak = _peak_traced_bytes(legacy)
    optimized_peak = _peak_traced_bytes(cached)
    return {
        "semantics_equal": True,
        "result_digest": _digest(cached_result),
        "comparison": {
            "median_latency_ratio": round(optimized / baseline, 6),
            "median_latency_reduction_ns": baseline - optimized,
            "peak_traced_bytes_reduction": (
                baseline_peak - optimized_peak
                if baseline_peak is not None and optimized_peak is not None
                else None
            ),
        },
        "baseline_uncached": {
            **legacy_timing,
            "sample_digest": legacy_sample_digest,
            "peak_traced_bytes": baseline_peak,
        },
        "optimized_cached": {
            **cached_timing,
            "sample_digest": cached_sample_digest,
            "peak_traced_bytes": optimized_peak,
        },
    }


def _ranking_receipt(
    candidates: Sequence[CapabilityCandidate], *, repetitions: int
) -> dict[str, Any]:
    def rank() -> dict[str, Any]:
        return rank_capabilities(candidates, REQUIRED, max_results=32)

    timing, result, sample_digest = _measure(rank, repetitions=repetitions)
    return {
        **timing,
        "sample_digest": sample_digest,
        "result_digest": _digest(result),
        "peak_traced_bytes": _peak_traced_bytes(rank),
    }


def run(
    *,
    scales: Sequence[int] = DEFAULT_SCALES,
    repetitions: int = DEFAULT_REPETITIONS,
) -> dict[str, Any]:
    if not scales or any(scale < 1 for scale in scales):
        raise ValueError("scales must contain positive integers")
    if repetitions < 5:
        raise ValueError("repetitions must be at least 5")
    max_scale = max(scales)
    candidates = _build_candidates(max_scale)
    rows: dict[str, Any] = {}
    for scale in scales:
        selected = candidates[:scale]
        rows[str(scale)] = {
            "batch_size": scale,
            "kernel": _kernel_receipt(selected, repetitions=repetitions),
            "ranking": _ranking_receipt(selected, repetitions=repetitions),
        }
    return {
        "schema": SCHEMA,
        "status": "pass",
        "issue": 497,
        "workload": {
            "required_capabilities": list(REQUIRED),
            "candidate_count": max_scale,
            "candidate_digest": _digest(
                [candidate.capabilities for candidate in candidates]
            ),
            "scales": list(scales),
            "repetitions": repetitions,
        },
        "optimization": {
            "name": "candidate_capability_frozenset",
            "portable": True,
            "isa_dispatch": "none",
            "disabled_when": "never; the implementation has no ISA-specific branch",
            "break_even": "measured by kernel and full-ranking rows at every reported batch size",
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "metric_reasons": {
                "cache_misses": "not_collected",
                "copied_bytes": "not_collected",
                "page_faults": "not_collected",
                "rss_kib": "not_collected",
                "traced_peak_bytes": (
                    "available"
                    if tracemalloc is not None
                    else "tracemalloc_unavailable"
                ),
            },
        },
        "scales": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    parser.add_argument("--scales", type=int, nargs="+", default=DEFAULT_SCALES)
    args = parser.parse_args()
    receipt = run(scales=tuple(args.scales), repetitions=args.repetitions)
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.json_out is not None:
        args.json_out.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
