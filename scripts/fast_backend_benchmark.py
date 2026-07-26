#!/usr/bin/env python3
"""Raw Mapper-vs-FastBackend adapter overhead benchmark (#358)."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simplicio_mapper.fast_backend import resolve_backend  # noqa: E402


def _measure(action, runs: int) -> list[float]:
    values = []
    for _ in range(runs):
        started = time.perf_counter_ns()
        action()
        values.append((time.perf_counter_ns() - started) / 1_000_000)
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--out")
    args = parser.parse_args()
    if args.runs < 10:
        parser.error("--runs must be >= 10")
    fixture = ROOT / "contracts" / "fast-context" / "v1" / "fixtures" / "cross-language.json"
    local = {
        "project_map": {"product": {"name": "benchmark"}, "files": []},
        "symbol_index": {"symbols": []},
        "call_graph": {"edges": []},
        "architecture_inventory": {"modules": [], "layers": []},
    }
    mapper = _measure(
        lambda: resolve_backend(root=str(ROOT), local_artifacts=local, mode="mapper"),
        args.runs,
    )
    fast = _measure(
        lambda: resolve_backend(
            root=str(ROOT), local_artifacts=local, mode="fast", manifest_path=str(fixture)
        ),
        args.runs,
    )
    payload = {
        "schema": "simplicio.fast-backend-benchmark/v1",
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "runs": args.runs,
        "mapper_ms": mapper,
        "fast_adapter_ms": fast,
        "summary": {
            "mapper_median_ms": statistics.median(mapper),
            "fast_adapter_median_ms": statistics.median(fast),
        },
        "claim": "adapter overhead only; no end-to-end speedup is claimed",
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
