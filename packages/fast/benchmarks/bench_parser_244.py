"""Measured Python parser-adapter benchmark for issue #244."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from simplicio_fast.parser_adapter import build_payload


SCHEMA = "simplicio.fast.parser-adapter-benchmark/v1"
MIN_REPETITIONS = 10
FUNCTIONS_PER_FILE = 100


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = min(len(ordered) - 1, lower + 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _rss_kib() -> int | None:
    try:
        import psutil

        return int(psutil.Process(os.getpid()).memory_info().rss // 1024)
    except (ImportError, OSError):
        return None


def _measure(root: Path, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()
    payload = operation()
    return {
        "wall_ms": (time.perf_counter_ns() - started) / 1_000_000,
        "cpu_ms": (time.process_time_ns() - cpu_started) / 1_000_000,
        "rss_kib": _rss_kib(),
        "payload_bytes": len(json.dumps(payload, sort_keys=True).encode("utf-8")),
        "parsed_files": len(payload["invalidation"]["parsed_paths"]),
        "reused_files": len(payload["invalidation"]["reused_paths"]),
        "parsed_bytes": sum(
            (root / path).stat().st_size
            for path in payload["invalidation"]["parsed_paths"]
        ),
        "reused_bytes": sum(
            (root / path).stat().st_size
            for path in payload["invalidation"]["reused_paths"]
        ),
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def median(name: str) -> float | None:
        values = [float(row[name]) for row in rows if row[name] is not None]
        return statistics.median(values) if values else None

    def percentile(name: str, fraction: float) -> float | None:
        values = [float(row[name]) for row in rows if row[name] is not None]
        return _percentile(values, fraction) if values else None

    return {
        "repetitions": len(rows),
        "wall_ms_median": median("wall_ms"),
        "wall_ms_p95": percentile("wall_ms", 0.95),
        "wall_ms_p99": percentile("wall_ms", 0.99),
        "cpu_ms_median": median("cpu_ms"),
        "rss_kib_median": median("rss_kib"),
        "payload_bytes_median": median("payload_bytes"),
        "parsed_files_median": median("parsed_files"),
        "reused_files_median": median("reused_files"),
        "parsed_bytes_median": median("parsed_bytes"),
        "reused_bytes_median": median("reused_bytes"),
        "raw": rows,
    }


def _source(root: Path, files: int) -> None:
    for index in range(files):
        text = "".join(
            f"def value_{index}_{function}():\n    return {function}\n"
            for function in range(FUNCTIONS_PER_FILE)
        )
        (root / f"module_{index:04d}.py").write_text(text, encoding="utf-8")


def _category(
    root: Path,
    symbols: int,
    repetitions: int,
    category: str,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    files = math.ceil(symbols / FUNCTIONS_PER_FILE)
    _source(root, files)
    baseline = build_payload(root)
    target = root / "module_0000.py"
    original = target.read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    for repetition in range(repetitions):
        if category == "cold":
            def operation() -> dict[str, Any]:
                return build_payload(root)
        elif category == "unchanged":
            def operation() -> dict[str, Any]:
                return build_payload(root, changed_paths=[], previous_payload=baseline)
        else:
            target.write_text(
                original + f"\ndef changed_{repetition}():\n    return {repetition}\n",
                encoding="utf-8",
            )
            def operation() -> dict[str, Any]:
                return build_payload(
                    root,
                    changed_paths=["module_0000.py"],
                    previous_payload=baseline,
                )
        rows.append(_measure(root, operation))
        if category == "one_file":
            target.write_text(original, encoding="utf-8")
    return {
        "symbols": symbols,
        "files": files,
        "category": category,
        **_summary(rows),
    }


def run(*, symbols: tuple[int, ...] = (10_000, 100_000), repetitions: int = 10) -> dict[str, Any]:
    if repetitions < MIN_REPETITIONS:
        raise ValueError(f"issue 244 benchmark requires at least {MIN_REPETITIONS} repetitions")
    if not symbols or any(value < 1 for value in symbols):
        raise ValueError("symbols must contain positive values")
    with tempfile.TemporaryDirectory(prefix="simplicio-fast-244-") as directory:
        root = Path(directory)
        results = {
            str(value): {
                category: _category(root / f"{value}-{category}", value, repetitions, category)
                for category in ("cold", "one_file", "unchanged")
            }
            for value in symbols
        }
    return {
        "schema": SCHEMA,
        "status": "pass",
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "repetitions": repetitions,
            "rss_reason": None,
        },
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", type=int, nargs="+", default=[10_000, 100_000])
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(symbols=tuple(args.symbols), repetitions=args.repetitions)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
