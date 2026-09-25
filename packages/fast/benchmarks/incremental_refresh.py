"""Repeated one-change incremental refresh benchmark for issue #188."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import tempfile
import time
from pathlib import Path

from simplicio_fast.snapshot import build_snapshot


SCHEMA = "simplicio.fast.incremental-refresh-benchmark/v1"


def _seed(root: Path, files: int) -> None:
    for index in range(files):
        path = root / f"crate_{index // 100:03d}" / f"module_{index:05d}.rs"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"pub fn value_{index}() -> usize {{ {index} }}\n",
            encoding="utf-8",
        )


def _change(root: Path, index: int, revision: int) -> None:
    path = root / f"crate_{index // 100:03d}" / f"module_{index:05d}.rs"
    path.write_text(
        f"pub fn value_{index}() -> usize {{ {index + revision} }}\n",
        encoding="utf-8",
    )


def run(*, files: int = 2400, repetitions: int = 5) -> dict:
    if files < 1 or repetitions < 2:
        raise ValueError("files must be positive and repetitions must be at least two")
    with tempfile.TemporaryDirectory(prefix="simplicio-fast-incremental-") as directory:
        base = Path(directory)
        baseline_root = base / "baseline"
        fast_root = base / "fast"
        _seed(baseline_root, files)
        _seed(fast_root, files)
        baseline_snapshot = base / "baseline.sfast"
        fast_snapshot = base / "fast.sfast"
        build_snapshot(baseline_root, baseline_snapshot)
        build_snapshot(fast_root, fast_snapshot)
        baseline_samples = []
        fast_samples = []
        phase_samples = []
        for revision in range(1, repetitions + 1):
            changed_index = revision % files
            _change(baseline_root, changed_index, revision)
            _change(fast_root, changed_index, revision)
            baseline_snapshot.with_name(
                f"{baseline_snapshot.name}.validation.json"
            ).write_text("{}", encoding="utf-8")
            start = time.perf_counter()
            build_snapshot(baseline_root, baseline_snapshot)
            baseline_samples.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            candidate = build_snapshot(fast_root, fast_snapshot)
            fast_samples.append((time.perf_counter() - start) * 1000)
            phase_samples.append(candidate.phase_timings_ms)
            if candidate.parsed_files != 1 or candidate.reused_files != files - 1:
                raise RuntimeError(
                    "incremental receipt did not preserve one-change semantics"
                )
        baseline_median = statistics.median(baseline_samples)
        fast_median = statistics.median(fast_samples)
        return {
            "schema": SCHEMA,
            "status": "pass",
            "workload": {
                "files": files,
                "changed_files": 1,
                "repetitions": repetitions,
            },
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "processor": platform.processor() or None,
            },
            "raw": {
                "full_hash_validation_wall_ms": baseline_samples,
                "metadata_validation_wall_ms": fast_samples,
                "metadata_phase_timings_ms": phase_samples,
            },
            "totals": {
                "full_hash_validation_median_ms": baseline_median,
                "metadata_validation_median_ms": fast_median,
                "speedup": baseline_median / fast_median if fast_median else None,
            },
            "limitations": [
                "Local synthetic Rust corpus; no LLM or provider token telemetry.",
                "Metadata identity mismatch falls back to byte hashing.",
            ],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=2400)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    receipt = run(files=args.files, repetitions=args.repetitions)
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
