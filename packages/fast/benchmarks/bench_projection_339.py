"""Cross-domain Python projection benchmark for issue #339.

This measures the derived projection core only.  Rust parity and the canonical
non-projection baseline remain explicit unavailable cells in the receipt.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import platform
import statistics
import tempfile
import time
from typing import Any

from simplicio_fast.projection import ProjectionEnvelope, ProjectionStore


SCHEMA = "simplicio.fast.projection-benchmark/v1"


def _records(generation: str = "g1") -> tuple[ProjectionEnvelope, ...]:
    return tuple(
        ProjectionEnvelope.create(
            kind,
            producer=f"benchmark.{kind}",
            producer_schema=f"{kind}/v1",
            generation=generation,
            stable_handle=f"{kind}:item-1",
            payload={"repository": "benchmark-repo", "kind": kind, "value": 1},
        )
        for kind in ("code", "knowledge", "operations")
    )


def _summary(rows: list[dict[str, float]]) -> dict[str, Any]:
    walls = [row["wall_ms"] for row in rows]
    return {
        "repetitions": len(rows),
        "wall_ms_median": statistics.median(walls),
        "wall_ms_p95": sorted(walls)[max(0, int(len(walls) * 0.95) - 1)],
        "raw": rows,
    }


def run(repetitions: int = 30) -> dict[str, Any]:
    if repetitions < 10:
        raise ValueError("issue 339 benchmark requires at least 10 repetitions")
    cold: list[dict[str, float]] = []
    warm: list[dict[str, float]] = []
    delta: list[dict[str, float]] = []
    readers: list[dict[str, float]] = []
    consumers: list[dict[str, float]] = []
    with tempfile.TemporaryDirectory(prefix="simplicio-fast-339-") as directory:
        root = Path(directory)
        for repetition in range(repetitions):
            records = _records()
            started_cpu = time.process_time()
            started = time.perf_counter()
            store = ProjectionStore("benchmark-repo")
            for record in records:
                store.publish(record)
            path = root / f"projection-{repetition}.json"
            store.save(path)
            ProjectionStore.load(path, "benchmark-repo")
            cold.append(
                {
                    "wall_ms": (time.perf_counter() - started) * 1000,
                    "cpu_ms": (time.process_time() - started_cpu) * 1000,
                    "bytes": float(path.stat().st_size),
                }
            )

            started_cpu = time.process_time()
            started = time.perf_counter()
            store.snapshot()
            warm.append(
                {
                    "wall_ms": (time.perf_counter() - started) * 1000,
                    "cpu_ms": (time.process_time() - started_cpu) * 1000,
                    "bytes": 0.0,
                }
            )

            changed = ProjectionEnvelope.create(
                "code",
                producer="benchmark.code",
                producer_schema="code/v1",
                generation="g1",
                stable_handle="code:item-2",
                payload={"repository": "benchmark-repo", "value": repetition},
            )
            started_cpu = time.process_time()
            started = time.perf_counter()
            receipt = store.apply_delta(
                "g1", changed=(changed,), deleted_handles=("knowledge:item-1",)
            )
            assert receipt["closure_handles"]
            delta.append(
                {
                    "wall_ms": (time.perf_counter() - started) * 1000,
                    "cpu_ms": (time.process_time() - started_cpu) * 1000,
                    "bytes": 0.0,
                }
            )

            started_cpu = time.process_time()
            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=20) as pool:
                snapshots = list(pool.map(lambda _: store.snapshot(), range(20)))
            assert all(snapshot == snapshots[0] for snapshot in snapshots)
            readers.append(
                {
                    "wall_ms": (time.perf_counter() - started) * 1000,
                    "cpu_ms": (time.process_time() - started_cpu) * 1000,
                    "bytes": 0.0,
                }
            )

            started_cpu = time.process_time()
            started = time.perf_counter()
            for consumer in range(10):
                isolated = ProjectionStore(f"consumer-{consumer}")
                for record in _records():
                    isolated.publish(
                        ProjectionEnvelope.create(
                            record.projection_type,
                            producer=record.producer,
                            producer_schema=record.producer_schema,
                            generation=record.generation,
                            stable_handle=record.stable_handle,
                            payload={**record.payload, "repository": f"consumer-{consumer}"},
                        )
                    )
                isolated.snapshot()
            consumers.append(
                {
                    "wall_ms": (time.perf_counter() - started) * 1000,
                    "cpu_ms": (time.process_time() - started_cpu) * 1000,
                    "bytes": 0.0,
                }
            )
    return {
        "schema": SCHEMA,
        "status": "partial",
        "partial_reason": "rust_parity_and_canonical_baseline_unavailable",
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "repository": "benchmark-repo",
            "rss": {"value": None, "reason": "not_collected"},
            "page_faults": {"value": None, "reason": "not_collected"},
        },
        "workload": {"domains": ["code", "knowledge", "operations"], "readers": 20, "consumers": 10},
        "repetitions": repetitions,
        "scenarios": {
            "cold_publish_save_load": _summary(cold),
            "warm_snapshot": _summary(warm),
            "delta_closure": _summary(delta),
            "twenty_readers": _summary(readers),
            "ten_isolated_consumers": _summary(consumers),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.repetitions)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
