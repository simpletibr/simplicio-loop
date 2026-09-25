"""Record an installed exact-tokenizer provider/model matrix for issue #240."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path
from typing import Any

from simplicio_fast.tokenizers import resolve_tokenizer


SCHEMA = "simplicio.fast.tokenizer-matrix/v1"
PROVIDERS = (
    "tiktoken:cl100k_base",
    "tiktoken:o200k_base",
    "tiktoken:model:gpt-4o",
)
TASKS = (
    ("create-user-validation", "Understand create_user validation and test coverage."),
    ("auth-regression", "Locate the authentication regression and affected tests."),
    ("cache-invalidation", "Explain cache invalidation and changed-path dependencies."),
    ("delivery-budget", "Prepare bounded context for the delivery token budget."),
)
REPETITIONS = 30


def _measure(provider_id: str) -> dict[str, Any]:
    tokenizer = resolve_tokenizer(provider_id)
    if tokenizer is None:
        return {
            "provider": provider_id,
            "status": "unavailable",
            "reason_code": "provider_tokenizer_unavailable",
            "tasks": [],
        }
    rows: list[dict[str, Any]] = []
    for name, task in TASKS:
        samples: list[float] = []
        count = None
        for _ in range(REPETITIONS):
            started = time.perf_counter()
            count = tokenizer(task)
            samples.append((time.perf_counter() - started) * 1000)
        rows.append(
            {
                "name": name,
                "text_sha256": hashlib.sha256(task.encode()).hexdigest(),
                "tokens": count,
                "wall_ms_median": statistics.median(samples),
                "wall_ms_p95": sorted(samples)[int(REPETITIONS * 0.95) - 1],
                "repetitions": REPETITIONS,
            }
        )
    return {
        "provider": provider_id,
        "status": "exact",
        "reason_code": None,
        "tasks": rows,
    }


def run() -> dict[str, Any]:
    providers = [_measure(provider) for provider in PROVIDERS]
    exact = sum(row["status"] == "exact" for row in providers)
    return {
        "schema": SCHEMA,
        "status": "pass" if exact == len(PROVIDERS) else "partial",
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "provider_count": len(PROVIDERS),
            "exact_provider_count": exact,
            "billing_telemetry": "not_observed",
        },
        "providers": providers,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run()
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
