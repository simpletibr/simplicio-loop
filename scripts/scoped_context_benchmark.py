"""Measure cold, warm, and incremental scoped-context latency."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simplicio_mapper.scoped_context import PERFORMANCE_THRESHOLD_MS, build_scoped_context


def _invoke(root: Path, cache: Path, task: str, changed: tuple[str, ...] = ()) -> tuple[float, dict]:
    started = time.perf_counter()
    payload = build_scoped_context(str(root), target_hints=["src/target.py"], task_fingerprint=task, changed_paths=changed, cache_root=str(cache), start_background=False)
    return (time.perf_counter() - started) * 1000, payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=10)
    args = parser.parse_args()
    if args.repetitions < 10:
        parser.error("--repetitions must be at least 10")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "src").mkdir()
        target = root / "src/target.py"
        target.write_text("value = 1\n", encoding="utf-8")
        cache = root / "cache"
        cold = [_invoke(root, root / f"cold-{index}", f"cold-{index}")[0] for index in range(args.repetitions)]
        warm = [_invoke(root, cache, "warm")[0] for _ in range(args.repetitions)]
        incremental = []
        for index in range(args.repetitions):
            target.write_text(f"value = {index + 2}\n", encoding="utf-8")
            incremental.append(_invoke(root, cache, "warm", ("src/target.py",))[0])
    result = {
        "schema": "simplicio.mapper-scoped-benchmark/v1",
        "repetitions": args.repetitions,
        "threshold_ms": PERFORMANCE_THRESHOLD_MS,
        "cold_avg_ms": sum(cold) / len(cold),
        "cold_max_ms": max(cold),
        "warm_avg_ms": sum(warm) / len(warm),
        "warm_max_ms": max(warm),
        "incremental_avg_ms": sum(incremental) / len(incremental),
        "incremental_max_ms": max(incremental),
        "warm_pass": max(warm) <= PERFORMANCE_THRESHOLD_MS,
        "incremental_pass": max(incremental) <= PERFORMANCE_THRESHOLD_MS,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["warm_pass"] and result["incremental_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
