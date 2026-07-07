"""Tests for the GitHub issue close-readiness audit."""

from __future__ import annotations

import json

from bench.run_issue_closure_audit import run_audit, write_reports


def _write_json(path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _paths(tmp_path) -> dict[str, object]:
    paths = {
        "scratch_live_gate": tmp_path / "scratch-live.json",
        "llm_reduction": tmp_path / "llm-summary.json",
        "unified_run": tmp_path / "unified.json",
        "schema_smoke": tmp_path / "schema-smoke.json",
        "quant_curve_json": tmp_path / "quant-curve.json",
        "quant_curve_md": tmp_path / "quant-curve.md",
        "quant_curve_pdf": tmp_path / "quant-curve.pdf",
        "quant_curve_adr": tmp_path / "quant-curve-adr.md",
    }
    _write_json(
        paths["scratch_live_gate"],
        {
            "benchmark": "scratch-live-gate",
            "summary": {
                "release_gates": {
                    "full_75_run_matrix": True,
                    "planner_valid_ge_90": True,
                    "scaffold_clean_ge_95": True,
                    "e2e_green_ge_80": True,
                    "average_cost_le_1": True,
                    "skillopt_human_approval_ge_80": False,
                    "release_ready": False,
                }
            },
        },
    )
    _write_json(
        paths["llm_reduction"],
        {
            "benchmark": "llm-reduction-summary",
            "summary": {
                "release_evidence_complete": False,
                "missing_release_evidence": ["real scratch LLM baseline for B/codegen pass-rate and latency"],
                "release_gates": {
                    "target_reduction_met": True,
                    "real_50_scratch_corpus": True,
                    "B_real_executor_pass_rate_ge_llm": False,
                    "B_real_latency_reduction_ge_50": False,
                    "SkillOpt_human_approval_ge_80": False,
                    "release_evidence_complete": False,
                },
            },
        },
    )
    _write_json(
        paths["unified_run"],
        {
            "benchmark": "unified-run-f5-fixture",
            "summary": {
                "fixture_only": True,
                "evidence_level": "fixture",
                "real_llm_runs_present": False,
                "external_codex_goal_run_present": False,
                "release_ready": False,
                "missing_live_evidence": ["real Codex /goal baseline runs"],
            },
        },
    )
    _write_json(
        paths["schema_smoke"],
        {
            "benchmark": "schema-smoke-summary",
            "summary": {
                "required_quant_smokes_present": {
                    "Q8_0": False,
                    "Q6_K": False,
                    "Q4_K_M": False,
                },
                "required_quant_smokes_passed": {
                    "Q8_0": False,
                    "Q6_K": False,
                    "Q4_K_M": False,
                },
                "failed_required_quant_smokes": [],
                "missing_release_evidence": ["bench/results_v14_qwen15b_quant_curve.{md,json,pdf}"],
            },
        },
    )
    return paths


def test_issue_closure_audit_keeps_partial_evidence_open(tmp_path) -> None:
    result = run_audit(_paths(tmp_path))

    assert result["benchmark"] == "issue-closure-audit"
    assert result["summary"]["all_issues_close_ready"] is False
    assert result["summary"]["issues_close_ready"] == 0
    assert "skillopt_human_approval_ge_80" in result["issues"]["32"]["blockers"]
    assert "B_real_executor_pass_rate_ge_llm" in result["issues"]["33"]["blockers"]
    assert "not_fixture_only" in result["issues"]["41"]["blockers"]
    assert "Q8_0_smoke_present" in result["issues"]["46"]["blockers"]
    assert "quant_curve_adr_present" in result["issues"]["46"]["blockers"]


def test_issue_closure_audit_passes_when_all_release_gates_are_true(tmp_path) -> None:
    paths = _paths(tmp_path)
    scratch = json.loads(paths["scratch_live_gate"].read_text(encoding="utf-8"))
    scratch["summary"]["release_gates"]["skillopt_human_approval_ge_80"] = True
    scratch["summary"]["release_gates"]["release_ready"] = True
    _write_json(paths["scratch_live_gate"], scratch)

    llm = json.loads(paths["llm_reduction"].read_text(encoding="utf-8"))
    llm["summary"]["release_evidence_complete"] = True
    llm["summary"]["missing_release_evidence"] = []
    llm["summary"]["release_gates"].update(
        {
            "B_real_executor_pass_rate_ge_llm": True,
            "B_real_latency_reduction_ge_50": True,
            "SkillOpt_human_approval_ge_80": True,
            "release_evidence_complete": True,
        }
    )
    _write_json(paths["llm_reduction"], llm)

    _write_json(
        paths["unified_run"],
        {
            "benchmark": "unified-run-f5-live",
            "summary": {
                "fixture_only": False,
                "evidence_level": "live",
                "real_llm_runs_present": True,
                "external_codex_goal_run_present": True,
                "release_ready": True,
                "missing_live_evidence": [],
            },
        },
    )
    _write_json(
        paths["schema_smoke"],
        {
            "benchmark": "schema-smoke-summary",
            "summary": {
                "required_quant_smokes_present": {
                    "Q8_0": True,
                    "Q6_K": True,
                    "Q4_K_M": True,
                },
                "required_quant_smokes_passed": {
                    "Q8_0": False,
                    "Q6_K": False,
                    "Q4_K_M": False,
                },
                "failed_required_quant_smokes": ["Q8_0", "Q6_K", "Q4_K_M"],
                "missing_release_evidence": [],
            },
        },
    )
    _write_json(paths["quant_curve_json"], {"summary": {"release_ready": True}})
    paths["quant_curve_md"].write_text("# curve\n", encoding="utf-8")
    paths["quant_curve_pdf"].write_bytes(b"%PDF-1.4\n")
    paths["quant_curve_adr"].write_text("# decision\n", encoding="utf-8")

    result = run_audit(paths)

    assert result["summary"]["all_issues_close_ready"] is True
    assert result["summary"]["issues_close_ready"] == 4
    assert result["summary"]["open_blockers"] == {}


def test_issue_closure_audit_writes_reports(tmp_path) -> None:
    result = run_audit(_paths(tmp_path))
    json_path = tmp_path / "audit.json"
    md_path = tmp_path / "audit.md"

    write_reports(result, json_path, md_path)

    assert '"benchmark": "issue-closure-audit"' in json_path.read_text(encoding="utf-8")
    assert "# Issue Closure Audit" in md_path.read_text(encoding="utf-8")
