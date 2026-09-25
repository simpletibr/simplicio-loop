"""Measure the bounded DeliveryEngine semantic path against explicit legacy mode."""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from simplicio_fast.delivery import DeliveryEngine
from simplicio_fast.engine import select_engine
from simplicio_fast.snapshot import build_snapshot


SCHEMA = "simplicio.fast.delivery-context-benchmark/v1"
REPETITIONS = 30


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def run() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="simplicio-fast-delivery-240-") as directory:
        root = Path(directory)
        for index in range(8):
            (root / f"module_{index}.py").write_text(
                f"def user_note_{index}():\n    return 'user'\n", encoding="utf-8"
            )
        (root / "target.py").write_text(
            "def authenticate_user(credentials):\n    return credentials\n", encoding="utf-8"
        )
        snapshot = root / "project.sfast"
        build_snapshot(root, snapshot)
        engine_receipt = select_engine("python").receipt()
        results: dict[str, Any] = {}
        for mode in ("semantic", "legacy-regex"):
            cold: list[float] = []
            warm: list[float] = []
            semantic_tokens: list[int] = []
            legacy_tokens: list[int] = []
            selected_files: list[list[str]] = []
            for repetition in range(REPETITIONS):
                cache = root / f"cache-{mode}-{repetition}"
                delivery = DeliveryEngine(root, snapshot, cache)
                started = time.perf_counter()
                delivery.prepare(
                    "authenticate user",
                    profile="loop-standalone",
                    engine_receipt=engine_receipt,
                    selection_mode=mode,
                    tokenizer_id="whitespace-v1",
                    tokenizer=lambda text: len(text.split()),
                )
                cold.append((time.perf_counter() - started) * 1000)
                started = time.perf_counter()
                second = delivery.prepare(
                    "authenticate user",
                    profile="loop-standalone",
                    engine_receipt=engine_receipt,
                    selection_mode=mode,
                    tokenizer_id="whitespace-v1",
                    tokenizer=lambda text: len(text.split()),
                )
                warm.append((time.perf_counter() - started) * 1000)
                token_count = int(second["context"]["tokens"])
                (semantic_tokens if mode == "semantic" else legacy_tokens).append(token_count)
                selected_files.append([item["file"] for item in second["context"]["selected"]])
            results[mode] = {
                "cold_median_ms": statistics.median(cold),
                "cold_p95_ms": percentile(cold, 0.95),
                "warm_median_ms": statistics.median(warm),
                "warm_p95_ms": percentile(warm, 0.95),
                "tokens_median": statistics.median(semantic_tokens if mode == "semantic" else legacy_tokens),
                "selected_files": selected_files[0],
                "repetitions": REPETITIONS,
            }
        semantic = results["semantic"]
        legacy = results["legacy-regex"]
        return {
            "schema": SCHEMA,
            "status": "partial",
            "scope": "synthetic_local_corpus",
            "reason": "real_historical_corpus_and_downstream_success_not_collected",
            "environment": {"platform": platform.platform(), "python": platform.python_version()},
            "results": results,
            "semantic_token_reduction_vs_legacy": 1 - semantic["tokens_median"] / legacy["tokens_median"] if legacy["tokens_median"] else None,
            "semantic_selected_files": semantic["selected_files"],
            "legacy_selected_files": legacy["selected_files"],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run()
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
