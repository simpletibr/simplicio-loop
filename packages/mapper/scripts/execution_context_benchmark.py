#!/usr/bin/env python3
"""Small cold/warm benchmark receipt for execution-context production."""

from __future__ import annotations

import argparse
import builtins
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simplicio_mapper.execution_context import build_execution_context  # noqa: E402
from simplicio_mapper.retrieval_index import (  # noqa: E402
    TOKENIZER_POLICY,
    build_retrieval_index,
    select_context_targets,
    serialized_token_count,
)


class _MeasuredFile:
    def __init__(self, handle: Any, counter: dict[str, int]) -> None:
        self._handle = handle
        self._counter = counter

    def __enter__(self) -> _MeasuredFile:
        self._handle.__enter__()
        return self

    def __exit__(self, *args: Any) -> Any:
        return self._handle.__exit__(*args)

    def __iter__(self):
        return iter(self._handle)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._handle, name)

    def read(self, *args: Any, **kwargs: Any) -> Any:
        value = self._handle.read(*args, **kwargs)
        self._counter["bytes_read"] += len(value.encode("utf-8")) if isinstance(value, str) else len(value)
        return value

    def readlines(self, *args: Any, **kwargs: Any) -> Any:
        values = self._handle.readlines(*args, **kwargs)
        self._counter["bytes_read"] += sum(
            len(value.encode("utf-8")) if isinstance(value, str) else len(value) for value in values
        )
        return values


def _peak_rss_bytes() -> tuple[int | None, str | None]:
    try:
        import resource

        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ImportError, OSError) as error:
        return None, f"resource_ru_maxrss_unavailable:{type(error).__name__}"
    multiplier = 1 if sys.platform == "darwin" else 1024
    return int(value * multiplier), None


def _metric(value: int | float | None, reason: str | None = None) -> dict[str, Any]:
    return {"value": value, "unavailable_reason": reason}


def _measure(callable_: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    counter = {"files_opened": 0, "bytes_read": 0}
    original_open = builtins.open

    def measured_open(*args: Any, **kwargs: Any) -> _MeasuredFile:
        counter["files_opened"] += 1
        return _MeasuredFile(original_open(*args, **kwargs), counter)

    started = time.perf_counter_ns()
    with patch("builtins.open", measured_open):
        payload = callable_()
    latency_ms = (time.perf_counter_ns() - started) / 1_000_000
    peak_rss, rss_reason = _peak_rss_bytes()
    return {
        "bytes_read": _metric(counter["bytes_read"]),
        "files_opened": _metric(counter["files_opened"]),
        "latency_ms": _metric(round(latency_ms, 6)),
        "peak_rss_bytes": _metric(peak_rss, rss_reason),
        "serialized_tokens": _metric(serialized_token_count(payload)),
    }


def benchmark_callable(callable_: Callable[[], dict[str, Any]], *, runs: int = 2) -> dict[str, Any]:
    if runs < 2:
        raise ValueError("runs must be at least 2")
    cold = _measure(callable_)
    warm_measurements = [_measure(callable_) for _ in range(runs - 1)]
    warm: dict[str, Any] = {}
    for metric_name in cold:
        samples = [measurement[metric_name]["value"] for measurement in warm_measurements]
        available = [value for value in samples if value is not None]
        reasons = [
            measurement[metric_name]["unavailable_reason"]
            for measurement in warm_measurements
            if measurement[metric_name]["unavailable_reason"]
        ]
        warm[metric_name] = _metric(
            statistics.median(available) if available else None,
            ";".join(sorted(set(reasons))) if reasons else None,
        )
    return {
        "schema": "simplicio.execution-context-benchmark/v1",
        "runs": runs,
        "measurements": {"cold": cold, "warm": warm},
        "cold_semantics": "first builder call in the current process",
        "warm_semantics": "median of subsequent same-process builder calls",
        "rss_semantics": (
            "resource.ru_maxrss process high-water mark observed after each call; "
            "not an allocation delta for the builder"
        ),
        "environment": {
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "process_id": os.getpid(),
            "process_model": "current-process",
            "python_version": platform.python_version(),
            "tokenizer_policy": TOKENIZER_POLICY,
        },
    }


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _benchmark_fixture(fixture: Path, *, runs: int) -> dict[str, Any]:
    source = fixture / "source"
    artifacts = fixture / "artifacts"
    project_map = _load(artifacts / "project-map.json")
    symbol_index = _load(artifacts / "symbol-index.json")
    call_graph = _load(artifacts / "call-graph.json")
    architecture = _load(artifacts / "architecture-inventory.json")
    precedents = _load(artifacts / "precedent-index.json")
    retrieval = build_retrieval_index(
        project_map,
        symbol_index=symbol_index,
        call_graph=call_graph,
        root=str(source),
    )
    selection = select_context_targets(
        str(source),
        project_map,
        goal="Implement AC-1 greet",
        target="src/app.py",
        symbol_index=symbol_index,
        call_graph=call_graph,
        retrieval_index=retrieval,
        token_budget=8000,
    )

    def build() -> dict[str, Any]:
        return build_execution_context(
            str(source),
            goal="Implement AC-1 greet",
            task_fingerprint="benchmark-task",
            acceptance_criteria=["AC-1"],
            project_map=project_map,
            symbol_index=symbol_index,
            call_graph=call_graph,
            architecture_inventory=architecture,
            precedent_index=precedents,
            selection=selection,
            token_budget=8000,
        )

    receipt = benchmark_callable(build, runs=runs)
    receipt["fixture"] = os.path.relpath(fixture, ROOT).replace(os.sep, "/")
    return receipt


def benchmark_fixture_subprocess(fixture: Path, *, runs: int = 3) -> dict[str, Any]:
    """Measure the builder in a fresh interpreter instead of the caller process."""
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--fixture-root",
        str(fixture.resolve()),
        "--runs",
        str(runs),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode:
        raise RuntimeError(
            f"benchmark worker failed with exit {completed.returncode}: {completed.stderr.strip()}"
        )
    receipt = json.loads(completed.stdout)
    receipt["cold_semantics"] = "first builder call in a fresh subprocess"
    receipt["environment"]["process_model"] = "fresh-subprocess"
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=ROOT / "simplicio_mapper/contracts/mapper-artifacts/v1/fixtures/python-minimal",
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    fixture = args.fixture_root.resolve()
    receipt = (
        _benchmark_fixture(fixture, runs=args.runs)
        if args.worker
        else benchmark_fixture_subprocess(fixture, runs=args.runs)
    )
    if not args.worker:
        receipt["environment"].pop("process_id", None)
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
