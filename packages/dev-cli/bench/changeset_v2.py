"""Reproducible 10-run changeset-v2 adapter benchmark with raw observations."""

from __future__ import annotations

import json
import statistics
import tempfile
import time
from pathlib import Path

from simplicio.changeset_v2 import benchmark_environment, execute_changeset


def main() -> int:
    observations = []
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "app.py").write_text("old\n", encoding="utf-8")
        changeset = {
            "schema": "simplicio.fast.changeset/v2",
            "changeset_id": "benchmark",
            "generation": "1",
            "allowlist": ["app.py"],
            "operations": [
                {
                    "kind": "replace_range",
                    "path": "app.py",
                    "start_line": 1,
                    "end_line": 1,
                    "text": "new\n",
                }
            ],
        }
        for run in range(10):
            started = time.perf_counter_ns()
            receipt = execute_changeset(changeset, root=root, apply=False)
            observations.append(
                {"run": run + 1, "elapsed_ns": time.perf_counter_ns() - started, "status": receipt["status"]}
            )
    elapsed = [row["elapsed_ns"] for row in observations]
    print(  # noqa: T201 - benchmark CLI emits its machine-readable result
        json.dumps(
            {
                "schema": "simplicio.fast.changeset-benchmark/v1",
                "environment": benchmark_environment(),
                "repetitions": 10,
                "raw": observations,
                "median_ns": statistics.median(elapsed),
                "min_ns": min(elapsed),
                "max_ns": max(elapsed),
                "unavailable": {"savings": "no comparative baseline was measured"},
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
