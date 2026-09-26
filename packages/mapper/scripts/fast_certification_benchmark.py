#!/usr/bin/env python3
"""Raw cold/warm/incremental certification benchmark; no savings claim."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from pathlib import Path

from simplicio_mapper.fast_certification import certify_fast

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "simplicio_mapper" / "contracts" / "fast-certification" / "v1" / "fixtures"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--out", default="docs/evidence/fast-certification-benchmark.json")
    args = parser.parse_args()
    if args.runs < 10:
        parser.error("--runs must be >= 10")
    samples = []
    mapper = str(FIXTURES / "golden-corpus.json")
    fast = str(FIXTURES / "golden-fast.json")
    for repository_size, multiplier in (("small", 1), ("medium", 5), ("large", 20)):
        for mode in ("cold", "warm", "incremental"):
            for run in range(args.runs):
                started = time.perf_counter()
                result = None
                for _ in range(multiplier if mode != "incremental" else 1):
                    result = certify_fast(mapper, fast)
                samples.append(
                    {
                        "repository_size": repository_size,
                        "mode": mode,
                        "run": run + 1,
                        "elapsed_seconds": time.perf_counter() - started,
                        "status": result["status"],
                    }
                )
    payload = {
        "schema": "simplicio.fast-certification-benchmark/v1",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "corpus": "simplicio_mapper/contracts/fast-certification/v1/fixtures/golden-corpus.json",
        },
        "runs": args.runs,
        "samples": samples,
        "medians": {
            f"{size}:{mode}": statistics.median(
                item["elapsed_seconds"]
                for item in samples
                if item["repository_size"] == size and item["mode"] == mode
            )
            for size in ("small", "medium", "large")
            for mode in ("cold", "warm", "incremental")
        },
        "claim": None,
    }
    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
