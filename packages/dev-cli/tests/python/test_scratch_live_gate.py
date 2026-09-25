"""Tests for the live scratch gate runner."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import bench.run_scratch_live_gate as live_gate
from bench.run_scratch_live_gate import (
    CODEGEN_DISABLED_RESULTS_JSON,
    CODEGEN_DISABLED_RESULTS_MD,
    _normalize_skillopt_review,
    _parse_json_stdout,
    _resolve_output_paths,
    _summarize,
    load_skillopt_review_evidence,
    merge_results,
    parse_args,
    run_live_gate,
    write_reports,
)
from bench.run_scratch_release_gate import PILOT_STACKS, RELEASE_GOALS


def _completed(cmd, stdout, returncode=0, stderr=""):
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def _skillopt_review_row(tmp_path, index: int, *, approved: bool = True) -> dict:
    skill = f"generated-skill-{index:02d}"
    skill_path = tmp_path / skill / "SKILL.md"
    skill_path.parent.mkdir()
    skill_path.write_text(
        "\n".join(
            [
                "---",
                f"name: {skill}",
                "auto_generated:",
                "  by: skill-opt",
                "  source_goal: Generate audit workflow",
                "  planner_model: test-planner",
                "  review_required: true",
                "---",
                "",
                f"# {skill}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "skill": skill,
        "path": str(skill_path),
        "sha256": hashlib.sha256(skill_path.read_bytes()).hexdigest(),
        "reviewer": "wesley",
        "approved": approved,
        "reviewed_at": "2026-05-31",
    }


def test_live_gate_runs_plan_only_slice(tmp_path) -> None:
    calls = []

    def fake_runner(cmd, **_kwargs):
        calls.append(cmd)
        assert "--plan-only" in cmd
        return _completed(
            cmd,
            json.dumps(
                {
                    "project_name": "gate-g01-py-fastapi",
                    "tasks": [{"id": "T01", "goal": "add model"}],
                }
            ),
        )

    result = run_live_gate(
        work_dir=tmp_path / "live",
        stacks=("py-fastapi", "ts-nextjs"),
        goals=("CRUD app for condo units",),
        max_runs=1,
        plan_only=True,
        runner=fake_runner,
    )

    summary = result["summary"]
    assert len(calls) == 1
    assert result["matrix"]["selected_runs"] == 1
    assert result["matrix"]["release_planned_runs"] == 75
    assert summary["planner_valid"] == 1
    assert summary["planner_valid_rate"] == 1.0
    assert summary["release_gates"]["scaffold_clean_ge_95"] is None
    assert summary["release_gates"]["release_ready"] is False


def test_live_gate_runs_execution_slice(tmp_path) -> None:
    project_dir = tmp_path / "live" / "projects" / "gate-g01-py-fastapi"
    project_dir.mkdir(parents=True)

    def fake_runner(cmd, **_kwargs):
        if isinstance(cmd, list) and len(cmd) > 2 and cmd[2] in {"pytest", "ruff"}:
            return _completed(cmd, "ok\n")
        if isinstance(cmd, str):
            return _completed(cmd, "", returncode=1, stderr=f"{cmd} not recognized")
        assert "--plan-only" not in cmd
        return _completed(
            cmd,
            json.dumps(
                {
                    "project_dir": str(project_dir),
                    "files_written": ["src/main.py"],
                    "tasks_passed": 2,
                    "tasks_total": 2,
                    "metrics": {
                        "tasks_llm": 0,
                        "tasks_codegen": 2,
                        "lines_generated_total": 12,
                        "lines_modified_total": 3,
                        "lines_added_total": 14,
                        "lines_removed_total": 2,
                        "files_created_total": 2,
                        "files_changed_total": 1,
                    },
                }
            ),
        )

    result = run_live_gate(
        work_dir=tmp_path / "live",
        stacks=("py-fastapi",),
        goals=("CRUD app for condo units",),
        skip_install=True,
        post_verify=True,
        runner=fake_runner,
    )

    row = result["runs"][0]
    summary = result["summary"]
    assert row["planner_valid"] is True
    assert row["scaffold_clean"] is True
    assert row["task_all_passed"] is True
    assert row["e2e_green"] is True
    assert row["scratch_metrics"]["tasks_llm"] == 0
    assert row["line_stats"]["lines_generated"] == 12
    assert row["line_stats"]["lines_modified"] == 3
    assert row["cost_usd"] == 0.0
    assert row["post_verify"]["passed"] is True
    assert summary["scaffold_clean_rate"] == 1.0
    assert summary["e2e_green_rate"] == 1.0
    assert summary["average_cost_usd"] == 0.0
    assert summary["lines_generated_total"] == 12
    assert summary["lines_modified_total"] == 3
    assert summary["avg_lines_generated_per_run"] == 12.0
    assert summary["release_gates"]["average_cost_le_1"] is True
    assert summary["release_gates"]["full_75_run_matrix"] is False


def test_live_gate_reports_missing_post_verify_runtime_tools(tmp_path, monkeypatch) -> None:
    project_dir = tmp_path / "live" / "projects" / "gate-g01-go-gin"
    project_dir.mkdir(parents=True)
    monkeypatch.setattr(live_gate.shutil, "which", lambda _tool: None)

    def fake_runner(cmd, **_kwargs):
        if isinstance(cmd, str):
            return _completed(
                cmd,
                "",
                returncode=1,
                stderr=f"{cmd}: go: not found",
            )
        return _completed(
            cmd,
            json.dumps(
                {
                    "project_dir": str(project_dir),
                    "files_written": ["main.go"],
                    "tasks_passed": 1,
                    "tasks_total": 1,
                }
            ),
        )

    result = run_live_gate(
        work_dir=tmp_path / "live",
        stacks=("go-gin",),
        goals=("CRUD app for condo units",),
        post_verify=True,
        runner=fake_runner,
    )
    json_path = tmp_path / "live.json"
    md_path = tmp_path / "live.md"
    write_reports(result, json_path, md_path)

    row = result["runs"][0]
    preflight = result["summary"]["runtime_tool_preflight"]
    assert preflight["enabled"] is True
    assert preflight["required_tools"] == ["go"]
    assert preflight["missing_tools"] == ["go"]
    assert preflight["checked_commands"] == 2
    assert row["post_verify"]["runtime_tool_preflight"]["missing_tools"] == ["go"]
    assert row["post_verify"]["passed"] is False
    assert row["e2e_green"] is False
    assert result["summary"]["release_gates"]["release_ready"] is False
    assert "- missing runtime tools: `go`" in md_path.read_text(encoding="utf-8")


def test_live_gate_disables_runtime_tool_preflight_without_post_verify(tmp_path, monkeypatch) -> None:
    def fail_if_checked(_tool):
        raise AssertionError("runtime tool preflight should be disabled")

    monkeypatch.setattr(live_gate.shutil, "which", fail_if_checked)

    def fake_runner(cmd, **_kwargs):
        return _completed(
            cmd,
            json.dumps(
                {
                    "project_dir": str(tmp_path),
                    "files_written": ["main.go"],
                    "tasks_passed": 1,
                    "tasks_total": 1,
                }
            ),
        )

    result = run_live_gate(
        work_dir=tmp_path / "live",
        stacks=("go-gin",),
        goals=("CRUD app for condo units",),
        runner=fake_runner,
    )

    preflight = result["summary"]["runtime_tool_preflight"]
    assert preflight["enabled"] is False
    assert preflight["missing_tools"] == []


def test_live_gate_can_disable_codegen_for_llm_baseline(tmp_path) -> None:
    def fake_runner(cmd, **kwargs):
        assert kwargs["env"]["SIMPLICIO_DISABLE_CODEGEN"] == "1"
        return _completed(
            cmd,
            json.dumps(
                {
                    "project_dir": str(tmp_path),
                    "files_written": ["src/main.py"],
                    "tasks_passed": 2,
                    "tasks_total": 2,
                    "metrics": {
                        "tasks_llm": 2,
                        "tasks_codegen": 0,
                        "avg_llm_ms": 1200,
                    },
                }
            ),
        )

    result = run_live_gate(
        work_dir=tmp_path / "live",
        stacks=("py-fastapi",),
        goals=("CRUD app for condo units",),
        disable_codegen=True,
        runner=fake_runner,
    )

    row = result["runs"][0]
    assert result["matrix"]["disable_codegen"] is True
    assert row["codegen_disabled"] is True
    assert row["scratch_metrics"]["tasks_llm"] == 2


def test_live_gate_requires_project_dir_for_post_verify(tmp_path) -> None:
    def fake_runner(cmd, **_kwargs):
        return _completed(
            cmd,
            json.dumps(
                {
                    "files_written": ["src/main.py"],
                    "tasks_passed": 2,
                    "tasks_total": 2,
                }
            ),
        )

    result = run_live_gate(
        work_dir=tmp_path / "live",
        stacks=("py-fastapi",),
        goals=("CRUD app for condo units",),
        post_verify=True,
        runner=fake_runner,
    )

    row = result["runs"][0]
    assert row["e2e_green"] is False
    assert row["post_verify"]["error"] == "missing project_dir"


def test_live_gate_requires_post_verify_for_e2e_metric(tmp_path) -> None:
    def fake_runner(cmd, **_kwargs):
        return _completed(
            cmd,
            json.dumps(
                {
                    "files_written": ["src/main.py"],
                    "tasks_passed": 2,
                    "tasks_total": 2,
                }
            ),
        )

    result = run_live_gate(
        work_dir=tmp_path / "live",
        stacks=("py-fastapi",),
        goals=("CRUD app for condo units",),
        runner=fake_runner,
    )

    row = result["runs"][0]
    summary = result["summary"]
    assert row["task_all_passed"] is True
    assert row["e2e_green"] is None
    assert summary["release_gates"]["e2e_green_ge_80"] is None
    assert "post-scratch stack test/lint verification" in summary["missing_release_evidence"]


def test_live_gate_handles_timeout_bytes_in_reports(tmp_path) -> None:
    def fake_runner(cmd, **_kwargs):
        raise subprocess.TimeoutExpired(cmd, 1, output=b"partial", stderr=b"err")

    result = run_live_gate(
        work_dir=tmp_path / "live",
        stacks=("py-fastapi",),
        goals=("CRUD app for condo units",),
        post_verify=True,
        runner=fake_runner,
    )
    json_path = tmp_path / "timeout.json"
    md_path = tmp_path / "timeout.md"

    row = result["runs"][0]
    assert row["timed_out"] is True
    assert row["stdout_tail"] == "partial"
    assert row["stderr_tail"] == "err"
    assert row["post_verify"]["error"] == "scratch command timed out"
    write_reports(result, json_path, md_path)
    assert '"timed_out": true' in json_path.read_text(encoding="utf-8")


def test_live_gate_marks_malformed_task_counts_failed(tmp_path) -> None:
    def fake_runner(cmd, **_kwargs):
        return _completed(
            cmd,
            json.dumps(
                {
                    "project_dir": str(tmp_path),
                    "files_written": ["src/main.py"],
                    "tasks_passed": "two",
                    "tasks_total": 2,
                }
            ),
        )

    result = run_live_gate(
        work_dir=tmp_path / "live",
        stacks=("py-fastapi",),
        goals=("CRUD app for condo units",),
        runner=fake_runner,
    )

    row = result["runs"][0]
    assert row["planner_valid"] is False
    assert row["task_all_passed"] is False
    assert row["error"] == "tasks_passed must be an integer"


def test_live_gate_full_matrix_requires_official_pairs() -> None:
    rows = [
        {
            "goal": "not an official goal",
            "stack": "py-fastapi",
            "planner_valid": True,
            "scaffold_clean": True,
            "task_all_passed": True,
            "e2e_green": True,
            "duration_s": 1,
            "timed_out": False,
        }
        for _ in range(75)
    ]

    summary = _summarize(rows, 1.0, plan_only=False, post_verify=True)

    assert summary["release_gates"]["full_75_run_matrix"] is False


def test_live_gate_keeps_cost_unknown_when_llm_cost_is_missing() -> None:
    rows = [
        {
            "goal": "CRUD app for condo units with owner contact search",
            "stack": "py-fastapi",
            "planner_valid": True,
            "scaffold_clean": True,
            "task_all_passed": True,
            "e2e_green": True,
            "duration_s": 1,
            "timed_out": False,
            "cost_usd": None,
            "scratch_metrics": {"tasks_llm": 1},
        }
    ]

    summary = _summarize(rows, 1.0, plan_only=False, post_verify=True)

    assert summary["average_cost_usd"] is None
    assert summary["release_gates"]["average_cost_le_1"] is None
    assert "average cost measurement" in summary["missing_release_evidence"]


def test_live_gate_accepts_skillopt_human_review_evidence(tmp_path) -> None:
    reviews = [_skillopt_review_row(tmp_path, index, approved=index <= 8) for index in range(1, 11)]
    review_path = tmp_path / "skillopt-review.json"
    review_path.write_text(json.dumps({"reviews": reviews}), encoding="utf-8")
    rows = [
        {
            "goal": goal,
            "stack": stack,
            "planner_valid": True,
            "scaffold_clean": True,
            "task_all_passed": True,
            "e2e_green": True,
            "duration_s": 1,
            "timed_out": False,
            "cost_usd": 0.0,
        }
        for goal in RELEASE_GOALS
        for stack in PILOT_STACKS
    ]

    summary = _summarize(
        rows,
        1.0,
        plan_only=False,
        post_verify=True,
        skillopt_review=load_skillopt_review_evidence(review_path),
    )

    assert summary["skillopt_review"]["total_reviews"] == 10
    assert summary["skillopt_review"]["approved"] == 8
    assert summary["release_gates"]["skillopt_human_approval_ge_80"] is True
    assert summary["release_gates"]["release_ready"] is True
    assert "SkillOpt human approval evidence >=80%" not in summary["missing_release_evidence"]


def test_live_gate_rejects_invalid_skillopt_review_rows() -> None:
    summary = _summarize(
        [
            {
                "goal": "CRUD app for condo units with owner contact search",
                "stack": "py-fastapi",
                "planner_valid": True,
                "scaffold_clean": True,
                "task_all_passed": True,
                "e2e_green": True,
                "duration_s": 1,
                "timed_out": False,
                "cost_usd": 0.0,
            }
        ],
        1.0,
        plan_only=False,
        post_verify=True,
        skillopt_review={
            "reviews": [
                {"skill": "missing-reviewer", "approved": True},
                {"skill": "string-approved", "reviewer": "wesley", "approved": "yes"},
                {"skill": "missing-date", "reviewer": "wesley", "approved": True},
            ]
        },
    )

    assert summary["skillopt_review"]["total_reviews"] == 0
    assert summary["skillopt_review"]["invalid_reviews"] == 3
    assert summary["release_gates"]["skillopt_human_approval_ge_80"] is False


def test_live_gate_verifies_skillopt_review_packet_artifacts(tmp_path) -> None:
    reviews = [_skillopt_review_row(tmp_path, index, approved=index <= 8) for index in range(1, 11)]
    review_path = tmp_path / "skillopt-review.json"
    review_path.write_text(json.dumps({"reviews": reviews}), encoding="utf-8")

    evidence = load_skillopt_review_evidence(review_path)

    assert evidence["total_reviews"] == 10
    assert evidence["artifact_verified"] == 10
    assert evidence["gate_passed"] is True


def test_live_gate_rejects_skillopt_review_without_artifact() -> None:
    evidence = _normalize_skillopt_review(
        {
            "reviews": [
                {
                    "skill": "generated-skill",
                    "reviewer": "wesley",
                    "approved": True,
                    "reviewed_at": "2026-05-31",
                }
            ]
        }
    )

    assert evidence["total_reviews"] == 0
    assert evidence["invalid_reviews"] == 1
    assert evidence["gate_passed"] is False


def test_live_gate_rejects_duplicate_skillopt_review_artifacts(tmp_path) -> None:
    row = _skillopt_review_row(tmp_path, 1)
    reviews = [{**row, "skill": f"generated-skill-{index:02d}"} for index in range(10)]

    evidence = _normalize_skillopt_review({"reviews": reviews})

    assert evidence["total_reviews"] == 1
    assert evidence["invalid_reviews"] == 9
    assert evidence["duplicate_reviews"] == 9
    assert evidence["gate_passed"] is False


def test_live_gate_rejects_skillopt_review_for_manual_artifact(tmp_path) -> None:
    skill_path = tmp_path / "manual-skill" / "SKILL.md"
    skill_path.parent.mkdir()
    skill_path.write_text(
        "---\nname: manual-skill\nreview_required: true\n---\n",
        encoding="utf-8",
    )

    evidence = _normalize_skillopt_review(
        {
            "reviews": [
                {
                    "skill": "manual-skill",
                    "path": str(skill_path),
                    "sha256": hashlib.sha256(skill_path.read_bytes()).hexdigest(),
                    "reviewer": "wesley",
                    "approved": True,
                    "reviewed_at": "2026-05-31",
                }
            ]
        }
    )

    assert evidence["total_reviews"] == 0
    assert evidence["invalid_reviews"] == 1
    assert evidence["gate_passed"] is False


def test_live_gate_rejects_skillopt_review_packet_hash_mismatch(tmp_path) -> None:
    skill_path = tmp_path / "generated-skill" / "SKILL.md"
    skill_path.parent.mkdir()
    skill_path.write_text("---\nname: generated-skill\n---\n", encoding="utf-8")
    review_path = tmp_path / "skillopt-review.json"
    review_path.write_text(
        json.dumps(
            {
                "reviews": [
                    {
                        "skill": "generated-skill",
                        "path": str(skill_path),
                        "sha256": "0" * 64,
                        "reviewer": "wesley",
                        "approved": True,
                        "reviewed_at": "2026-05-31",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    evidence = load_skillopt_review_evidence(review_path)

    assert evidence["total_reviews"] == 0
    assert evidence["invalid_reviews"] == 1
    assert evidence["gate_passed"] is False


def test_live_gate_merges_distinct_slices(tmp_path) -> None:
    def fake_runner(cmd, **_kwargs):
        stack = cmd[cmd.index("--stack") + 1]
        project = tmp_path / "live" / "projects" / f"gate-g01-{stack}"
        project.mkdir(parents=True, exist_ok=True)
        if isinstance(cmd, str):
            return _completed(cmd, "")
        return _completed(
            cmd,
            json.dumps(
                {
                    "project_dir": str(project),
                    "files_written": ["src/main.py"],
                    "tasks_passed": 1,
                    "tasks_total": 1,
                }
            ),
        )

    existing = run_live_gate(
        work_dir=tmp_path / "live-py",
        stacks=("py-fastapi",),
        goals=("CRUD app for condo units",),
        post_verify=False,
        runner=fake_runner,
    )
    current = run_live_gate(
        work_dir=tmp_path / "live-ts",
        stacks=("ts-nextjs",),
        goals=("CRUD app for condo units",),
        post_verify=False,
        runner=fake_runner,
    )

    merged = merge_results(existing, current)

    assert merged["matrix"]["selected_runs"] == 2
    assert merged["matrix"]["planned_runs"] == 2
    assert [row["run_number"] for row in merged["runs"]] == [1, 2]
    assert [row["stack"] for row in merged["runs"]] == ["py-fastapi", "ts-nextjs"]
    assert merged["summary"]["total_runs"] == 2
    assert merged["summary"]["task_all_passed"] == 2


def test_live_gate_rejects_duplicate_merge_rows(tmp_path) -> None:
    def fake_runner(cmd, **_kwargs):
        return _completed(
            cmd,
            json.dumps(
                {
                    "project_dir": str(tmp_path),
                    "files_written": ["src/main.py"],
                    "tasks_passed": 1,
                    "tasks_total": 1,
                }
            ),
        )

    existing = run_live_gate(
        work_dir=tmp_path / "live-a",
        stacks=("py-fastapi",),
        goals=("CRUD app for condo units",),
        runner=fake_runner,
    )
    current = run_live_gate(
        work_dir=tmp_path / "live-b",
        stacks=("py-fastapi",),
        goals=("CRUD app for condo units",),
        runner=fake_runner,
    )

    with pytest.raises(ValueError, match="refusing to overwrite"):
        merge_results(existing, current)

    merged = merge_results(existing, current, allow_overwrite=True)
    assert merged["matrix"]["selected_runs"] == 1


def test_live_gate_resume_skips_existing_rows_before_max_runs(tmp_path) -> None:
    calls = []

    def fake_runner(cmd, **_kwargs):
        calls.append(cmd)
        return _completed(cmd, '{"tasks": [{"id": "T01"}]}')

    result = run_live_gate(
        work_dir=tmp_path / "live",
        stacks=("py-fastapi", "ts-nextjs"),
        goals=("goal one", "goal two"),
        max_runs=1,
        plan_only=True,
        skip_existing_keys={("goal one", "py-fastapi")},
        runner=fake_runner,
    )

    assert len(calls) == 1
    assert result["runs"][0]["goal"] == "goal one"
    assert result["runs"][0]["stack"] == "ts-nextjs"


def test_live_gate_disable_codegen_uses_baseline_output_defaults(tmp_path) -> None:
    args = parse_args(["--work-dir", str(tmp_path), "--disable-codegen"])

    json_output, md_output = _resolve_output_paths(args)

    assert json_output == CODEGEN_DISABLED_RESULTS_JSON
    assert md_output == CODEGEN_DISABLED_RESULTS_MD


def test_live_gate_rejects_resume_and_overwrite_together(tmp_path) -> None:
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--work-dir",
                str(tmp_path),
                "--resume-existing",
                "--overwrite-existing",
            ]
        )


def test_live_gate_marks_bad_stdout_as_failed(tmp_path) -> None:
    def fake_runner(cmd, **_kwargs):
        return _completed(cmd, "not json", returncode=3)

    result = run_live_gate(
        work_dir=tmp_path / "live",
        stacks=("py-fastapi",),
        goals=("CRUD app for condo units",),
        plan_only=True,
        runner=fake_runner,
    )

    row = result["runs"][0]
    assert row["planner_valid"] is False
    assert row["json_parse_error"]
    assert result["summary"]["planner_valid_rate"] == 0.0


def test_live_gate_extracts_json_from_noisy_stdout() -> None:
    payload, error = _parse_json_stdout('noise\n{"tasks": [{"id": "T01"}]}\n')

    assert error == ""
    assert payload == {"tasks": [{"id": "T01"}]}


def test_live_gate_writes_reports(tmp_path) -> None:
    def fake_runner(cmd, **_kwargs):
        return _completed(cmd, '{"tasks": [{"id": "T01"}]}')

    result = run_live_gate(
        work_dir=tmp_path / "live",
        stacks=("py-fastapi",),
        goals=("CRUD app for condo units",),
        plan_only=True,
        runner=fake_runner,
    )
    json_path = tmp_path / "live.json"
    md_path = tmp_path / "live.md"

    write_reports(result, json_path, md_path)

    assert '"benchmark": "scratch-live-gate"' in json_path.read_text(encoding="utf-8")
    assert "# Scratch Live Gate" in md_path.read_text(encoding="utf-8")


def test_versioned_agent_skillopt_review_packet_passes_gate() -> None:
    summary = load_skillopt_review_evidence(Path("bench/results_skillopt_agent_review_packet.json"))

    assert summary["total_reviews"] == 10
    assert summary["approved"] == 8
    assert summary["approval_rate"] == 0.8
    assert summary["gate_passed"] is True
    assert summary["invalid_reviews"] == 0
    assert summary["artifact_verified"] == 10
