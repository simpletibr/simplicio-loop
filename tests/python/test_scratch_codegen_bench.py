"""Tests for the scratch codegen benchmark harness."""

from __future__ import annotations

import json

from bench.run_scratch_codegen import (
    build_cases,
    capture_llm_baseline,
    load_live_gate_evidence,
    load_llm_baseline,
    load_real_llm_baseline_from_live_gate,
    run_benchmark,
    write_llm_baseline,
    write_reports,
)


def test_scratch_codegen_bench_cases_cover_python_executors() -> None:
    cases = build_cases(include_typescript=False)

    assert {case.expected_executor for case in cases if case.stack_slug == "py-fastapi"} == {
        "python-add-fastapi-route",
        "python-add-orm-field",
        "python-add-pydantic-schema",
        "python-add-pytest-test",
    }


def test_scratch_codegen_bench_cases_cover_typescript_executors() -> None:
    cases = build_cases(include_typescript=True)

    assert {case.expected_executor for case in cases if case.stack_slug == "ts-nextjs"} == {
        "typescript-add-next-page",
        "typescript-add-next-route",
    }


def test_scratch_codegen_bench_cases_cover_live_stack_executors() -> None:
    cases = build_cases(include_typescript=True)

    assert {
        case.expected_executor for case in cases if case.stack_slug in {"go-gin", "rust-axum", "php-laravel"}
    } == {
        "go-gin-crud",
        "php-laravel-crud-routes",
        "rust-axum-crud",
    }


def test_scratch_codegen_bench_runs_keyless_non_typescript_cases(tmp_path) -> None:
    result = run_benchmark(
        work_dir=tmp_path / "bench",
        repeat=1,
        include_typescript=False,
    )

    summary = result["summary"]
    assert summary["total_cases"] == 7
    assert summary["passed_cases"] == 7
    assert summary["tasks_codegen"] == 7
    assert summary["llm_calls"] == 0
    assert summary["planner_calls"] == 0
    assert summary["post_validated_cases"] == 7
    assert summary["post_validation_failed_cases"] == 0
    assert summary["release_gates"]["llm_baseline_present"] is False
    assert summary["release_gates"]["typescript_next_route_compiles_and_responds_json"] is False


def test_scratch_codegen_bench_writes_reports(tmp_path) -> None:
    result = run_benchmark(
        work_dir=tmp_path / "bench",
        repeat=1,
        include_typescript=False,
    )
    json_path = tmp_path / "results.json"
    md_path = tmp_path / "results.md"

    write_reports(result, json_path, md_path)

    assert '"benchmark": "scratch-codegen"' in json_path.read_text(encoding="utf-8")
    assert "# Scratch Codegen Benchmark" in md_path.read_text(encoding="utf-8")


def test_scratch_codegen_bench_compares_captured_llm_baseline(tmp_path) -> None:
    result = run_benchmark(
        work_dir=tmp_path / "bench",
        repeat=1,
        include_typescript=False,
        llm_baseline={
            "source": "fixture",
            "summary": {
                "total_cases": 4,
                "pass_rate": 0.75,
                "avg_llm_ms": 10000,
            },
        },
    )

    summary = result["summary"]
    assert summary["release_gates"]["llm_baseline_present"] is True
    assert summary["release_gates"]["executor_pass_rate_ge_llm"] is True
    assert summary["release_gates"]["latency_reduction_ge_50"] is True
    assert summary["llm_baseline"]["source"] == "fixture"
    assert "LLM baseline pass-rate" not in "\n".join(summary["missing_release_evidence"])


def test_scratch_codegen_bench_consumes_live_gate_evidence(tmp_path) -> None:
    live_gate = {
        "source": "fixture-live-gate",
        "summary": {
            "total_runs": 75,
            "e2e_green": 75,
            "e2e_green_rate": 1.0,
            "release_gates": {
                "full_75_run_matrix": True,
                "e2e_green_ge_80": True,
            },
        },
        "runs": [
            {
                "stack": "py-fastapi",
                "e2e_green": True,
                "scratch_metrics": {
                    "tasks_total": 4,
                    "tasks_codegen": 4,
                    "tasks_llm": 0,
                    "tasks_failed": 0,
                    "avg_codegen_ms": 50,
                },
            }
        ],
    }
    result = run_benchmark(
        work_dir=tmp_path / "bench",
        repeat=1,
        include_typescript=False,
        llm_baseline={
            "source": "fixture-llm",
            "summary": {
                "total_cases": 4,
                "pass_rate": 0.75,
                "avg_llm_ms": 10000,
            },
        },
        live_gate=live_gate,
    )

    summary = result["summary"]
    gates = summary["release_gates"]
    assert summary["live_corpus"]["total_runs"] == 75
    assert summary["live_corpus"]["tasks_codegen"] == 4
    assert summary["live_corpus"]["tasks_llm"] == 0
    assert gates["real_50_scratch_corpus"] is True
    assert gates["real_mechanical_share_ge_30"] is True
    assert gates["real_e2e_green_ge_80"] is True
    assert gates["real_executor_pass_rate_ge_llm"] is None
    assert gates["real_latency_reduction_ge_50"] is None
    assert gates["zero_feature_regression_live"] is True
    assert summary["live_latency_reduction_vs_task_baseline"] >= 0.50
    assert summary["missing_release_evidence"] == [
        "real scratch LLM baseline for executor pass-rate comparison",
        "real scratch LLM baseline for task latency comparison",
    ]


def test_scratch_codegen_bench_loads_live_gate_file(tmp_path) -> None:
    live_gate_path = tmp_path / "live-gate.json"
    live_gate_path.write_text(
        """
        {
          "summary": {
            "total_runs": 50,
            "e2e_green": 50,
            "e2e_green_rate": 1.0,
            "release_gates": {
              "full_75_run_matrix": false,
              "e2e_green_ge_80": true
            }
          },
          "runs": [
            {
              "stack": "py-fastapi",
              "scratch_metrics": {
                "tasks_total": 2,
                "tasks_codegen": 1,
                "tasks_llm": 1,
                "tasks_failed": 0,
                "avg_codegen_ms": 25
              }
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    loaded = load_live_gate_evidence(live_gate_path)

    assert loaded["total_runs"] == 50
    assert loaded["codegen_share"] == 0.5
    assert loaded["avg_codegen_ms"] == 25
    assert loaded["stacks"] == ["py-fastapi"]


def test_scratch_codegen_loads_real_llm_baseline_from_disabled_live_gate(
    tmp_path,
) -> None:
    live_gate_path = tmp_path / "llm-live-gate.json"
    runs = [
        {
            "stack": "py-fastapi",
            "e2e_green": index < 45,
            "scratch_metrics": {
                "tasks_total": 2,
                "tasks_codegen": 0,
                "tasks_llm": 2,
                "tasks_failed": 0 if index < 45 else 1,
                "avg_llm_ms": 1500,
            },
        }
        for index in range(50)
    ]
    live_gate_path.write_text(
        json.dumps(
            {
                "matrix": {
                    "disable_codegen": True,
                    "plan_only": False,
                    "post_verify": True,
                    "skip_install": False,
                },
                "summary": {
                    "total_runs": 50,
                    "e2e_green": 45,
                    "e2e_green_rate": 0.9,
                    "release_gates": {"e2e_green_ge_80": True},
                },
                "runs": runs,
            }
        ),
        encoding="utf-8",
    )

    baseline = load_real_llm_baseline_from_live_gate(live_gate_path)

    assert baseline["total_cases"] == 50
    assert baseline["pass_rate"] == 0.9
    assert baseline["avg_llm_ms"] == 1500
    assert baseline["real_corpus"] is True


def test_scratch_codegen_rejects_live_gate_baseline_without_disable_codegen(
    tmp_path,
) -> None:
    live_gate_path = tmp_path / "codegen-live-gate.json"
    live_gate_path.write_text(
        json.dumps(
            {
                "matrix": {"disable_codegen": False, "post_verify": True},
                "summary": {"total_runs": 1, "e2e_green_rate": 1.0},
                "runs": [],
            }
        ),
        encoding="utf-8",
    )

    try:
        load_real_llm_baseline_from_live_gate(live_gate_path)
    except ValueError as exc:
        assert "--disable-codegen" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected disabled-codegen guard")


def test_scratch_codegen_bench_loads_baseline_file(tmp_path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        '{"summary": {"total_cases": 10, "pass_rate": 0.8, "avg_llm_ms": 9000}}',
        encoding="utf-8",
    )

    baseline = load_llm_baseline(baseline_path)

    assert baseline["total_cases"] == 10
    assert baseline["pass_rate"] == 0.8
    assert baseline["avg_llm_ms"] == 9000


def test_scratch_codegen_bench_captures_llm_baseline_without_codegen(
    tmp_path,
    monkeypatch,
) -> None:
    from simplicio import providers

    generate_calls: list[str] = []

    def fake_generate(prompt: str, feedback: str | None = None) -> str:
        generate_calls.append(prompt)
        return (
            '{"path":"generated.py","content":"'
            "class User:\\n"
            "    email: Mapped[str]\\n\\n"
            "class UserCreate: pass\\n"
            "class UserUpdate: pass\\n"
            "class UserRead: pass\\n\\n"
            "@router.get('/users/{id}')\\n"
            "async def read_user(): pass\\n\\n"
            "from src.utils.math_ops import double\\n"
            "def test_double():\\n"
            "    assert double(2) == 4\\n"
            "package http\\n"
            'import \\"github.com/gin-gonic/gin\\"\\n'
            "func NewRouter() {}\\n"
            '\\"/condo_units\\"\\n'
            "c.JSON\\n"
            "use axum::Router;\\n"
            "struct CondoUnit;\\n"
            "Router::new()\\n"
            "condo_units_crud_routes_work\\n"
            "<?php\\n"
            "Route::get('/condo_units', fn () => []);\\n"
            "Route::post('/condo_units', fn () => response()->json([], 201));\\n"
            "JsonResponse\\n"
            '"}'
        )

    monkeypatch.setenv("SIMPLICIO_MODEL", "fake-llm/baseline")
    monkeypatch.setattr(providers, "generate", fake_generate)

    baseline = capture_llm_baseline(
        work_dir=tmp_path / "baseline",
        repeat=1,
        include_typescript=False,
    )

    summary = baseline["summary"]
    assert summary["total_cases"] == 7
    assert summary["passed_cases"] == 7
    assert summary["pass_rate"] == 1.0
    assert summary["avg_llm_ms"] >= 0
    assert summary["model"] == "fake-llm/baseline"
    assert len(generate_calls) == 7
    assert all(row["execution_mode"] == "llm" for row in baseline["cases"])

    baseline_path = tmp_path / "captured-baseline.json"
    write_llm_baseline(baseline, baseline_path)
    loaded = load_llm_baseline(baseline_path)
    assert loaded["pass_rate"] == 1.0
    assert loaded["avg_llm_ms"] > 0


def test_scratch_codegen_bench_requires_model_for_baseline(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_MODEL", raising=False)

    try:
        capture_llm_baseline(
            work_dir=tmp_path / "baseline",
            repeat=1,
            include_typescript=False,
        )
    except RuntimeError as exc:
        assert "SIMPLICIO_MODEL" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected missing model to block baseline capture")


def test_scratch_codegen_bench_writes_captured_baseline(tmp_path, monkeypatch) -> None:
    baseline = {
        "benchmark": "scratch-codegen-llm-baseline",
        "summary": {
            "total_cases": 4,
            "pass_rate": 0.5,
            "avg_llm_ms": 12000,
        },
    }
    json_path = tmp_path / "baseline.json"

    write_llm_baseline(baseline, json_path)
    loaded = load_llm_baseline(json_path)

    assert loaded["total_cases"] == 4
    assert loaded["pass_rate"] == 0.5
    assert loaded["avg_llm_ms"] == 12000
