"""Aggregate the LLM-reduction evidence reports into one release view.

The individual benchmark harnesses prove separate levers from issue #33:
cache (D), static fixers (C), recipes (A), mechanical executors (B), and the
scratch release-gate preflight. This report intentionally keeps synthetic
local evidence separate from release evidence so the remaining blockers stay
machine-readable.
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

RESULTS_JSON = ROOT / "bench" / "results_llm_reduction_summary.json"
RESULTS_MD = ROOT / "bench" / "results_llm_reduction_summary.md"

DEFAULT_INPUTS = {
    "cache": ROOT / "bench" / "results_scratch_cache_gate.json",
    "static_fixers": ROOT / "bench" / "results_static_fixers.json",
    "recipes": ROOT / "bench" / "results_scratch_recipes.json",
    "codegen": ROOT / "bench" / "results_scratch_codegen.json",
    "preflight": ROOT / "bench" / "results_scratch_release_gate.json",
    "live_gate": ROOT / "bench" / "results_scratch_live_gate.json",
}


def run_summary(input_paths: dict[str, Path] | None = None) -> dict[str, Any]:
    paths = input_paths or DEFAULT_INPUTS
    inputs = {name: _load_input(path) for name, path in paths.items()}
    levers = _summarize_levers(inputs)
    release_call_proof = _release_call_proof(inputs)
    gates = _summarize_gates(levers, release_call_proof)
    modeled_path = _modeled_call_path(gates)
    missing = _missing_release_evidence(inputs, gates)

    return {
        "benchmark": "llm-reduction-summary",
        "scope": (
            "aggregate issue #33 evidence view; separates local synthetic gates "
            "from the real release corpus and LLM-baseline gates"
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
        "levers": levers,
        "release_call_proof": release_call_proof,
        "summary": {
            "local_synthetic_gates_pass": gates["local_synthetic_gates_pass"],
            "release_evidence_complete": gates["release_evidence_complete"],
            "target_reduction_met": gates["target_reduction_met"],
            "modeled_baseline_calls": modeled_path["baseline_calls"],
            "modeled_final_calls": modeled_path["final_calls"],
            "modeled_reduction": modeled_path["reduction"],
            "missing_release_evidence": missing,
            "release_gates": gates,
        },
        "modeled_call_path": modeled_path,
}


def _relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _load_input(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"path": path, "present": False, "error": "missing file"}
    except json.JSONDecodeError as exc:
        return {"path": path, "present": False, "error": f"invalid json: {exc}"}
    return {
        "path": path,
        "present": True,
        "benchmark": data.get("benchmark"),
        "data": data,
    }


def _summarize_levers(inputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cache = _summary(inputs, "cache")
    fixers = _summary(inputs, "static_fixers")
    recipes = _summary(inputs, "recipes")
    codegen = _summary(inputs, "codegen")
    preflight = _summary(inputs, "preflight")
    live_gate = _summary(inputs, "live_gate")

    return {
        "D_cache": {
            "present": inputs["cache"]["present"],
            "warm_hit_rate": cache.get("warm_hit_rate", 0.0),
            "warm_hits": cache.get("warm_hits", 0),
            "warm_misses": cache.get("warm_misses", 0),
            "gate_passed": _gate(cache, "warm_hit_rate_ge_80")
            and _gate(cache, "warm_plans_all_valid"),
            "real_corpus": _gate(cache, "real_50_scratch_corpus"),
        },
        "C_static_fixers": {
            "present": inputs["static_fixers"]["present"],
            "fixer_resolved_rate": fixers.get("fixer_resolved_rate", 0.0),
            "retry_call_reduction": fixers.get("retry_call_reduction", 0.0),
            "baseline_llm_calls": fixers.get("baseline_llm_calls", 0),
            "with_fixer_llm_calls": fixers.get("with_fixer_llm_calls", 0),
            "real_package_manager_cases": fixers.get(
                "real_package_manager_cases",
                0,
            ),
            "real_package_manager_passed": fixers.get(
                "real_package_manager_passed",
                0,
            ),
            "scratch_import_failure_cases": fixers.get(
                "scratch_import_failure_cases",
                0,
            ),
            "scratch_import_failure_passed": fixers.get(
                "scratch_import_failure_passed",
                0,
            ),
            "real_package_manager_execution": _gate(
                fixers,
                "real_package_manager_execution",
            ),
            "real_scratch_import_failure_repaired": _gate(
                fixers,
                "real_scratch_import_failure_repaired",
            ),
            "gate_passed": _gate(fixers, "fixer_resolved_ge_80")
            and _gate(fixers, "retry_calls_down_ge_30"),
            "real_corpus": _gate(fixers, "real_scratch_corpus"),
        },
        "A_recipes": {
            "present": inputs["recipes"]["present"],
            "match_rate": recipes.get("match_rate", 0.0),
            "matched_cases": recipes.get("matched_cases", 0),
            "total_cases": recipes.get("total_cases", 0),
            "planner_calls_saved": recipes.get("planner_calls_saved", 0),
            "gate_passed": _gate(recipes, "recipe_match_ge_40")
            and _gate(recipes, "matched_plans_valid"),
            "real_corpus": _gate(recipes, "real_scratch_corpus"),
            "llm_baseline_present": _gate(
                recipes,
                "llm_pass_rate_baseline_present",
            ),
            "recipe_plan_pass_rate_ge_llm": _gate(
                recipes,
                "recipe_plan_pass_rate_ge_llm",
            ),
        },
        "B_codegen": {
            "present": inputs["codegen"]["present"],
            "codegen_share": codegen.get("codegen_share", 0.0),
            "pass_rate": codegen.get("pass_rate", 0.0),
            "avg_codegen_ms": codegen.get("avg_codegen_ms", 0),
            "tasks_codegen": codegen.get("tasks_codegen", 0),
            "total_tasks": codegen.get("total_tasks", 0),
            "gate_passed": _gate(codegen, "mechanical_share_ge_30")
            and _gate(codegen, "executor_pass_rate_100")
            and _gate(codegen, "typescript_next_route_compiles_and_responds_json"),
            "llm_baseline_present": _gate(codegen, "llm_baseline_present"),
            "executor_pass_rate_ge_llm": _gate(
                codegen,
                "executor_pass_rate_ge_llm",
            ),
            "latency_reduction_ge_50": _gate(codegen, "latency_reduction_ge_50"),
            "real_corpus": _gate(codegen, "real_50_scratch_corpus"),
            "real_mechanical_share_ge_30": _gate(
                codegen,
                "real_mechanical_share_ge_30",
            ),
            "real_e2e_green_ge_80": _gate(codegen, "real_e2e_green_ge_80"),
            "real_executor_pass_rate_ge_llm": _gate(
                codegen,
                "real_executor_pass_rate_ge_llm",
            ),
            "real_latency_reduction_ge_50": _gate(
                codegen,
                "real_latency_reduction_ge_50",
            ),
            "zero_feature_regression_live": _gate(
                codegen,
                "zero_feature_regression_live",
            ),
        },
        "scratch_preflight": {
            "present": inputs["preflight"]["present"],
            "ready_for_live_gate": bool(preflight.get("ready_for_live_gate", False)),
            "blocker_count": preflight.get("blocker_count", 0),
            "blockers": preflight.get("blockers", []),
        },
        "scratch_live_gate": {
            "present": inputs["live_gate"]["present"],
            "total_runs": live_gate.get("total_runs", 0),
            "e2e_green": live_gate.get("e2e_green", 0),
            "e2e_green_rate": live_gate.get("e2e_green_rate", 0.0),
            "median_wall_clock_s": live_gate.get("median_wall_clock_s"),
            "full_matrix": _gate(live_gate, "full_75_run_matrix"),
            "e2e_green_ge_80": _gate(live_gate, "e2e_green_ge_80"),
            "skillopt_human_approval_ge_80": _gate(
                live_gate,
                "skillopt_human_approval_ge_80",
            ),
            "skillopt_reviews": int(
                (live_gate.get("skillopt_review") or {}).get("total_reviews", 0)
            ),
            "skillopt_approved": int(
                (live_gate.get("skillopt_review") or {}).get("approved", 0)
            ),
            "release_ready": _gate(live_gate, "release_ready"),
        },
    }


def _summary(inputs: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    item = inputs[name]
    if not item["present"]:
        return {}
    data = item["data"]
    return data.get("summary") or data.get("gate") or {}


def _gate(summary: dict[str, Any], name: str) -> bool:
    return bool(summary.get("release_gates", {}).get(name, False))


def _release_call_proof(inputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    recipes = _summary(inputs, "recipes")
    codegen = _summary(inputs, "codegen")
    live_gate = _summary(inputs, "live_gate")
    recipe_live = recipes.get("live_corpus") or {}
    codegen_live = codegen.get("live_corpus") or {}

    total_runs = int(
        recipe_live.get("total_runs")
        or live_gate.get("total_runs")
        or codegen_live.get("total_runs")
        or 0
    )
    tasks_total = int(
        codegen_live.get("tasks_total") or codegen.get("total_tasks") or 0
    )
    tasks_llm = int(codegen_live.get("tasks_llm") or 0)
    tasks_codegen = int(codegen_live.get("tasks_codegen") or 0)
    planner_calls_saved = min(
        int(recipe_live.get("planner_calls_saved") or 0),
        total_runs,
    )
    planner_calls_after_recipes = max(total_runs - planner_calls_saved, 0)
    baseline_calls = total_runs + tasks_total
    actual_calls = planner_calls_after_recipes + tasks_llm
    calls_saved = max(baseline_calls - actual_calls, 0)
    reduction = round(calls_saved / baseline_calls, 4) if baseline_calls else 0.0

    release_matrix_ready = bool(
        _gate(live_gate, "full_75_run_matrix")
        and _gate(live_gate, "e2e_green_ge_80")
        and _gate(recipes, "real_scratch_corpus")
        and _gate(codegen, "real_50_scratch_corpus")
    )
    target_met = bool(release_matrix_ready and reduction >= 0.68)
    return {
        "present": release_matrix_ready,
        "baseline_calls": baseline_calls,
        "actual_calls": actual_calls,
        "calls_saved": calls_saved,
        "reduction": reduction,
        "target_reduction": 0.68,
        "target_reduction_met": target_met,
        "total_runs": total_runs,
        "planner_calls_saved_by_recipes": planner_calls_saved,
        "planner_calls_after_recipes": planner_calls_after_recipes,
        "tasks_total": tasks_total,
        "tasks_codegen": tasks_codegen,
        "tasks_llm": tasks_llm,
    }


def _summarize_gates(
    levers: dict[str, Any],
    release_call_proof: dict[str, Any],
) -> dict[str, Any]:
    local_gates = {
        "D_cache_synthetic": levers["D_cache"]["gate_passed"],
        "C_static_fixers_synthetic": levers["C_static_fixers"]["gate_passed"],
        "A_recipes_synthetic": levers["A_recipes"]["gate_passed"],
        "B_codegen_synthetic": levers["B_codegen"]["gate_passed"],
        "scratch_preflight_ready": levers["scratch_preflight"]["ready_for_live_gate"],
    }
    release_gates = {
        **local_gates,
        "real_50_scratch_corpus": (
            levers["D_cache"]["real_corpus"]
            and levers["C_static_fixers"]["real_corpus"]
            and levers["A_recipes"]["real_corpus"]
        ),
        "C_real_package_manager_execution": levers["C_static_fixers"][
            "real_package_manager_execution"
        ],
        "C_real_scratch_import_failure_repaired": levers["C_static_fixers"][
            "real_scratch_import_failure_repaired"
        ],
        "A_recipe_llm_baseline_present": levers["A_recipes"]["llm_baseline_present"],
        "A_recipe_pass_rate_ge_llm": levers["A_recipes"][
            "recipe_plan_pass_rate_ge_llm"
        ],
        "B_codegen_llm_baseline_present": levers["B_codegen"]["llm_baseline_present"],
        "B_executor_pass_rate_ge_llm": levers["B_codegen"]["executor_pass_rate_ge_llm"],
        "B_latency_reduction_ge_50": levers["B_codegen"]["latency_reduction_ge_50"],
        "B_real_50_scratch_corpus": levers["B_codegen"]["real_corpus"],
        "B_real_mechanical_share_ge_30": levers["B_codegen"][
            "real_mechanical_share_ge_30"
        ],
        "B_real_e2e_green_ge_80": levers["B_codegen"]["real_e2e_green_ge_80"],
        "B_real_executor_pass_rate_ge_llm": levers["B_codegen"][
            "real_executor_pass_rate_ge_llm"
        ],
        "B_real_latency_reduction_ge_50": levers["B_codegen"][
            "real_latency_reduction_ge_50"
        ],
        "B_zero_feature_regression_live": levers["B_codegen"][
            "zero_feature_regression_live"
        ],
        "scratch_live_matrix_complete": levers["scratch_live_gate"]["full_matrix"],
        "scratch_live_e2e_green_ge_80": levers["scratch_live_gate"]["e2e_green_ge_80"],
        "SkillOpt_human_approval_ge_80": levers["scratch_live_gate"][
            "skillopt_human_approval_ge_80"
        ],
        "aggregate_call_reduction_proof": release_call_proof["present"],
    }
    local_synthetic = all(local_gates.values())
    release_complete = all(release_gates.values())
    release_gates["local_synthetic_gates_pass"] = local_synthetic
    release_gates["release_evidence_complete"] = release_complete
    release_gates["target_reduction_met"] = release_call_proof["target_reduction_met"]
    return release_gates


def _modeled_call_path(gates: dict[str, bool]) -> dict[str, Any]:
    # Roadmap model from issue #33: 1 planner + 18 doer calls => 19 calls.
    baseline = 19
    after_cache = 18 if gates["D_cache_synthetic"] else baseline
    after_fixers = 16 if gates["C_static_fixers_synthetic"] else after_cache
    after_recipes = after_fixers
    after_codegen = 6 if gates["B_codegen_synthetic"] else after_recipes
    reduction = round((baseline - after_codegen) / baseline, 4)
    return {
        "baseline_calls": baseline,
        "steps": [
            {
                "name": "baseline",
                "calls": baseline,
                "note": "1 planner + 18 doer calls in the roadmap model",
            },
            {
                "name": "D_cache",
                "calls": after_cache,
                "gate_passed": gates["D_cache_synthetic"],
                "note": "warm cache removes the repeated planner call",
            },
            {
                "name": "C_static_fixers",
                "calls": after_fixers,
                "gate_passed": gates["C_static_fixers_synthetic"],
                "note": "static fixers reduce verify-loop retry calls",
            },
            {
                "name": "A_recipes",
                "calls": after_recipes,
                "gate_passed": gates["A_recipes_synthetic"],
                "note": "recipes save cold planner calls for matched common goals",
            },
            {
                "name": "B_codegen",
                "calls": after_codegen,
                "gate_passed": gates["B_codegen_synthetic"],
                "note": "mechanical executors replace common doer calls",
            },
        ],
        "final_calls": after_codegen,
        "reduction": reduction,
        "target_reduction": 0.68,
        "target_reduction_met_locally": reduction >= 0.68,
        "release_target_met": False,
    }


def _missing_release_evidence(
    inputs: dict[str, dict[str, Any]],
    gates: dict[str, bool],
) -> list[str]:
    missing: list[str] = []
    for name, item in inputs.items():
        if not item["present"]:
            missing.append(f"{name}: {item.get('error', 'missing input')}")
            continue
        summary = _summary(inputs, name)
        for entry in summary.get("missing_release_evidence", []):
            if _is_generic_real_corpus_missing(str(entry)):
                continue
            if _is_aggregate_call_missing(str(entry)) and gates["target_reduction_met"]:
                continue
            missing.append(str(entry))
    if not gates["real_50_scratch_corpus"]:
        missing.append(_real_corpus_missing_text(inputs))
    if not gates["B_codegen_llm_baseline_present"]:
        missing.append("captured LLM baseline for executor pass-rate and latency")
    if not gates["B_real_50_scratch_corpus"]:
        missing.append("B/codegen real 50-scratch corpus")
    if not gates["B_real_mechanical_share_ge_30"]:
        missing.append("B/codegen real mechanical task share >=30%")
    if not gates["B_real_executor_pass_rate_ge_llm"]:
        missing.append("B/codegen real executor pass-rate >= LLM baseline")
    if not gates["B_real_latency_reduction_ge_50"]:
        missing.append("B/codegen real task latency reduction >=50%")
    if not gates["B_zero_feature_regression_live"]:
        missing.append("B/codegen zero feature regression evidence")
    if not gates["C_real_package_manager_execution"]:
        missing.append("non-faked package manager execution")
    if not gates["C_real_scratch_import_failure_repaired"]:
        missing.append(
            "real fixer evidence from actual scratch install/import/lint failures"
        )
    if not gates["A_recipe_llm_baseline_present"]:
        missing.append("recipe path pass-rate compared with equivalent LLM path")
    if not gates["A_recipe_pass_rate_ge_llm"]:
        missing.append("recipe path pass-rate >= equivalent LLM path")
    if not gates["scratch_preflight_ready"]:
        missing.append("scratch live-gate preflight must be ready before the matrix")
    if not gates["scratch_live_matrix_complete"]:
        missing.append("live v0.5 scratch matrix: 15 goals x 5 pilot stacks")
    if not gates["SkillOpt_human_approval_ge_80"]:
        missing.append("SkillOpt human approval evidence >=80%")
    return _canonical_missing(missing)


def _canonical_missing(values: list[str]) -> list[str]:
    canonical = []
    for value in values:
        text = " ".join(value.strip().split())
        lower = text.casefold()
        if not text:
            continue
        if "b/codegen real 50-scratch" in lower:
            canonical.append("B/codegen real 50-scratch corpus")
        elif "real 50-scratch corpus still missing for" in lower:
            canonical.append(text)
        elif "50 real scratch" in lower or "real 50-scratch" in lower:
            canonical.append(
                "real 50-scratch corpus shared by cache, recipes, fixers, and executors"
            )
        elif "real scratch llm baseline" in lower:
            canonical.append(
                "real scratch LLM baseline for B/codegen pass-rate and latency"
            )
        elif "real mechanical task share" in lower:
            canonical.append("B/codegen real mechanical task share >=30%")
        elif "real executor pass-rate" in lower:
            canonical.append(
                "real scratch LLM baseline for B/codegen pass-rate and latency"
            )
        elif "real task latency reduction" in lower:
            canonical.append(
                "real scratch LLM baseline for B/codegen pass-rate and latency"
            )
        elif "zero feature regression" in lower:
            canonical.append("B/codegen zero feature regression evidence")
        elif "aggregate call-reduction" in lower:
            canonical.append(
                "aggregate call-reduction proof across cache, recipes, fixers, and executors"
            )
        elif (
            "real install/import/lint failures" in lower
            or "comparison across actual scratch reports" in lower
        ):
            canonical.append(
                "real fixer evidence from actual scratch install/import/lint failures"
            )
        elif "non-faked package manager" in lower:
            canonical.append("non-faked package manager execution")
        elif "recipe path pass-rate" in lower:
            canonical.append("recipe path pass-rate compared with equivalent LLM path")
        elif "llm baseline" in lower:
            canonical.append("captured LLM baseline for executor pass-rate and latency")
        elif "planner cache hit-rate" in lower:
            canonical.append(
                "planner cache hit-rate measured across cold/warm real scratch runs"
            )
        elif "live v0.5" in lower or "15 goals x 5 pilot stacks" in lower:
            canonical.append("live v0.5 scratch matrix: 15 goals x 5 pilot stacks")
        elif "skillopt" in lower:
            canonical.append("SkillOpt human approval evidence >=80%")
        else:
            canonical.append(text)
    return _dedupe(canonical)


def _is_generic_real_corpus_missing(value: str) -> bool:
    lower = " ".join(value.strip().split()).casefold()
    return "50 real scratch" in lower or "real 50-scratch" in lower


def _is_aggregate_call_missing(value: str) -> bool:
    return "aggregate call-reduction" in " ".join(value.strip().split()).casefold()


def _real_corpus_missing_text(inputs: dict[str, dict[str, Any]]) -> str:
    missing = []
    if not _gate(_summary(inputs, "cache"), "real_50_scratch_corpus"):
        missing.append("cache")
    if not _gate(_summary(inputs, "static_fixers"), "real_scratch_corpus"):
        missing.append("static fixers")
    if not _gate(_summary(inputs, "recipes"), "real_scratch_corpus"):
        missing.append("recipes")
    if not missing:
        missing.append("aggregate proof")
    return "real 50-scratch corpus still missing for " + ", ".join(missing)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        normalized = " ".join(value.strip().split())
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def write_reports(result: dict[str, Any], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_to_markdown(result), encoding="utf-8")


def _to_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    levers = result["levers"]
    path = result["modeled_call_path"]
    proof = result["release_call_proof"]
    lines = [
        "# LLM Reduction Summary",
        "",
        result["scope"],
        "",
        "## Summary",
        "",
        f"- local synthetic gates pass: {summary['local_synthetic_gates_pass']}",
        f"- release evidence complete: {summary['release_evidence_complete']}",
        f"- target reduction met for release: {summary['target_reduction_met']}",
        (
            "- modeled local call path: "
            f"{path['baseline_calls']} -> {path['final_calls']} "
            f"({path['reduction']:.2%} reduction)"
        ),
        (
            "- release call proof: "
            f"{proof['baseline_calls']} -> {proof['actual_calls']} "
            f"({proof['reduction']:.2%} reduction)"
        ),
        "",
        "## Lever Evidence",
        "",
        "| lever | gate | key evidence | release gap |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        [
            (
                f"| D cache | {levers['D_cache']['gate_passed']} | "
                f"warm hit-rate {levers['D_cache']['warm_hit_rate']:.2%}, "
                f"hits/misses {levers['D_cache']['warm_hits']}/"
                f"{levers['D_cache']['warm_misses']} | "
                f"real corpus {levers['D_cache']['real_corpus']} |"
            ),
            (
                f"| C static fixers | {levers['C_static_fixers']['gate_passed']} | "
                f"fixed {levers['C_static_fixers']['fixer_resolved_rate']:.2%}, "
                f"retry calls down "
                f"{levers['C_static_fixers']['retry_call_reduction']:.2%}, "
                f"real pkg probe {levers['C_static_fixers']['real_package_manager_passed']}/"
                f"{levers['C_static_fixers']['real_package_manager_cases']}, "
                f"scratch import probe {levers['C_static_fixers']['scratch_import_failure_passed']}/"
                f"{levers['C_static_fixers']['scratch_import_failure_cases']} | "
                f"real corpus {levers['C_static_fixers']['real_corpus']} |"
            ),
            (
                f"| A recipes | {levers['A_recipes']['gate_passed']} | "
                f"match-rate {levers['A_recipes']['match_rate']:.2%}, "
                f"planner calls saved {levers['A_recipes']['planner_calls_saved']} | "
                f"LLM baseline {levers['A_recipes']['llm_baseline_present']}, "
                f"real corpus {levers['A_recipes']['real_corpus']} |"
            ),
            (
                f"| B codegen | {levers['B_codegen']['gate_passed']} | "
                f"codegen share {levers['B_codegen']['codegen_share']:.2%}, "
                f"pass-rate {levers['B_codegen']['pass_rate']:.2%}, "
                f"avg {levers['B_codegen']['avg_codegen_ms']} ms | "
                f"LLM baseline {levers['B_codegen']['llm_baseline_present']}, "
                f"real corpus {levers['B_codegen']['real_corpus']} |"
            ),
            (
                f"| scratch preflight | "
                f"{levers['scratch_preflight']['ready_for_live_gate']} | "
                f"blockers {levers['scratch_preflight']['blocker_count']} | "
                "ready for matrix execution |"
            ),
            (
                f"| scratch live gate | "
                f"{levers['scratch_live_gate']['e2e_green_ge_80']} | "
                f"{levers['scratch_live_gate']['e2e_green']}/"
                f"{levers['scratch_live_gate']['total_runs']} e2e green, "
                f"SkillOpt {levers['scratch_live_gate']['skillopt_approved']}/"
                f"{levers['scratch_live_gate']['skillopt_reviews']} approved, "
                f"median {levers['scratch_live_gate']['median_wall_clock_s']} s | "
                f"full matrix {levers['scratch_live_gate']['full_matrix']} |"
            ),
        ]
    )
    lines.extend(["", "## Modeled Call Path", ""])
    for step in path["steps"]:
        gate = step.get("gate_passed")
        gate_text = "" if gate is None else f", gate={gate}"
        lines.append(f"- {step['name']}: {step['calls']} calls{gate_text}")
    lines.extend(
        [
            "",
            "## Release Call Proof",
            "",
            f"- release matrix present: {proof['present']}",
            f"- baseline calls: {proof['baseline_calls']}",
            f"- actual calls: {proof['actual_calls']}",
            f"- calls saved: {proof['calls_saved']}",
            (
                "- planner calls saved by recipes: "
                f"{proof['planner_calls_saved_by_recipes']}"
            ),
            f"- task calls handled by codegen: {proof['tasks_codegen']}",
            f"- remaining task-level LLM calls: {proof['tasks_llm']}",
        ]
    )
    lines.extend(["", "## Missing Release Evidence", ""])
    for item in summary["missing_release_evidence"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", type=Path, default=RESULTS_JSON)
    parser.add_argument("--md-output", type=Path, default=RESULTS_MD)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_summary()
    write_reports(result, args.json_output, args.md_output)
    if not args.quiet:
        print(json.dumps(result["summary"], indent=2, sort_keys=True))
        print(f"wrote {args.json_output}")
        print(f"wrote {args.md_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
