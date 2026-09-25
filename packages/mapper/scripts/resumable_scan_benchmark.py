#!/usr/bin/env python3
"""Reproducible large-repository bounded-timeout/resume benchmark (#357)."""

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

SCHEMA = "simplicio.resumable-scan-benchmark/v1"


def _materialize(root: Path, files: int) -> None:
    (root / "package.json").write_text('{"name":"resumable-scan-benchmark"}\n', encoding="utf-8")
    for index in range(files):
        path = root / "src" / f"group-{index % 32:02d}" / f"module_{index:05d}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"def value_{index}(seed: int) -> int:\n    return seed + {index}\n",
            encoding="utf-8",
        )


def run_benchmark(*, files: int, runs: int, timeout: int) -> dict:
    samples: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="mapper-resumable-scan-") as temporary:
        root = Path(temporary)
        _materialize(root, files)
        for ordinal in range(runs):
            started = time.perf_counter()
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "simplicio_mapper.cli",
                    "scan",
                    str(root),
                    "--sync",
                    "--timeout",
                    str(timeout),
                    "--json",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=max(30, timeout + 20),
            )
            elapsed = time.perf_counter() - started
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            partial = json.loads((root / ".simplicio" / "partial-scan.json").read_text(encoding="utf-8"))
            state = json.loads((root / ".simplicio" / "index-state.json").read_text(encoding="utf-8"))
            samples.append(
                {
                    "run": ordinal + 1,
                    "elapsed_seconds": round(elapsed, 6),
                    "exit_code": result.returncode,
                    "phase": payload["phase"],
                    "resuming": bool(payload["deep"].get("resuming")),
                    "partial_schema": partial["schema"],
                    "completeness": state["completeness"],
                    "files_discovered": state["progress"]["files_discovered"],
                    "eta_seconds": state["progress"]["eta_seconds"],
                }
            )
    elapsed_values = [sample["elapsed_seconds"] for sample in samples]
    return {
        "schema": SCHEMA,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
        },
        "config": {"files": files, "runs": runs, "timeout_seconds": timeout},
        "summary": {
            "min_seconds": min(elapsed_values),
            "median_seconds": statistics.median(elapsed_values),
            "max_seconds": max(elapsed_values),
            "timeouts": sum(sample["phase"] == "timeout" for sample in samples),
            "resumed_runs": sum(sample["resuming"] for sample in samples),
        },
        "samples": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=2500)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=0)
    parser.add_argument("--out")
    args = parser.parse_args()
    if args.files < 1 or args.runs < 10 or args.timeout < 0:
        parser.error("--files must be positive, --runs must be >=10, and --timeout must be >=0")
    payload = run_benchmark(files=args.files, runs=args.runs, timeout=args.timeout)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.out:
        destination = Path(args.out)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
