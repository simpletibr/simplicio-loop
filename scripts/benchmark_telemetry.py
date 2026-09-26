#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from simplicio_loop.telemetry import benchmark_overhead


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=".simplicio-loop/benchmark/telemetry")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--samples", type=int, default=7)
    args = parser.parse_args()
    receipt = benchmark_overhead(
        Path(args.output_dir), iterations=args.iterations, samples=args.samples
    )
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
