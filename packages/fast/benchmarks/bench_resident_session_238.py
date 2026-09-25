"""Compare one-shot and resident Rust session latency for issue #238.

The benchmark never retries a request after a process failure. It records every
sample and reports p50/p95/p99 so startup and steady-state costs remain visible.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from simplicio_fast.rust_session import RustCoreSession
from simplicio_fast.snapshot import build_snapshot


SCHEMA = "simplicio.fast.resident-session-benchmark/v1"
OPERATION = "query"


def _summary(samples: list[float]) -> dict[str, Any]:
    ordered = sorted(samples)
    return {
        "count": len(samples),
        "median_ms": statistics.median(samples),
        "p95_ms": ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))],
        "p99_ms": ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.99) - 1))],
        "raw_ms": samples,
    }


def _one_shot(binary: Path, snapshot: Path) -> float:
    started = time.perf_counter()
    completed = subprocess.run(
        [str(binary), "--query", str(snapshot), "value_0", "--limit", "10"],
        capture_output=True,
        timeout=5,
        check=True,
    )
    if not completed.stdout:
        raise RuntimeError("native one-shot returned no response")
    return (time.perf_counter() - started) * 1000


def run(binary: Path, *, repetitions: int = 30) -> dict[str, Any]:
    if repetitions < 30:
        raise ValueError("issue 238 benchmark requires at least 30 repetitions")
    binary = binary.resolve()
    if not binary.is_file():
        raise FileNotFoundError(binary)
    with tempfile.TemporaryDirectory(prefix="simplicio-fast-238-") as directory:
        root = Path(directory)
        (root / "module.py").write_text(
            "".join(f"def value_{index}():\n    return {index}\n" for index in range(10_000)),
            encoding="utf-8",
        )
        snapshot = root / "project.sfast"
        build_snapshot(root, snapshot)
        one_shot = [_one_shot(binary, snapshot) for _ in range(repetitions)]
        with RustCoreSession(binary) as session:
            payload = {"snapshot": str(snapshot), "term": "value_0", "limit": 10}
            session.call(OPERATION, payload)
            resident: list[float] = []
            for _ in range(repetitions):
                started = time.perf_counter()
                session.call(OPERATION, payload)
                resident.append((time.perf_counter() - started) * 1000)
            cache_stats = session.call("session_cache_stats", {})
            if cache_stats.get("snapshots") != 1:
                raise RuntimeError("resident session did not retain one mapped generation")
            metrics = session.metrics()
    return {
        "schema": SCHEMA,
        "status": "pass",
        "environment": {
            "os": platform.platform(),
            "python": sys.version,
            "machine": platform.machine(),
            "executable": str(binary),
            "workload": {"symbols": 10_000, "term": "value_0", "limit": 10},
        },
        "request": {
            "operation": OPERATION,
            "payload": {"term": "value_0", "limit": 10},
        },
        "one_shot": _summary(one_shot),
        "resident": _summary(resident),
        "resident_metrics": metrics,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.binary, repetitions=args.repetitions)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
