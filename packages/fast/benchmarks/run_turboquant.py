"""Reproducible FWHT microbenchmark for Fast-TurboQuant issue #88."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from collections.abc import Callable, Sequence

from simplicio_fast.fwht import fwht


def _dense_hadamard(values: Sequence[float]) -> tuple[float, ...]:
    """Reference dense Hadamard transform using the same unscaled math."""
    size = len(values)
    result: list[float] = []
    for row in range(size):
        total = 0.0
        for column, value in enumerate(values):
            parity = (row & column).bit_count() & 1
            total += (-1.0 if parity else 1.0) * value
        result.append(total)
    return tuple(result)


def _measure(operation: Callable[[], object], *, repetitions: int) -> dict[str, object]:
    samples: list[float] = []
    for _ in range(repetitions):
        started = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - started) * 1000.0)
    ordered = sorted(samples)
    return {
        "repetitions": repetitions,
        "median_ms": statistics.median(samples),
        "p95_ms": ordered[max(0, int(len(ordered) * 0.95) - 1)],
        "samples_ms": samples,
    }


def run(*, dimension: int, repetitions: int, seed: int) -> dict[str, object]:
    if dimension < 1 or dimension & (dimension - 1):
        raise ValueError("dimension must be a positive power of two")
    if repetitions < 1:
        raise ValueError("repetitions must be positive")

    values = tuple(
        ((index * 17 + seed * 13) % 101 - 50) / 17.0 for index in range(dimension)
    )
    expected = _dense_hadamard(values)
    fast_result = fwht(values, normalization="none")
    if max(abs(left - right) for left, right in zip(fast_result, expected)) > 1e-9:
        raise AssertionError("FWHT result diverged from dense reference")

    baseline = _measure(lambda: _dense_hadamard(values), repetitions=repetitions)
    fast = _measure(lambda: fwht(values, normalization="none"), repetitions=repetitions)
    speedup = baseline["median_ms"] / fast["median_ms"]
    return {
        "schema": "simplicio.fast.turboquant-benchmark/v1",
        "status": "complete",
        "scope": "FWHT candidate-generation microbenchmark",
        "warning": "This is not an end-to-end quantization, recall, Rust, or SIMD claim.",
        "dimension": dimension,
        "seed": seed,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "baseline_dense_transform": baseline,
        "fast_fwht": fast,
        "median_speedup": speedup,
        "dense_multiply_operations_avoided": dimension * dimension,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dimension", type=int, default=256)
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    print(
        json.dumps(
            run(dimension=args.dimension, repetitions=args.repetitions, seed=args.seed),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
