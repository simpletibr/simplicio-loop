"""Measure bounded Rust relation queries on a high-cardinality snapshot."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    from benchmarks.bench_rust_query_239 import _corpus, _percentile
except ModuleNotFoundError:
    from bench_rust_query_239 import _corpus, _percentile
from simplicio_fast.rust_session import RustCoreSession
from simplicio_fast.snapshot import build_snapshot


SCHEMA = "simplicio.fast.rust-relations-benchmark/v1"
REPETITIONS = 30


def _rss_kib(pid: int) -> int | None:
    try:
        import psutil
    except ImportError:
        return None
    try:
        return int(psutil.Process(pid).memory_info().rss // 1024)
    except (OSError, psutil.Error):
        return None


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


def _measure(binary: Path, snapshot: Path) -> dict[str, Any]:
    with RustCoreSession(binary) as session:
        stats = session.call("stats", {"snapshot": str(snapshot)})["stats"]
        warm = session.call(
            "relations",
            {
                "snapshot": str(snapshot),
                "handle": "value_0",
                "kind": "call",
                "limit": 10,
            },
        )
        baseline_rss = _rss_kib(session._process.pid)
        samples: list[float] = []
        records_decoded: list[int] = []
        rss: list[int] = []
        for _ in range(REPETITIONS):
            started = time.perf_counter()
            result = session.call(
                "relations",
                {
                    "snapshot": str(snapshot),
                    "handle": "value_0",
                    "kind": "call",
                    "limit": 10,
                },
            )
            samples.append((time.perf_counter() - started) * 1000)
            records_decoded.append(int(result["planner"]["records_decoded"]))
            current_rss = _rss_kib(session._process.pid)
            if current_rss is not None:
                rss.append(current_rss)
        return {
            "symbols": int(stats["symbols"]),
            "relations": int(stats["relations"]),
            "samples_ms": samples,
            "wall_ms_median": statistics.median(samples),
            "wall_ms_p95": _percentile(samples, 0.95),
            "wall_ms_p99": _percentile(samples, 0.99),
            "records_decoded_max": max(records_decoded),
            "matches": len(warm["relations"]),
            "rss_kib_baseline": baseline_rss,
            "rss_kib_max": max(rss) if rss else None,
            "rss_additional_kib_max": (
                max(max(0, value - baseline_rss) for value in rss)
                if rss and baseline_rss is not None
                else None
            ),
            "rss_reason": None if rss else "process_rss_unavailable",
        }


def run(
    binary: Path | None = None,
    *,
    scales: tuple[int, ...] = (10_000, 100_000),
) -> dict[str, Any]:
    if any(scale < 1 for scale in scales):
        raise ValueError("scales must be positive")
    repository = Path(__file__).parents[1].resolve()
    executable = _build_binary(repository, binary)
    with tempfile.TemporaryDirectory(prefix="simplicio-fast-rust-relations-") as directory:
        parent = Path(directory)
        results: dict[str, dict[str, Any]] = {}
        for scale in scales:
            root, _term = _corpus(parent, scale, with_relations=True)
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            results[str(scale)] = _measure(executable, snapshot)
    gates = {
        "limit_bounded": all(value["records_decoded_max"] <= 10 for value in results.values()),
        "relation_matches_present": all(value["matches"] == 10 for value in results.values()),
    }
    return {
        "schema": SCHEMA,
        "status": "pass" if all(gates.values()) else "fail",
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "rust_binary": str(executable),
            "repetitions": REPETITIONS,
        },
        "performance_gates": gates,
        "scales": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--scales", default="10000,100000")
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(
        args.binary,
        scales=tuple(int(value) for value in args.scales.split(",") if value),
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
