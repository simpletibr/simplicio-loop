"""Checkout-bound hot-path evidence for issue #242.

The benchmark measures the current checkout directly. It deliberately keeps
cold rebuilds as one measured baseline because a 1M cold rebuild is expensive;
the existing 30-repetition cold receipt remains historical unless it carries
the same source commit.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import platform
import statistics
import subprocess
import tempfile
from time import perf_counter, process_time
from typing import Any, Iterable

from benchmarks.changed_path_delta_230 import _make_root, _measure, workload_shape
from simplicio_fast.snapshot import Snapshot, build_snapshot


SCHEMA = "simplicio.fast.issue242-hotpath-receipt/v1"
DEFAULT_SCALES = (1_000, 10_000, 100_000, 1_000_000)


@dataclass(frozen=True)
class Sample:
    wall_ms: float
    cpu_ms: float
    stage_timings_ms: dict[str, float] | None
    parsed_files: int
    reused_files: int
    parity: bool


def _summary(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = list(rows)

    def percentile(name: str, fraction: float) -> float:
        ordered = sorted(float(row[name]) for row in values)
        position = (len(ordered) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    stage_coverages = [
        sum(float(value) for value in (row.get("stage_timings_ms") or {}).values())
        / float(row["wall_ms"])
        for row in values
        if row.get("stage_timings_ms")
    ]
    return {
        "repetitions": len(values),
        "wall_ms_median": statistics.median(float(row["wall_ms"]) for row in values),
        "wall_ms_p95": percentile("wall_ms", 0.95),
        "wall_ms_p99": percentile("wall_ms", 0.99),
        "cpu_ms_median": statistics.median(float(row["cpu_ms"]) for row in values),
        "parsed_files_median": statistics.median(int(row["parsed_files"]) for row in values),
        "reused_files_median": statistics.median(int(row["reused_files"]) for row in values),
        "parity": all(bool(row["parity"]) for row in values),
        "stage_coverage_min": min(stage_coverages) if stage_coverages else None,
    }


def _handoff_sample(store: Any, base: Any, worktree_id: str, path: str, generation: str) -> dict[str, Any]:
    started = perf_counter()
    cpu_started = process_time()
    report = store.handoff(base.generation_id, worktree_id, [path], delta_generation=generation)
    wall_ms = (perf_counter() - started) * 1000
    stage_timings = dict(report["stage_timings_ms"])
    measured = sum(float(value) for value in stage_timings.values())
    stage_timings["orchestration_and_receipt_residual"] = round(max(0.0, wall_ms - measured), 6)
    return {
        "wall_ms": wall_ms,
        "cpu_ms": (process_time() - cpu_started) * 1000,
        "stage_timings_ms": stage_timings,
        "parsed_files": report["files_parsed"],
        "reused_files": report["cache_reuse"],
        "parity": report["parity"],
    }


def _warm_sample(store: Any, base: Any) -> dict[str, Any]:
    snapshot = store.base_dir / base.generation_id / base.snapshot
    started = perf_counter()
    cpu_started = process_time()
    with Snapshot(snapshot) as opened:
        count = len(opened.files())
    return {
        "wall_ms": (perf_counter() - started) * 1000,
        "cpu_ms": (process_time() - cpu_started) * 1000,
        "parsed_files": 0,
        "reused_files": count,
        "parity": count == len(base.source_hashes),
    }


def run(*, scales: tuple[int, ...] = DEFAULT_SCALES, repetitions: int = 30) -> dict[str, Any]:
    if repetitions < 30:
        raise ValueError("issue 242 hot-path receipt requires at least 30 repetitions")
    rows: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="simplicio-fast-242-hotpath-") as directory:
        parent = Path(directory)
        for symbols in scales:
            files, functions = workload_shape(symbols)
            root, store, base, _sizes = _make_root(parent, files, f"s{symbols}", functions)
            path = "module_000.py"
            unchanged_delta = store.create_delta(base.generation_id, f"unchanged-{symbols}", [path])
            unchanged = [
                _handoff_sample(store, base, f"unchanged-{symbols}", path, unchanged_delta.delta_generation)
                for _ in range(repetitions)
            ]
            warm = [_warm_sample(store, base) for _ in range(repetitions)]

            changed: list[dict[str, Any]] = []
            for revision in range(repetitions):
                source = root / path
                source.write_text(
                    "".join(f"def value_0_{index}():\n    return {index + revision + 1}\n" for index in range(functions)),
                    encoding="utf-8",
                )
                worktree_id = f"one-file-{symbols}-{revision}"
                delta = store.create_delta(base.generation_id, worktree_id, [path])
                changed.append(_handoff_sample(store, base, worktree_id, path, delta.delta_generation))

            cold_path = root / "cold.sfast"
            cold_sample, _ = _measure(lambda: build_snapshot(root, cold_path))
            cold = {**cold_sample, "parsed_files": files, "reused_files": 0, "parity": True}
            unchanged_summary = _summary(unchanged)
            warm_summary = _summary(warm)
            changed_summary = _summary(changed)
            cold_summary = {**cold, "repetitions": 1}
            gates = {
                "one_file_within_half_cold": symbols < 10_000 or changed_summary["wall_ms_median"] <= cold["wall_ms"] * 0.5,
                "unchanged_within_two_times_warm": unchanged_summary["wall_ms_median"] <= warm_summary["wall_ms_median"] * 2,
                "unchanged_under_reference_budget": unchanged_summary["wall_ms_median"] <= 5.0,
                "parity": unchanged_summary["parity"] and changed_summary["parity"],
                "stage_coverage_ge_95_percent": unchanged_summary["stage_coverage_min"] >= 0.95 and changed_summary["stage_coverage_min"] >= 0.95,
            }
            rows[str(symbols)] = {
                "symbols": symbols,
                "files": files,
                "functions_per_file": functions,
                "cold": {"summary": cold_summary, "raw": [cold]},
                "warm": {"summary": warm_summary, "raw": warm},
                "unchanged": {"summary": unchanged_summary, "raw": unchanged},
                "one_file": {"summary": changed_summary, "raw": changed},
                "performance_gates": {"schema": "simplicio.fast.changed-path-performance-gates/v1", "checks": gates, "status": "pass" if all(gates.values()) else "fail"},
            }
    try:
        source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        source_commit = None
    return {
        "schema": SCHEMA,
        "status": "pass" if all(item["performance_gates"]["status"] == "pass" for item in rows.values()) else "fail",
        "source_commit": source_commit,
        "environment": {"platform": platform.platform(), "python": platform.python_version(), "metrics_status": "partial", "metric_reasons": {"rss_kib": "not_collected", "page_faults": "not_collected"}},
        "repetitions": repetitions,
        "scales": rows,
        "residuals": ["Linux_receipt", "CI_regression_gate", "coverage_final", "physical_20_reader_10_worktree_matrix"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scales", default=",".join(str(value) for value in DEFAULT_SCALES))
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(scales=tuple(int(value) for value in args.scales.split(",")), repetitions=args.repetitions)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    if receipt["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
