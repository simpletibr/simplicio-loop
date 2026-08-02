#!/usr/bin/env python3
"""Measure real multiprocess transaction writers for issue #498."""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
WRITER_COUNTS = (1, 10, 50)

_WORKER = """
import json, sys
from simplicio.changeset_v2 import execute_changeset
root, index = sys.argv[1], int(sys.argv[2])
plan = {
    "schema": "simplicio.fast.changeset/v2",
    "changeset_id": f"issue-498-{index}",
    "correlation_id": f"issue-498-{index}",
    "generation": "benchmark-generation",
    "allowlist": [f"writer-{index}.txt"],
    "operations": [{"kind": "create", "path": f"writer-{index}.txt", "content": "ok\\n"}],
}
result = execute_changeset(plan, root=root, apply=True)
print(json.dumps({"status": result.get("status"), "state": (result.get("transaction") or {}).get("state")}))
"""


def _batch_once(writer_count: int) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(_REPO_ROOT), env.get("PYTHONPATH", "")) if item
    )
    with tempfile.TemporaryDirectory(prefix=f"issue-498-lock-{writer_count}-") as raw_root:
        root = Path(raw_root)
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", _WORKER, str(root), str(index)],
                cwd=_REPO_ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for index in range(writer_count)
        ]
        results = [process.communicate(timeout=60) for process in processes]
        failures = []
        for index, (process, (stdout, stderr)) in enumerate(zip(processes, results, strict=True)):
            if process.returncode != 0:
                failures.append({"index": index, "returncode": process.returncode, "stderr": stderr[-500:]})
                continue
            try:
                result = json.loads(stdout)
            except json.JSONDecodeError:
                failures.append({"index": index, "stdout": stdout[-500:], "stderr": stderr[-500:]})
                continue
            if result != {"status": "ok", "state": "COMMITTED"}:
                failures.append({"index": index, "result": result})
        if failures:
            raise RuntimeError(f"multiprocess transaction batch failed: {failures}")
        if len(list(root.glob("writer-*.txt"))) != writer_count:
            raise RuntimeError("multiprocess batch did not materialize every writer output")


def _measure(writer_count: int, repeats: int) -> dict[str, Any]:
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        _batch_once(writer_count)
        samples.append((time.perf_counter() - started) * 1000)
    ordered = sorted(samples)
    return {
        "writers": writer_count,
        "status": "PASS",
        "repeats": repeats,
        "p50_ms": statistics.median(samples),
        "p95_ms": ordered[max(0, int(len(ordered) * 0.95) - 1)],
        "min_ms": min(samples),
        "max_ms": max(samples),
    }


def run_benchmark(*, repeats: int = 10, writer_counts: tuple[int, ...] = WRITER_COUNTS) -> dict[str, Any]:
    if repeats < 10:
        raise ValueError("issue #498 benchmark requires at least 10 repetitions")
    if not writer_counts or any(count < 1 for count in writer_counts):
        raise ValueError("writer_counts must contain positive values")
    return {
        "schema": "simplicio.dev-cli.issue-498-lock-benchmark/v1",
        "issue": 498,
        "repeats": repeats,
        "writer_counts": list(writer_counts),
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "rows": [_measure(count, repeats) for count in writer_counts],
        "limitations": [
            "measures end-to-end multiprocess transaction batches, not private kernel lock counters",
            "CPU/RSS/fsync counters are not exposed by the transaction receipt",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_benchmark(repeats=args.repeats)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
