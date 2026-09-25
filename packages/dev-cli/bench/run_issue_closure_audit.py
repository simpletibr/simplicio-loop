"""Audit close-readiness for the open GitHub issues tracked by PR #47.

The goal is not to approve missing evidence. This script converts the current
repo-local artifacts into machine-readable close blockers for #32, #33, #41,
and #46, so completion cannot be claimed from partial reports.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent

RESULTS_JSON = ROOT / "bench" / "results_issue_closure_audit.json"
RESULTS_MD = ROOT / "bench" / "results_issue_closure_audit.md"

DEFAULT_INPUTS = {
    "scratch_live_gate": ROOT / "bench" / "results_scratch_live_gate.json",
    "llm_reduction": ROOT / "bench" / "results_llm_reduction_summary.json",
    "unified_run": ROOT / "bench" / "results_unified_run_bench.json",
    "schema_smoke": ROOT / "bench" / "results_v14_schema_smoke_summary.json",
    "quant_curve_json": ROOT / "bench" / "results_v14_qwen15b_quant_curve.json",
    "quant_curve_md": ROOT / "bench" / "results_v14_qwen15b_quant_curve.md",
    "quant_curve_pdf": ROOT / "bench" / "results_v14_qwen15b_quant_curve.pdf",
    "quant_curve_adr": ROOT / "docs" / "adr" / "0001-qwen15b-schema-v1-quant-decision.md",
}


def run_audit(input_paths: dict[str, Path] | None = None) -> dict[str, Any]:
    paths = input_paths or DEFAULT_INPUTS
    inputs = {name: _load(path) for name, path in paths.items()}
    issues = {
        "32": _audit_issue_32(inputs),
        "33": _audit_issue_33(inputs),
        "41": _audit_issue_41(inputs),
        "46": _audit_issue_46(inputs),
    }
    open_blockers = {
        issue: result["blockers"]
        for issue, result in issues.items()
        if result["blockers"]
    }
    return {
        "benchmark": "issue-closure-audit",
        "scope": (
            "close-readiness audit for GitHub issues #32, #33, #41, and #46; "
            "partial evidence is reported as blockers"
        ),
        "date": time.strftime("%Y-%m-%d"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "inputs": {
            name: {
                "path": _relative_path(item["path"]),
                "present": item["present"],
                "benchmark": item.get("benchmark"),
                "error": item.get("error", ""),
            }
            for name, item in inputs.items()
        },
        "issues": issues,
        "summary": {
            "issues_total": len(issues),
            "issues_close_ready": sum(
                1 for result in issues.values() if result["close_ready"]
            ),
            "issues_blocked": sum(
                1 for result in issues.values() if not result["close_ready"]
            ),
            "all_issues_close_ready": all(
                result["close_ready"] for result in issues.values()
            ),
            "open_blockers": open_blockers,
        },
}


def _relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": path, "present": False, "error": "missing file"}
    if path.suffix.lower() != ".json":
        return {"path": path, "present": True, "benchmark": "file"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"path": path, "present": False, "error": f"invalid json: {exc}"}
    return {
        "path": path,
        "present": True,
        "benchmark": data.get("benchmark"),
        "data": data,
    }


def _audit_issue_32(inputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    live = _summary(inputs, "scratch_live_gate")
    gates = live.get("release_gates") if isinstance(live.get("release_gates"), dict) else {}
    checks = {
        "scratch_live_gate_present": inputs["scratch_live_gate"]["present"],
        "full_75_run_matrix": gates.get("full_75_run_matrix") is True,
        "planner_valid_ge_90": gates.get("planner_valid_ge_90") is True,
        "scaffold_clean_ge_95": gates.get("scaffold_clean_ge_95") is True,
        "e2e_green_ge_80": gates.get("e2e_green_ge_80") is True,
        "average_cost_le_1": gates.get("average_cost_le_1") is True,
        "skillopt_human_approval_ge_80": (
            gates.get("skillopt_human_approval_ge_80") is True
        ),
        "live_gate_release_ready": gates.get("release_ready") is True,
    }
    blockers = _missing_checks(checks)
    return _issue_result(
        title="from-scratch mode + planner + SkillOpt",
        checks=checks,
        blockers=blockers,
    )


def _audit_issue_33(inputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    summary = _summary(inputs, "llm_reduction")
    gates = summary.get("release_gates") if isinstance(summary.get("release_gates"), dict) else {}
    checks = {
        "llm_reduction_summary_present": inputs["llm_reduction"]["present"],
        "target_reduction_met": gates.get("target_reduction_met") is True,
        "real_50_scratch_corpus": gates.get("real_50_scratch_corpus") is True,
        "B_real_executor_pass_rate_ge_llm": (
            gates.get("B_real_executor_pass_rate_ge_llm") is True
        ),
        "B_real_latency_reduction_ge_50": (
            gates.get("B_real_latency_reduction_ge_50") is True
        ),
        "SkillOpt_human_approval_ge_80": (
            gates.get("SkillOpt_human_approval_ge_80") is True
        ),
        "release_evidence_complete": (
            summary.get("release_evidence_complete") is True
            or gates.get("release_evidence_complete") is True
        ),
    }
    blockers = _missing_checks(checks)
    blockers.extend(
        item
        for item in summary.get("missing_release_evidence", [])
        if isinstance(item, str) and item not in blockers
    )
    return _issue_result(
        title="reduce LLM dependency across simplicio flow",
        checks=checks,
        blockers=blockers,
    )


def _audit_issue_41(inputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    unified = _summary(inputs, "unified_run")
    checks = {
        "unified_run_report_present": inputs["unified_run"]["present"],
        "not_fixture_only": unified.get("fixture_only") is False,
        "live_evidence_level": unified.get("evidence_level") == "live",
        "real_llm_runs_present": unified.get("real_llm_runs_present") is True,
        "external_codex_goal_run_present": (
            unified.get("external_codex_goal_run_present") is True
        ),
        "release_ready": unified.get("release_ready") is True,
    }
    blockers = _missing_checks(checks)
    blockers.extend(
        item
        for item in unified.get("missing_live_evidence", [])
        if isinstance(item, str) and item not in blockers
    )
    return _issue_result(
        title="unified simplicio-py run orchestrator",
        checks=checks,
        blockers=blockers,
    )


def _audit_issue_46(inputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    smoke = _summary(inputs, "schema_smoke")
    required = smoke.get("required_quant_smokes_present")
    required = required if isinstance(required, dict) else {}
    curve = _summary(inputs, "quant_curve_json")
    checks = {
        "schema_smoke_summary_present": inputs["schema_smoke"]["present"],
        "Q8_0_smoke_present": required.get("Q8_0") is True,
        "Q6_K_smoke_present": required.get("Q6_K") is True,
        "Q4_K_M_smoke_present": required.get("Q4_K_M") is True,
        "quant_curve_json_present": inputs["quant_curve_json"]["present"],
        "quant_curve_md_present": inputs["quant_curve_md"]["present"],
        "quant_curve_pdf_present": inputs["quant_curve_pdf"]["present"],
        "quant_curve_adr_present": inputs["quant_curve_adr"]["present"],
        "quant_curve_release_ready": curve.get("release_ready") is True,
    }
    blockers = _missing_checks(checks)
    return _issue_result(
        title="Qwen2.5-Coder-1.5B GGUF quant curve",
        checks=checks,
        blockers=blockers,
    )


def _summary(inputs: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    data = inputs[name].get("data")
    if not isinstance(data, dict):
        return {}
    summary = data.get("summary")
    return summary if isinstance(summary, dict) else {}


def _missing_checks(checks: dict[str, bool]) -> list[str]:
    return [name for name, passed in checks.items() if passed is not True]


def _issue_result(
    *,
    title: str,
    checks: dict[str, bool],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "title": title,
        "close_ready": not blockers,
        "checks": checks,
        "blockers": blockers,
    }


def write_reports(result: dict[str, Any], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_to_markdown(result), encoding="utf-8")


def _to_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Issue Closure Audit",
        "",
        result["scope"],
        "",
        "## Summary",
        "",
        f"- issues close-ready: {summary['issues_close_ready']}/{summary['issues_total']}",
        f"- all issues close-ready: {summary['all_issues_close_ready']}",
        "",
        "## Issues",
        "",
        "| issue | title | close-ready | blockers |",
        "| --- | --- | --- | ---: |",
    ]
    for issue, data in result["issues"].items():
        lines.append(
            f"| #{issue} | {data['title']} | {data['close_ready']} | "
            f"{len(data['blockers'])} |"
        )
    lines.extend(["", "## Open Blockers", ""])
    for issue, blockers in summary["open_blockers"].items():
        lines.append(f"### #{issue}")
        for blocker in blockers:
            lines.append(f"- {blocker}")
        lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", type=Path, default=RESULTS_JSON)
    parser.add_argument("--md-output", type=Path, default=RESULTS_MD)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--fail-open",
        action="store_true",
        help="Return exit code 1 while any tracked issue is not close-ready.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_audit()
    write_reports(result, args.json_output, args.md_output)
    if not args.quiet:
        print(json.dumps(result["summary"], indent=2, sort_keys=True))
        print(f"wrote {args.json_output}")
        print(f"wrote {args.md_output}")
    if args.fail_open and not result["summary"]["all_issues_close_ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
