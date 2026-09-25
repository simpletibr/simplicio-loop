"""plan_compiler_benchmark.py — before/after measurement for issue #166.

Compares two things that both exist in this repo today:

- "before" = today's live task-execution path, `simplicio.pipeline.run_task`,
  the one thing `simplicio-cli` actually runs when a user asks it to do
  work. It shells out (git apply, the verify test command) and calls a
  model (`generate()`).
- "after" = `simplicio.plan_compiler.compile_task_spec_to_plan` (+
  `PlanDAG.validate()`), the new deterministic compile step from issue
  #166. As of this benchmark, plan_compiler has **zero call sites** in
  `cli.py`/`pipeline.py` (see `docs/plan-compiler.md`, "Scope of this
  slice") — it is not wired into the live execution path yet.

That asymmetry means this is NOT an apples-to-apples "same task, two
implementations" comparison. It is an honest measurement of two different
things: what the live path costs today, and what the new compile-only step
costs in isolation. See `bench/PLAN_COMPILER_BENCHMARK.md` for the
before/after write-up and the explicit "what remains unproven" section
(issue #166 ACs: "Benchmark publica processos, chamadas, tokens, p50/p95 e
task success antes/depois" and "Falha de hipótese vira resultado
documentado").

Run directly:

    python3 bench/plan_compiler_benchmark.py

No new dependencies: stdlib only (statistics, subprocess, tempfile,
unittest.mock) plus the `simplicio` package already in this repo.
"""

from __future__ import annotations

import json
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from simplicio import pipeline  # noqa: E402
from simplicio.plan_compiler import PlanDAG, compile_task_spec_to_plan  # noqa: E402
from simplicio.plan_compiler.compile_task_spec import PlanCompilationError  # noqa: E402
from simplicio.task_spec import TaskSpec  # noqa: E402

LEGACY_ITERATIONS = 5
COMPILE_REPEATS_PER_CASE = 40


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _percentile(samples: list[float], pct: float) -> float:
    """Nearest-rank percentile — no numpy/pandas dependency."""
    if not samples:
        return 0.0
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0, min(len(ordered) - 1, int(round(pct / 100.0 * (len(ordered) - 1)))))
    return ordered[rank]


def _stats(samples_s: list[float]) -> dict[str, float]:
    samples_ms = [s * 1000.0 for s in samples_s]
    return {
        "n": len(samples_ms),
        "p50_ms": round(_percentile(samples_ms, 50), 3),
        "p95_ms": round(_percentile(samples_ms, 95), 3),
        "mean_ms": round(statistics.fmean(samples_ms), 3) if samples_ms else 0.0,
        "min_ms": round(min(samples_ms), 3) if samples_ms else 0.0,
        "max_ms": round(max(samples_ms), 3) if samples_ms else 0.0,
    }


@contextmanager
def _count_calls(target: object, attr: str) -> Iterator[Callable[[], int]]:
    """Wrap ``target.attr`` to count invocations while still calling through."""
    original = getattr(target, attr)
    counter = {"n": 0}

    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        counter["n"] += 1
        return original(*args, **kwargs)

    setattr(target, attr, _wrapped)
    try:
        yield lambda: counter["n"]
    finally:
        setattr(target, attr, original)


@contextmanager
def _forbid_subprocess_and_network() -> Iterator[None]:
    """Raise immediately if the wrapped code opens a socket or a subprocess.

    Same effect-freedom proof pattern as
    ``tests/python/test_plan_compiler_dry_run.py`` (issue #166 slice 3),
    reused here so the benchmark's "0 calls" claim is asserted, not just
    counted-and-hoped.
    """

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("plan_compiler compile-only path must not shell out or hit the network")

    orig_socket = socket.socket
    orig_run = subprocess.run
    orig_popen = subprocess.Popen
    socket.socket = _forbidden  # type: ignore[assignment]
    subprocess.run = _forbidden  # type: ignore[assignment]
    subprocess.Popen = _forbidden  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket = orig_socket
        subprocess.run = orig_run
        subprocess.Popen = orig_popen


# --------------------------------------------------------------------------- #
# "Before": today's live pipeline path (simplicio.pipeline.run_task)
# --------------------------------------------------------------------------- #

_FAKE_DIFF = "\n".join(
    [
        "diff --git a/app.py b/app.py",
        "--- a/app.py",
        "+++ b/app.py",
        "@@ -1 +1 @@",
        "-old",
        "+new",
        "",
        "TEST: pytest -q",
    ]
)


def _run_legacy_pipeline_once() -> dict[str, Any]:
    """One iteration of the real `pipeline.run_task` happy path.

    Mirrors `tests/python/test_mapping_retry_flow.py::
    test_run_task_surfaces_primary_verify_receipt_from_transaction`: a fake
    `generate()` returns a fixed unified diff, `git apply` and the verify
    test command run for real via subprocess, and impact tests are stubbed
    to "not needed" (the impact-test subprocess call is a real, separate
    cost this benchmark does not hide — see the report's caveats section).
    """
    with tempfile.TemporaryDirectory(prefix="plan-compiler-bench-") as tmp:
        root = Path(tmp)
        (root / "app.py").write_text("old\n", encoding="utf-8")

        env_backup = {
            key: os.environ.get(key)
            for key in ("SIMPLICIO_DISABLE_RUN_LOG", "SIMPLICIO_TEST_CMD")
        }
        os.environ["SIMPLICIO_DISABLE_RUN_LOG"] = "1"
        os.environ["SIMPLICIO_TEST_CMD"] = (
            f"{sys.executable} -c "
            "\"from pathlib import Path; import sys; "
            "sys.exit(0 if Path('app.py').read_text() == 'new\\n' else 1)\""
        )

        orig_build_prompt = pipeline.build_prompt
        orig_generate = pipeline.generate
        orig_run_impact_tests = pipeline._run_impact_tests
        pipeline.build_prompt = lambda *args, **kwargs: "prompt"  # type: ignore[assignment]
        pipeline.generate = lambda *args, **kwargs: _FAKE_DIFF  # type: ignore[assignment]
        pipeline._run_impact_tests = lambda *a, **k: {  # type: ignore[assignment]
            "status": "no_callers_found",
            "callers": [],
            "tests_run": [],
            "result": pipeline.IMPACT_RESULT_NOT_NEEDED,
        }

        try:
            with (
                _count_calls(subprocess, "run") as subprocess_calls,
                _count_calls(pipeline, "generate") as generate_calls,
            ):
                start = time.perf_counter()
                result = pipeline.run_task(
                    str(root),
                    "python",
                    "change app",
                    "app.py",
                    "- behavior proven",
                    "- keep compatibility",
                    quiet=True,
                )
                elapsed_s = time.perf_counter() - start
                return {
                    "elapsed_s": elapsed_s,
                    "subprocess_calls": subprocess_calls(),
                    "model_calls": generate_calls(),
                    "success": bool(result.get("applied") is True),
                }
        finally:
            pipeline.build_prompt = orig_build_prompt
            pipeline.generate = orig_generate
            pipeline._run_impact_tests = orig_run_impact_tests
            for key, value in env_backup.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def benchmark_legacy_pipeline(iterations: int = LEGACY_ITERATIONS) -> dict[str, Any]:
    runs = [_run_legacy_pipeline_once() for _ in range(iterations)]
    latencies_s = [r["elapsed_s"] for r in runs]
    successes = sum(1 for r in runs if r["success"])
    return {
        "path": "pipeline.run_task (today's live execution path)",
        "iterations": iterations,
        "latency": _stats(latencies_s),
        "subprocess_calls_per_run": [r["subprocess_calls"] for r in runs],
        "model_calls_per_run": [r["model_calls"] for r in runs],
        "task_success_rate": successes / iterations if iterations else 0.0,
        "successes": successes,
    }


# --------------------------------------------------------------------------- #
# "After": plan_compiler compile-only path
# --------------------------------------------------------------------------- #

_COMPILE_KWARGS = {
    "goal_id": "goal-bench-1",
    "context_snapshot_id": "snap-bench-1",
    "revision": "1",
}


def _representative_task_specs() -> list[TaskSpec]:
    """A handful of representative TaskSpecs spanning AC/verifier count."""
    return [
        TaskSpec(
            task_id="bench-single-ac",
            source={"kind": "argument"},
            source_hash="hash-single",
            language="pt-BR",
            acceptance_criteria=[{"id": "AC1"}],
            verification_commands=[{"command": "pytest tests/python/test_a.py -q"}],
        ),
        TaskSpec(
            task_id="bench-multi-ac",
            source={"kind": "argument"},
            source_hash="hash-multi",
            language="pt-BR",
            acceptance_criteria=[{"id": "AC1"}, {"id": "AC2"}, {"id": "AC3"}],
            verification_commands=[
                {"command": "pytest tests/python/test_b.py -q"},
                {"command": "ruff check simplicio/"},
            ],
        ),
        TaskSpec(
            task_id="bench-budgeted",
            source={"kind": "argument"},
            source_hash="hash-budget",
            language="pt-BR",
            acceptance_criteria=[{"id": "AC1"}, {"id": "AC2"}],
            verification_commands=[{"command": "pytest tests/python/test_c.py -q"}],
        ),
    ]


def _compile_once(task_spec: TaskSpec) -> dict[str, Any]:
    with _forbid_subprocess_and_network():
        start = time.perf_counter()
        plan, effects, verifications = compile_task_spec_to_plan(task_spec, **_COMPILE_KWARGS)
        plan.validate(effects=effects, verifications=verifications)
        payload = plan.to_dict()
        restored = PlanDAG.from_dict(payload)
        restored.validate(effects=effects, verifications=verifications)
        elapsed_s = time.perf_counter() - start
    return {"elapsed_s": elapsed_s, "success": True}


def benchmark_plan_compiler(repeats_per_case: int = COMPILE_REPEATS_PER_CASE) -> dict[str, Any]:
    task_specs = _representative_task_specs()
    latencies_s: list[float] = []
    successes = 0
    total = 0
    for task_spec in task_specs:
        for _ in range(repeats_per_case):
            total += 1
            try:
                outcome = _compile_once(task_spec)
                latencies_s.append(outcome["elapsed_s"])
                if outcome["success"]:
                    successes += 1
            except PlanCompilationError:
                # Would only happen for a malformed fixture; none of the
                # fixtures above are malformed, so this branch documents
                # the failure mode without silently swallowing it.
                pass
    return {
        "path": "compile_task_spec_to_plan + PlanDAG.validate (compile-only, issue #166)",
        "task_spec_cases": [ts.task_id for ts in task_specs],
        "repeats_per_case": repeats_per_case,
        "iterations": total,
        "latency": _stats(latencies_s),
        "subprocess_calls_per_run": [0] * total,
        "model_calls_per_run": [0] * total,
        "compile_success_rate": successes / total if total else 0.0,
        "successes": successes,
    }


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def run_benchmark() -> dict[str, Any]:
    legacy = benchmark_legacy_pipeline()
    compiled = benchmark_plan_compiler()
    return {
        "schema": "simplicio.dev-cli-plan-compiler-benchmark/v1",
        "issue": 166,
        "before_pipeline_run_task": legacy,
        "after_plan_compiler_compile_only": compiled,
        "note": (
            "plan_compiler has zero call sites in cli.py/pipeline.py as of this run "
            "(see docs/plan-compiler.md). This is a measurement of the live path today "
            "vs. the new compile-only step in isolation, not a same-task A/B of two "
            "wired-in execution modes. See bench/PLAN_COMPILER_BENCHMARK.md."
        ),
    }


def main() -> None:
    report = run_benchmark()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
