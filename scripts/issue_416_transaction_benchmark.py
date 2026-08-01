"""Reproducible transaction benchmark for issue #416.

The benchmark compares the legacy in-memory mechanical plan application with
the Dev CLI's recoverable Python transaction.  Optional Fast/Rust lanes are
reported as unavailable rather than being represented by guessed numbers.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Keep the runner reproducible from a source checkout without requiring an
# editable install; installed-wheel smoke remains a separate gate.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from simplicio.changeset_transaction import changeset_digest  # noqa: E402
from simplicio.changeset_v2 import adapt_changeset, execute_changeset  # noqa: E402
from simplicio.mechanical_edit import execute_plan  # noqa: E402

SIZES = (1, 20, 200)


def _changeset(size: int) -> dict[str, Any]:
    return {
        "schema": "simplicio.fast.changeset/v2",
        "changeset_id": f"issue-416-{size}",
        "correlation_id": f"issue-416-{size}",
        "generation": "benchmark-generation",
        "allowlist": [f"file-{index}.txt" for index in range(size)],
        "operations": [
            {
                "kind": "replace_range",
                "path": f"file-{index}.txt",
                "start_line": 1,
                "end_line": 1,
                "text": f"updated-{index}\n",
            }
            for index in range(size)
        ],
    }


def _prepare_root(root: Path, size: int) -> None:
    for index in range(size):
        (root / f"file-{index}.txt").write_text(f"original-{index}\n", encoding="utf-8")


def _direct_once(size: int) -> None:
    changeset = _changeset(size)
    plan = adapt_changeset(changeset)
    with tempfile.TemporaryDirectory(prefix=f"issue-416-direct-{size}-") as directory:
        root = Path(directory)
        _prepare_root(root, size)
        result = execute_plan(plan, root=root, apply=True, allow_native=False)
        if result.get("status") != "ok":
            raise RuntimeError(f"direct lane failed: {result}")


def _transaction_once(size: int) -> None:
    changeset = _changeset(size)
    digest = changeset_digest(changeset)
    with tempfile.TemporaryDirectory(prefix=f"issue-416-transaction-{size}-") as directory:
        root = Path(directory)
        _prepare_root(root, size)
        result = execute_changeset(changeset, root=root, apply=True)
        if result.get("status") != "ok" or result.get("transaction", {}).get("state") != "COMMITTED":
            raise RuntimeError(f"transaction lane failed: {result}")
        if result.get("transaction", {}).get("changeset_digest") != digest:
            raise RuntimeError("transaction lane returned an unexpected changeset digest")


def _measure(fn: Callable[[int], None], size: int, repeats: int) -> dict[str, Any]:
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn(size)
        samples.append((time.perf_counter() - started) * 1000)
    ordered = sorted(samples)
    return {
        "status": "PASS",
        "repeats": repeats,
        "p50_ms": statistics.median(samples),
        "p95_ms": ordered[max(0, int(len(ordered) * 0.95) - 1)],
        "min_ms": min(samples),
        "max_ms": max(samples),
    }


def run_benchmark(*, repeats: int = 10) -> dict[str, Any]:
    if repeats < 10:
        raise ValueError("issue #416 benchmark requires at least 10 repetitions")
    rows: list[dict[str, Any]] = []
    for size in SIZES:
        for lane, function in (
            ("direct_mechanical", _direct_once),
            ("python_transaction", _transaction_once),
        ):
            rows.append({"size": size, "lane": lane, **_measure(function, size, repeats)})
        rows.extend(
            {
                "size": size,
                "lane": lane,
                "status": "UNAVAILABLE",
                "reason": reason,
                "repeats": 0,
            }
            for lane, reason in (
                ("fast_python_apply", "Fast apply adapter is not part of the Dev CLI benchmark contract"),
                ("fast_rust_apply", "Rust/Fast transaction producer artifact is not configured"),
            )
        )
    return {
        "schema": "simplicio.dev-cli.issue-416-transaction-benchmark/v1",
        "issue": 416,
        "repeats": repeats,
        "sizes": list(SIZES),
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "rows": rows,
        "limitations": [
            "direct_mechanical is a baseline, not a production transaction",
            "Fast/Rust apply lanes are unavailable without a producer artifact and are not estimated",
            "fsync/rename/CPU/RSS counters are not exposed by the current transaction receipt",
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
