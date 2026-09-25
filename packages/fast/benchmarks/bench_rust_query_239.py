"""Measure indexed Rust exact queries at issue #239 corpus scales."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from simplicio_fast.rust_session import RustCoreSession
from simplicio_fast.snapshot import build_snapshot


SCHEMA = "simplicio.fast.rust-index-query-benchmark/v1"
REPETITIONS = 30


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _rss_kib(pid: int) -> int | None:
    try:
        import psutil
    except ImportError:
        return None
    try:
        return int(psutil.Process(pid).memory_info().rss // 1024)
    except (OSError, psutil.Error):
        return None


def _corpus(
    parent: Path, symbols: int, *, with_relations: bool = False
) -> tuple[Path, str]:
    files = max(1, math.ceil(math.sqrt(symbols)))
    functions = math.ceil(symbols / files)
    root = parent / f"corpus-{symbols}"
    root.mkdir()
    for file_index in range(files):
        first = file_index * functions
        last = min(symbols, first + functions)
        source = "".join(
            (
                f"def value_{index}():\n    return value_0()\n"
                if with_relations
                else f"def value_{index}():\n    return {index}\n"
            )
            for index in range(first, last)
        )
        (root / f"module_{file_index:05d}.py").write_text(source, encoding="utf-8")
    return root, "value_0"


def _build_binary(root: Path, supplied: Path | None) -> Path:
    if supplied is not None:
        return supplied.resolve()
    binary = root / "rust" / "target" / "release" / (
        "simplicio-fast-rs.exe" if os.name == "nt" else "simplicio-fast-rs"
    )
    subprocess.run(
        [
            shutil.which("cargo") or "cargo",
            "build",
            "--manifest-path",
            str(root / "rust" / "simplicio-fast-core" / "Cargo.toml"),
            "--locked",
            "--release",
            "--quiet",
        ],
        cwd=root,
        check=True,
        timeout=600,
    )
    return binary


def _measure(binary: Path, snapshot: Path, root: Path) -> dict[str, Any]:
    with RustCoreSession(binary) as session:
        warm = session.call(
            "query", {"snapshot": str(snapshot), "term": "value_0", "limit": 10}
        )
        baseline_rss = _rss_kib(session._process.pid)
        samples: list[float] = []
        decoded: list[int] = []
        rss: list[int] = []
        for _ in range(REPETITIONS):
            started = time.perf_counter()
            result = session.call(
                "query", {"snapshot": str(snapshot), "term": "value_0", "limit": 10}
            )
            samples.append((time.perf_counter() - started) * 1000)
            planner = result["planner"]
            decoded.append(int(planner["records_decoded"]))
            current_rss = _rss_kib(session._process.pid)
            if current_rss is not None:
                rss.append(current_rss)
        planner = warm["planner"]
        return {
            "samples_ms": samples,
            "wall_ms_median": statistics.median(samples),
            "wall_ms_p95": _percentile(samples, 0.95),
            "wall_ms_p99": _percentile(samples, 0.99),
            "records_decoded_max": max(decoded),
            "candidates_visited": int(planner["candidates_visited"]),
            "selected_index": planner["selected_index"],
            "rss_kib_max": max(rss) if rss else None,
            "rss_additional_kib_max": (
                max(max(0, value - baseline_rss) for value in rss)
                if rss and baseline_rss is not None
                else None
            ),
            "rss_baseline_kib": baseline_rss,
            "rss_reason": None if rss else "process_rss_unavailable",
            "matches": len(warm["matches"]),
            "root": str(root),
        }


def run(binary: Path | None = None, *, scales: tuple[int, ...] = (10_000, 100_000, 1_000_000)) -> dict[str, Any]:
    if any(scale < 1 for scale in scales):
        raise ValueError("scales must be positive")
    repository = Path(__file__).parents[1].resolve()
    executable = _build_binary(repository, binary)
    with tempfile.TemporaryDirectory(prefix="simplicio-fast-rust-index-") as directory:
        parent = Path(directory)
        results: dict[str, Any] = {}
        for scale in scales:
            root, _term = _corpus(parent, scale)
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            result = _measure(executable, snapshot, root)
            result.pop("root")
            results[str(scale)] = {
                "symbols": scale,
                "snapshot_bytes": snapshot.stat().st_size,
                **result,
            }
    performance_gates = {
        "exact_query_p95_ms_le_10": all(
            value["wall_ms_p95"] <= 10 for value in results.values()
        ),
        "indexed_candidates_bounded": all(
            value["records_decoded_max"] <= 10 for value in results.values()
        ),
        "query_additional_rss_le_8_mib": all(
            value["rss_additional_kib_max"] is not None
            and value["rss_additional_kib_max"] <= 8 * 1024
            for value in results.values()
        ),
    }
    return {
        "schema": SCHEMA,
        "status": "pass" if all(performance_gates.values()) else "fail",
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "rust_binary": str(executable),
            "repetitions": REPETITIONS,
        },
        "performance_gates": performance_gates,
        "scales": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--scales", default="10000,100000,1000000")
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(
        args.binary,
        scales=tuple(int(value) for value in args.scales.split(",") if value),
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
