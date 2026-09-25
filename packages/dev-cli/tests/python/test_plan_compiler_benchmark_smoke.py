"""Smoke test for bench/plan_compiler_benchmark.py (issue #166).

This is deliberately NOT a CI perf gate — no latency threshold is asserted,
per this repo's convention (see `bench/` — a measurement/reporting tool, not
an enforced budget). It only proves the benchmark script itself imports and
runs to completion with the small case set it ships, and that its own
zero-subprocess-calls claim for the plan_compiler compile-only path holds,
since that claim is the load-bearing part of the benchmark's before/after
write-up (`bench/PLAN_COMPILER_BENCHMARK.md`).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BENCH_SCRIPT = Path(__file__).resolve().parents[2] / "bench" / "plan_compiler_benchmark.py"


def _load_benchmark_module():
    spec = importlib.util.spec_from_file_location("plan_compiler_benchmark", BENCH_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_benchmark_script_runs_and_reports_zero_calls_for_compile_only() -> None:
    module = _load_benchmark_module()

    legacy = module.benchmark_legacy_pipeline(iterations=1)
    assert legacy["successes"] == 1
    assert legacy["task_success_rate"] == 1.0
    assert legacy["subprocess_calls_per_run"][0] >= 2
    assert legacy["model_calls_per_run"] == [1]

    compiled = module.benchmark_plan_compiler(repeats_per_case=1)
    assert compiled["compile_success_rate"] == 1.0
    assert all(count == 0 for count in compiled["subprocess_calls_per_run"])
    assert all(count == 0 for count in compiled["model_calls_per_run"])


def test_run_benchmark_produces_the_documented_schema() -> None:
    module = _load_benchmark_module()

    report = module.run_benchmark()

    assert report["schema"] == "simplicio.dev-cli-plan-compiler-benchmark/v1"
    assert report["issue"] == 166
    assert "before_pipeline_run_task" in report
    assert "after_plan_compiler_compile_only" in report
    assert "zero call sites in cli.py/pipeline.py" in report["note"]
