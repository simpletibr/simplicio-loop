#!/usr/bin/env python3
"""Record raw 1/5/20-slot Fast handoff timings; makes no speedup claim."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from simplicio_mapper.fast_handoff import build_fast_handoff


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--out", default="docs/evidence/fast-handoff-benchmark.json")
    args = parser.parse_args()
    samples = []
    for slots in (1, 5, 20):
        for run in range(args.runs):
            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=slots) as pool:
                list(pool.map(lambda _: build_fast_handoff(args.root), range(slots)))
            samples.append(
                {"slots": slots, "run": run + 1, "elapsed_seconds": time.perf_counter() - started}
            )
    payload = {
        "schema": "simplicio.fast-handoff-benchmark/v1",
        "runs_per_slot_count": args.runs,
        "samples": samples,
        "medians": {
            str(slots): statistics.median(
                item["elapsed_seconds"] for item in samples if item["slots"] == slots
            )
            for slots in (1, 5, 20)
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
