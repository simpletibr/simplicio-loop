"""Measure warm DeliveryEngine preparation on a 100k-symbol fixture."""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from simplicio_fast.delivery import DeliveryEngine
from simplicio_fast.engine import select_engine
from simplicio_fast.snapshot import build_snapshot


SCHEMA = "simplicio.fast.delivery-100k-benchmark/v1"
SYMBOLS = 100_000
FILES = 100
REPETITIONS = 10
WARM_P95_LIMIT_MS = 25.0


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = min(len(ordered) - 1, lower + 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _build_source(root: Path) -> None:
    per_file = SYMBOLS // FILES
    for file_index in range(FILES):
        start = file_index * per_file
        lines = [
            f"def symbol_{symbol}():\n    return {symbol}\n"
            for symbol in range(start, start + per_file)
        ]
        (root / f"module_{file_index:03d}.py").write_text("".join(lines), encoding="utf-8")


def run(*, repetitions: int = REPETITIONS) -> dict[str, Any]:
    if repetitions < 10:
        raise ValueError("repetitions must be at least 10")
    with tempfile.TemporaryDirectory(prefix="simplicio-fast-240-100k-") as directory:
        root = Path(directory)
        _build_source(root)
        snapshot = root / "project.sfast"
        started = time.perf_counter()
        build_snapshot(root, snapshot)
        snapshot_ms = (time.perf_counter() - started) * 1000
        engine = DeliveryEngine(root, snapshot, root / "cache")
        engine_receipt = select_engine("python").receipt()
        query = "symbol_50000"
        first = engine.prepare(
            query,
            profile="loop-standalone",
            engine_receipt=engine_receipt,
            selection_mode="semantic",
            tokenizer_id="whitespace-v1",
            tokenizer=lambda text: len(text.split()),
        )
        warm: list[float] = []
        for _ in range(repetitions):
            started = time.perf_counter()
            result = engine.prepare(
                query,
                profile="loop-standalone",
                engine_receipt=engine_receipt,
                selection_mode="semantic",
                tokenizer_id="whitespace-v1",
                tokenizer=lambda text: len(text.split()),
            )
            warm.append((time.perf_counter() - started) * 1000)
        selected_files = sorted({item["file"] for item in result["context"]["selected"]})
        gate = _percentile(warm, 0.95) <= WARM_P95_LIMIT_MS
        return {
            "schema": SCHEMA,
            "status": "partial",
            "scope": "synthetic-100k-symbol-delivery-fixture",
            "environment": {"platform": platform.platform(), "python": platform.python_version()},
            "workload": {"symbols": SYMBOLS, "files": FILES, "repetitions": repetitions},
            "snapshot_ms": snapshot_ms,
            "first_status": first["status"],
            "selected_files": selected_files,
            "warm_ms": warm,
            "warm_median_ms": statistics.median(warm),
            "warm_p95_ms": _percentile(warm, 0.95),
            "performance_gate": {
                "name": "warm_p95_ms<=25",
                "limit_ms": WARM_P95_LIMIT_MS,
                "observed_ms": _percentile(warm, 0.95),
                "passed": gate,
            },
            "unverified": [
                "historical_task_corpus",
                "installed_cross_platform",
                "downstream_task_success",
            ],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=REPETITIONS)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(repetitions=args.repetitions)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
