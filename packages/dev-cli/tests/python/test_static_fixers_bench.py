"""Tests for the static fixer benchmark harness."""

from __future__ import annotations

import json
import subprocess

from bench.run_static_fixers import (
    build_cases,
    load_live_gate_evidence,
    run_benchmark,
    run_real_package_manager_probe,
    run_scratch_import_failure_probe,
    write_reports,
)


def test_static_fixer_bench_cases_have_expected_mix() -> None:
    cases = build_cases()

    assert len(cases) == 50
    assert sum(1 for case in cases if case.resolvable) == 40
    assert sum(1 for case in cases if not case.resolvable) == 10


def test_static_fixer_bench_measures_retry_reduction(tmp_path) -> None:
    result = run_benchmark(work_dir=tmp_path / "bench")
    summary = result["summary"]

    assert summary["total_cases"] == 50
    assert summary["passed_cases"] == 50
    assert summary["fixer_resolved_before_retry"] == 40
    assert summary["fixer_resolved_rate"] == 0.8
    assert summary["baseline_llm_calls"] == 100
    assert summary["with_fixer_llm_calls"] == 60
    assert summary["retry_call_reduction"] == 0.4
    assert summary["release_gates"]["real_package_manager_execution"] is False
    assert summary["release_gates"]["real_scratch_corpus"] is False


def test_static_fixer_bench_writes_reports(tmp_path) -> None:
    result = run_benchmark(work_dir=tmp_path / "bench")
    json_path = tmp_path / "results.json"
    md_path = tmp_path / "results.md"

    write_reports(result, json_path, md_path)

    assert '"benchmark": "static-fixers"' in json_path.read_text(encoding="utf-8")
    assert "# Static Fixers Benchmark" in md_path.read_text(encoding="utf-8")


def test_static_fixer_bench_real_package_probe_uses_runner(tmp_path) -> None:
    calls: list[list[str]] = []

    def fake_runner(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    rows = run_real_package_manager_probe(
        work_dir=tmp_path / "real-probe",
        repeat=1,
        runner=fake_runner,
    )

    assert len(rows) == 5
    assert all(row["passed"] for row in rows)
    assert any("pip" in " ".join(call) for call in calls)


def test_static_fixer_bench_records_real_probe_summary(tmp_path) -> None:
    result = run_benchmark(
        work_dir=tmp_path / "bench",
        real_package_manager_probe=True,
        real_probe_repeat=0,
    )

    summary = result["summary"]
    assert summary["real_package_manager_cases"] == 0
    assert summary["release_gates"]["real_package_manager_execution"] is False


def test_static_fixer_bench_repairs_scratch_import_failure(tmp_path) -> None:
    project_dir = tmp_path / "scratch" / "run-01" / "projects" / "static-fixer-import-probe-01"
    calls: list[list[str]] = []

    def fake_runner(argv, **kwargs):
        calls.append(list(argv))
        cwd = kwargs.get("cwd")
        if "simplicio.cli" in argv:
            project_dir.mkdir(parents=True, exist_ok=True)
            (project_dir / "pyproject.toml").write_text(
                '[project]\nname = "probe"\ndependencies = []\n',
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps({"project_dir": str(project_dir)}),
                "",
            )
        if len(argv) >= 4 and argv[1:3] == ["-m", "pip"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if len(argv) >= 3 and argv[1:3] == ["-m", "pytest"]:
            pyproject = project_dir / "pyproject.toml"
            if "boltons" in pyproject.read_text(encoding="utf-8"):
                return subprocess.CompletedProcess(argv, 0, "2 passed\n", "")
            assert cwd == str(project_dir)
            return subprocess.CompletedProcess(
                argv,
                1,
                "ModuleNotFoundError: No module named 'boltons'\n",
                "",
            )
        return subprocess.CompletedProcess(argv, 0, "", "")

    rows = run_scratch_import_failure_probe(
        work_dir=tmp_path / "scratch",
        runner=fake_runner,
    )

    assert len(rows) == 1
    assert rows[0]["initial_failure_observed"] is True
    assert rows[0]["fixer"] == "missing-pip-package"
    assert rows[0]["dependency_declared"] is True
    assert rows[0]["final_pytest_passed"] is True
    assert rows[0]["passed"] is True
    assert any("pip" in " ".join(call) for call in calls)


def test_static_fixer_bench_records_scratch_import_probe_summary(tmp_path) -> None:
    result = run_benchmark(
        work_dir=tmp_path / "bench",
        scratch_import_failure_probe=False,
    )

    summary = result["summary"]
    assert summary["scratch_import_failure_cases"] == 0
    assert summary["release_gates"]["real_scratch_import_failure_repaired"] is False


def test_static_fixer_bench_consumes_live_gate_corpus(tmp_path) -> None:
    live_gate = {
        "source": "fixture-live-gate",
        "summary": {
            "total_runs": 75,
            "e2e_green": 75,
        },
        "runs": [
            {
                "stack": "py-fastapi",
                "goal_index": index,
                "goal": f"CRUD app {index}",
                "returncode": 0,
                "e2e_green": True,
                "post_verify": {
                    "enabled": True,
                    "commands": [
                        {"name": "test", "passed": True},
                        {"name": "lint", "passed": True},
                    ],
                },
            }
            for index in range(1, 76)
        ],
    }

    result = run_benchmark(work_dir=tmp_path / "bench", live_gate=live_gate)
    summary = result["summary"]
    gates = summary["release_gates"]

    assert gates["real_scratch_corpus"] is True
    assert gates["real_eligible_failures_observed"] is False
    assert summary["live_corpus"]["total_runs"] == 75
    assert summary["live_corpus"]["eligible_failure_runs"] == 0
    assert "real 50-scratch corpus" not in "\n".join(summary["missing_release_evidence"])
    assert "real install/import/lint failures" in "\n".join(summary["missing_release_evidence"])

    live_path = tmp_path / "live-gate.json"
    live_path.write_text(json.dumps(live_gate), encoding="utf-8")
    loaded = load_live_gate_evidence(live_path)
    assert loaded["source"] == "fixture-live-gate"
    assert loaded["e2e_green"] == 75


def test_static_fixer_bench_counts_live_failure_runs(tmp_path) -> None:
    live_gate = {
        "runs": [
            {
                "stack": "py-fastapi",
                "goal": "CRUD app",
                "returncode": 1,
                "e2e_green": False,
                "post_verify": {
                    "enabled": True,
                    "commands": [{"name": "test", "passed": False}],
                },
            }
        ]
    }

    result = run_benchmark(work_dir=tmp_path / "bench", live_gate=live_gate)

    assert result["summary"]["live_corpus"]["eligible_failure_runs"] == 1
    assert result["summary"]["live_corpus"]["post_verify_failure_runs"] == 1
    assert result["summary"]["live_corpus"]["scratch_returncode_failure_runs"] == 1
    assert result["summary"]["release_gates"]["real_scratch_corpus"] is False
