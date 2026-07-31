"""Measure cold, warm, and incremental scoped-context performance honestly."""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simplicio_mapper.scoped_context import PERFORMANCE_THRESHOLD_MS, build_scoped_context


def _invoke(root: Path, cache: Path, task: str, changed: tuple[str, ...] = ()) -> dict[str, float | int | str]:
    started = time.perf_counter()
    payload = build_scoped_context(
        str(root),
        target_hints=["src/target.py"],
        task_fingerprint=task,
        changed_paths=changed,
        cache_root=str(cache),
        start_background=False,
    )
    metrics = payload["metrics"]
    return {
        "wall_ms": round((time.perf_counter() - started) * 1000, 3),
        "cpu_ms": float(metrics["cpu_ms"]),
        "parsed_files": int(metrics["files_parsed"]),
        "reused_files": int(metrics["files_reused"]),
        "artifact_files_parsed": int(metrics["artifact_files_parsed"]),
        "artifact_bytes": int(metrics["artifact_bytes"]),
        "cache": str(metrics["cache"]),
    }


def _summary(samples: list[dict[str, float | int | str]]) -> dict[str, object]:
    walls = sorted(float(sample["wall_ms"]) for sample in samples)
    cpus = sorted(float(sample["cpu_ms"]) for sample in samples)
    p95_index = min(len(walls) - 1, max(0, math.ceil(len(walls) * 0.95) - 1))
    return {
        "repetitions": len(samples),
        "wall_ms": {
            "avg": round(sum(walls) / len(walls), 3),
            "median": round(walls[len(walls) // 2], 3),
            "p95": round(walls[p95_index], 3),
            "max": round(max(walls), 3),
        },
        "cpu_ms": {
            "avg": round(sum(cpus) / len(cpus), 3),
            "median": round(cpus[len(cpus) // 2], 3),
            "p95": round(cpus[p95_index], 3),
            "max": round(max(cpus), 3),
        },
        "parsed_files": sum(int(sample["parsed_files"]) for sample in samples),
        "reused_files": sum(int(sample["reused_files"]) for sample in samples),
        "artifact_files_parsed": sum(int(sample["artifact_files_parsed"]) for sample in samples),
        "artifact_bytes": sum(int(sample["artifact_bytes"]) for sample in samples),
        "cache_states": sorted({str(sample["cache"]) for sample in samples}),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=2)
    args = parser.parse_args()
    if args.repetitions < 10:
        parser.error("--repetitions must be at least 10")
    if args.warmup < 0:
        parser.error("--warmup must not be negative")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "src").mkdir()
        (root / "tests").mkdir()
        target = root / "src/target.py"
        target.write_text("value = 1\n", encoding="utf-8")
        (root / "src/helper.py").write_text("value = 1\n", encoding="utf-8")
        (root / "src/caller.py").write_text("from src.target import value\n", encoding="utf-8")
        (root / "tests/test_target.py").write_text("def test_target(): pass\n", encoding="utf-8")
        (root / "pyproject.toml").write_text("[build-system]\n", encoding="utf-8")
        artifact_dir = root / ".simplicio"
        artifact_dir.mkdir()
        files = [{"path": path} for path in ("src/target.py", "src/helper.py", "src/caller.py", "tests/test_target.py", "pyproject.toml")]
        (artifact_dir / "project-map.json").write_text(json.dumps({"files": files}), encoding="utf-8")
        (artifact_dir / "symbol-index.json").write_text(json.dumps({"symbols": [{"name": "value", "defined_in": "src/target.py"}]}), encoding="utf-8")
        (artifact_dir / "call-graph.json").write_text(json.dumps({"edges": [{"source_file": "src/target.py", "target_file": "src/helper.py"}, {"source_file": "src/caller.py", "target_file": "src/target.py"}]}), encoding="utf-8")
        (artifact_dir / "architecture-inventory.json").write_text(json.dumps({"schema": "benchmark"}), encoding="utf-8")
        (artifact_dir / "precedent-index.json").write_text(json.dumps({"items": [{"id": "benchmark", "path": "src/target.py", "summary": "target benchmark"}]}), encoding="utf-8")
        cache = root / "cache"

        cold = [_invoke(root, root / f"cold-{index}", f"cold-{index}") for index in range(args.repetitions)]

        _invoke(root, cache, "warm")
        for _ in range(args.warmup):
            _invoke(root, cache, "warm")
        warm = [_invoke(root, cache, "warm") for _ in range(args.repetitions)]

        _invoke(root, cache, "incremental")
        for index in range(args.warmup):
            target.write_text(f"value = {index + 2}\n", encoding="utf-8")
            _invoke(root, cache, "incremental", ("src/target.py",))
        incremental = []
        for index in range(args.repetitions):
            target.write_text(f"value = {index + args.warmup + 2}\n", encoding="utf-8")
            incremental.append(_invoke(root, cache, "incremental", ("src/target.py",)))

    modes = {"cold": _summary(cold), "warm": _summary(warm), "incremental": _summary(incremental)}
    warm_pass = float(modes["warm"]["wall_ms"]["p95"]) <= PERFORMANCE_THRESHOLD_MS
    incremental_pass = float(modes["incremental"]["wall_ms"]["p95"]) <= PERFORMANCE_THRESHOLD_MS
    result = {
        "schema": "simplicio.mapper-scoped-benchmark/v2",
        "repetitions": args.repetitions,
        "warmup_repetitions": args.warmup,
        "threshold_ms": PERFORMANCE_THRESHOLD_MS,
        "gate_metric": "wall_ms.p95",
        "modes": modes,
        "warm_pass": warm_pass,
        "incremental_pass": incremental_pass,
        "cold_wall_avg_ms": modes["cold"]["wall_ms"]["avg"],
        "warm_wall_avg_ms": modes["warm"]["wall_ms"]["avg"],
        "incremental_wall_avg_ms": modes["incremental"]["wall_ms"]["avg"],
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if warm_pass and incremental_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
