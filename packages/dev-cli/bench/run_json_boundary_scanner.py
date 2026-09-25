#!/usr/bin/env python3
"""Measure the strict scanner hot path and print Markdown evidence."""

from __future__ import annotations

import argparse
import platform
import statistics
import sys
import tempfile
import time
import tracemalloc
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.check_json_boundaries import check


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entries", type=int, default=10_000)
    parser.add_argument("--runs", type=int, default=7)
    args = parser.parse_args()
    repo = Path(__file__).parents[1]
    with tempfile.TemporaryDirectory() as temporary:
        artifact = Path(temporary) / "release.whl"
        with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_STORED) as archive:
            for index in range(args.entries):
                archive.writestr(f"package/data/{index:05}.toml", "value = 1\n")
        samples = []
        tracemalloc.start()
        for _ in range(args.runs):
            started = time.perf_counter_ns()
            assert check(repo, [artifact]) == []
            samples.append((time.perf_counter_ns() - started) / 1_000_000)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    print("# Internal JSON scanner benchmark")
    print()
    print(f"- Platform: `{platform.platform()}`")
    print(f"- Python: `{platform.python_version()}`")
    print(f"- Workload: {args.entries} archive entries, {args.runs} measured scans")
    print(f"- Median: {statistics.median(samples):.3f} ms")
    print(f"- Minimum: {min(samples):.3f} ms")
    print(f"- Maximum: {max(samples):.3f} ms")
    print(f"- Peak Python allocation: {peak / 1024:.1f} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
