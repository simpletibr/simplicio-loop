"""Benchmark scratch plan recipes against a mixed synthetic goal corpus.

This measures lever A from the LLM-reduction roadmap: common scratch goals
should instantiate validated declarative plans without calling the planner LLM.
It is keyless and deterministic; it does not replace the real 50-scratch gate.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simplicio.scratch.recipes import RecipeRegistry  # noqa: E402
from simplicio.scratch import planner as scratch_planner  # noqa: E402
from simplicio.scratch.plan_schema import validate_plan  # noqa: E402
from simplicio.scratch.stack_registry import StackRegistry, slugify_project  # noqa: E402


RESULTS_JSON = ROOT / "bench" / "results_scratch_recipes.json"
RESULTS_MD = ROOT / "bench" / "results_scratch_recipes.md"
LLM_BASELINE_JSON = ROOT / "bench" / "results_scratch_recipes_llm_baseline.json"
LIVE_GATE_JSON = ROOT / "bench" / "results_scratch_live_gate.json"


@dataclass(frozen=True)
class RecipeCase:
    stack: str
    goal: str
    expected_match: bool
    expected_recipe: str | None = None


def build_cases() -> list[RecipeCase]:
    matched = [
        ("py-fastapi", "CRUD API for Unit", "crud-resource"),
        ("py-fastapi", "REST API for Invoice", "crud-resource"),
        ("py-fastapi", "CRUD API for Visitor", "crud-resource"),
        ("py-fastapi", "REST API for AmenityBooking", "crud-resource"),
        ("py-fastapi", "CRUD API for Vendor", "crud-resource"),
        ("py-fastapi", "admin panel for Booking", "admin-crud"),
        ("py-fastapi", "admin panel for Document", "admin-crud"),
        ("py-fastapi", "admin panel for Resident", "admin-crud"),
        ("py-fastapi", "add JWT auth", "auth-jwt"),
        ("py-fastapi", "login with JWT", "auth-jwt"),
        ("py-fastapi", "authentication with JWT", "auth-jwt"),
        ("py-fastapi", "Create websocket chat rooms", "websocket"),
        ("py-fastapi", "REST API for ParkingSpace", "crud-resource"),
        ("py-fastapi", "CRUD API for PackageDelivery", "crud-resource"),
        ("py-fastapi", "admin panel for Announcement", "admin-crud"),
        ("py-fastapi", "CRUD API for Payment", "crud-resource"),
        ("ts-nextjs", "Manage Product with CRUD", "crud-resource"),
        ("ts-nextjs", "CRUD page for Unit", "crud-resource"),
        ("ts-nextjs", "Manage Invoice with CRUD", "crud-resource"),
        ("ts-nextjs", "CRUD page for Visitor", "crud-resource"),
        ("ts-nextjs", "Manage Vendor with CRUD", "crud-resource"),
        ("ts-nextjs", "admin CRUD for Tenant", "admin-crud"),
        ("ts-nextjs", "backoffice to manage Subscription", "admin-crud"),
        ("ts-nextjs", "admin CRUD for Booking", "admin-crud"),
        ("ts-nextjs", "authentication with JWT", "auth-jwt"),
        ("ts-nextjs", "login with JWT", "auth-jwt"),
        ("ts-nextjs", "add JWT auth", "auth-jwt"),
        ("ts-nextjs", "Manage Document with CRUD", "crud-resource"),
        ("ts-nextjs", "CRUD page for ParkingSpace", "crud-resource"),
        ("ts-nextjs", "backoffice to manage Payment", "admin-crud"),
        ("ts-nextjs", "Manage AccessDevice with CRUD", "crud-resource"),
    ]
    misses = [
        ("py-fastapi", "Build a recommendation engine for movies"),
        ("py-fastapi", "Analyze CSV exports overnight"),
        ("py-fastapi", "Generate a billing report"),
        ("py-fastapi", "Import legacy XML data"),
        ("py-fastapi", "Build a workflow scheduler"),
        ("py-fastapi", "Create an ML inference gateway"),
        ("py-fastapi", "Synchronize LDAP groups"),
        ("py-fastapi", "Build a search ranking service"),
        ("py-fastapi", "Create a geocoding proxy"),
        ("ts-nextjs", "Create a marketing landing page"),
        ("ts-nextjs", "Render a public docs site"),
        ("ts-nextjs", "Add image optimization pipeline"),
        ("ts-nextjs", "Design a pricing comparison table"),
        ("ts-nextjs", "Build a chart dashboard"),
        ("ts-nextjs", "Create a theme editor"),
        ("ts-nextjs", "Build a map explorer"),
        ("ts-nextjs", "Add offline-first sync"),
        ("ts-nextjs", "Create a video playlist page"),
        ("ts-nextjs", "Build an onboarding wizard"),
    ]
    return [
        RecipeCase(stack, goal, True, recipe) for stack, goal, recipe in matched
    ] + [RecipeCase(stack, goal, False) for stack, goal in misses]


def run_benchmark(
    cases: list[RecipeCase] | None = None,
    *,
    llm_baseline: dict[str, Any] | None = None,
    live_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registry = RecipeRegistry()
    baseline = _normalize_llm_baseline(llm_baseline) if llm_baseline else None
    live_corpus = _normalize_live_recipe_corpus(live_gate) if live_gate else None
    rows = []
    t0 = time.perf_counter()
    for case in cases or build_cases():
        started = time.perf_counter()
        match = registry.match(case.goal, case.stack)
        plan_valid = False
        task_count = 0
        error = ""
        if match is not None:
            try:
                plan = registry.get(match.recipe_name, match.stack_slug).instantiate(
                    match,
                    slugify_project(case.goal),
                )
                plan_valid = True
                task_count = len(plan.tasks)
            except Exception as exc:  # pragma: no cover - defensive report detail
                error = f"{type(exc).__name__}: {exc}"

        actual_recipe = match.recipe_name if match is not None else None
        rows.append(
            {
                "stack": case.stack,
                "goal": case.goal,
                "expected_match": case.expected_match,
                "expected_recipe": case.expected_recipe,
                "matched": match is not None,
                "actual_recipe": actual_recipe,
                "expected_match_correct": (match is not None) == case.expected_match,
                "expected_recipe_correct": (
                    actual_recipe == case.expected_recipe
                    if case.expected_match
                    else actual_recipe is None
                ),
                "plan_valid": plan_valid,
                "task_count": task_count,
                "planner_calls_saved": 1 if match is not None else 0,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "error": error,
            }
        )

    elapsed_s = round(time.perf_counter() - t0, 3)
    return {
        "benchmark": "scratch-recipes",
        "scope": (
            "synthetic declarative recipe benchmark; validates match-before-planner "
            "coverage and plan schema integrity; optional live-gate input proves "
            "recipe coverage on the real scratch release corpus"
        ),
        "date": time.strftime("%Y-%m-%d"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "llm_baseline": baseline,
        "live_corpus": live_corpus,
        "summary": _summarize(rows, elapsed_s, baseline, live_corpus),
        "cases": rows,
    }


def capture_llm_baseline(
    *,
    work_dir: Path,
    cases: list[RecipeCase] | None = None,
    case_limit: int | None = None,
) -> dict[str, Any]:
    """Capture an equivalent planner LLM baseline with recipe matching bypassed."""
    planner_route = os.environ.get("SIMPLICIO_PLANNER", "").strip()
    if not planner_route:
        raise RuntimeError(
            "SIMPLICIO_PLANNER must be set to capture a recipe LLM baseline"
        )

    work_dir.mkdir(parents=True, exist_ok=True)
    baseline_cases = [case for case in cases or build_cases() if case.expected_match]
    if case_limit is not None:
        baseline_cases = baseline_cases[: max(0, case_limit)]

    rows = []
    t0 = time.perf_counter()
    for case in baseline_cases:
        rows.append(_run_llm_baseline_case(case, work_dir))

    elapsed_s = round(time.perf_counter() - t0, 3)
    return {
        "benchmark": "scratch-recipes-llm-baseline",
        "source": "captured by bench/run_scratch_recipes.py --capture-llm-baseline-json",
        "scope": (
            "equivalent planner LLM baseline for matched recipe goals; recipe "
            "matching is bypassed and the planner output is schema-validated"
        ),
        "work_dir": "$WORK_DIR",
        "date": time.strftime("%Y-%m-%d"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "planner": planner_route,
        },
        "summary": _summarize_llm_baseline(rows, elapsed_s, planner_route),
        "cases": rows,
    }


def _run_llm_baseline_case(case: RecipeCase, work_dir: Path) -> dict[str, Any]:
    registry = StackRegistry()
    stack = registry.get(case.stack)
    project_name = slugify_project(case.goal)
    case_dir = work_dir / project_name
    case_dir.mkdir(parents=True, exist_ok=True)
    _ensure_git_repo(case_dir)
    started = time.perf_counter()
    previous_cwd = Path.cwd()
    try:
        os.chdir(case_dir)
        prompt = scratch_planner._build_prompt(stack, case.goal, project_name)
        raw = scratch_planner.planner_complete(prompt, template_version=stack.version)
        parsed = scratch_planner._extract_json(raw)
        if parsed is None:
            raise ValueError("planner output did not contain a JSON object")
        plan = validate_plan(parsed)
        stack_matches = plan.stack == case.stack
        passed = bool(plan.tasks) and stack_matches
        error = "" if passed else f"plan stack mismatch: {plan.stack} != {case.stack}"
        task_count = len(plan.tasks)
    except Exception as exc:  # pragma: no cover - defensive report detail
        passed = False
        error = f"{type(exc).__name__}: {exc}"
        task_count = 0
    finally:
        os.chdir(previous_cwd)

    return {
        "stack": case.stack,
        "goal": case.goal,
        "expected_recipe": case.expected_recipe,
        "passed": passed,
        "task_count": task_count,
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "error": error,
    }


def _ensure_git_repo(path: Path) -> None:
    if (path / ".git").is_dir():
        return
    subprocess.run(
        ["git", "init", "-q"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )


def _summarize(
    rows: list[dict[str, Any]],
    elapsed_s: float,
    llm_baseline: dict[str, Any] | None = None,
    live_corpus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    total = len(rows)
    matched = sum(1 for row in rows if row["matched"])
    valid = sum(1 for row in rows if row["plan_valid"])
    match_correct = sum(1 for row in rows if row["expected_match_correct"])
    recipe_correct = sum(1 for row in rows if row["expected_recipe_correct"])
    planner_calls_saved = sum(int(row["planner_calls_saved"]) for row in rows)
    match_rate = round(matched / total, 4) if total else 0.0
    recipe_plan_pass_rate = round(valid / matched, 4) if matched else 0.0
    summary = {
        "total_cases": total,
        "matched_cases": matched,
        "missed_cases": total - matched,
        "match_rate": match_rate,
        "valid_recipe_plans": valid,
        "expected_match_accuracy": round(match_correct / total, 4) if total else 0.0,
        "expected_recipe_accuracy": round(recipe_correct / total, 4) if total else 0.0,
        "planner_calls_saved": planner_calls_saved,
        "recipe_plan_pass_rate": recipe_plan_pass_rate,
        "elapsed_s": elapsed_s,
    }
    if llm_baseline:
        summary["llm_baseline"] = llm_baseline
        summary["recipe_plan_pass_rate_ge_llm"] = recipe_plan_pass_rate >= float(
            llm_baseline["pass_rate"]
        )
    else:
        summary["recipe_plan_pass_rate_ge_llm"] = None
    if live_corpus:
        summary["live_corpus"] = live_corpus
    summary["release_gates"] = {
        "fifty_goal_corpus": total >= 50,
        "recipe_match_ge_40": match_rate >= 0.40,
        "matched_plans_valid": valid == matched,
        "expected_match_accuracy_100": match_correct == total,
        "real_scratch_corpus": bool(
            live_corpus and int(live_corpus.get("total_runs", 0)) >= 50
        ),
        "real_recipe_match_ge_40": bool(
            live_corpus and float(live_corpus.get("match_rate", 0.0)) >= 0.40
        ),
        "real_recipe_plans_valid": bool(
            live_corpus
            and int(live_corpus.get("valid_recipe_plans", 0))
            == int(live_corpus.get("matched_runs", 0))
        ),
        "real_e2e_green_ge_80": bool(
            live_corpus and float(live_corpus.get("e2e_green_rate", 0.0)) >= 0.80
        ),
        "llm_pass_rate_baseline_present": llm_baseline is not None,
        "llm_baseline_covers_matched_cases": (
            int(llm_baseline.get("total_cases", 0)) >= matched
            if llm_baseline
            else False
        ),
        "recipe_plan_pass_rate_ge_llm": summary["recipe_plan_pass_rate_ge_llm"],
    }
    summary["missing_release_evidence"] = [
        "aggregate call-reduction proof across cache, recipes, fixers, and executors",
    ]
    if not summary["release_gates"]["real_scratch_corpus"]:
        summary["missing_release_evidence"].append("real 50-scratch recipe corpus")
    if (
        summary["release_gates"]["real_scratch_corpus"]
        and not summary["release_gates"]["real_recipe_match_ge_40"]
    ):
        summary["missing_release_evidence"].append(
            "real recipe match-rate >=40% on scratch corpus"
        )
    if (
        summary["release_gates"]["real_scratch_corpus"]
        and not summary["release_gates"]["real_recipe_plans_valid"]
    ):
        summary["missing_release_evidence"].append(
            "real recipe plans valid on matched scratch corpus"
        )
    if (
        summary["release_gates"]["real_scratch_corpus"]
        and not summary["release_gates"]["real_e2e_green_ge_80"]
    ):
        summary["missing_release_evidence"].append(
            "real recipe scratch e2e green rate >=80%"
        )
    if not summary["release_gates"]["llm_pass_rate_baseline_present"]:
        summary["missing_release_evidence"].append(
            "recipe path pass-rate compared with equivalent LLM path"
        )
    elif not summary["release_gates"]["llm_baseline_covers_matched_cases"]:
        summary["missing_release_evidence"].append(
            "LLM recipe baseline covering all matched recipe cases"
        )
    elif summary["release_gates"]["recipe_plan_pass_rate_ge_llm"] is not True:
        summary["missing_release_evidence"].append(
            "recipe path pass-rate >= equivalent LLM path"
        )
    return summary


def _summarize_llm_baseline(
    rows: list[dict[str, Any]],
    elapsed_s: float,
    planner_route: str,
) -> dict[str, Any]:
    total = len(rows)
    passed = sum(1 for row in rows if row["passed"])
    durations = [
        int(row.get("duration_ms", 0))
        for row in rows
        if int(row.get("duration_ms", 0)) > 0
    ]
    return {
        "total_cases": total,
        "passed_cases": passed,
        "failed_cases": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "avg_llm_ms": max(1, round(sum(durations) / len(durations)))
        if durations
        else 0,
        "elapsed_s": elapsed_s,
        "planner": planner_route,
    }


def load_llm_baseline(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return _normalize_llm_baseline(data, source=_source_label(path))


def load_live_gate_evidence(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return _normalize_live_recipe_corpus(data, source=_source_label(path))


def write_llm_baseline(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")


def _normalize_llm_baseline(
    baseline: dict[str, Any],
    *,
    source: str | None = None,
) -> dict[str, Any]:
    summary = baseline.get("summary")
    values = summary if isinstance(summary, dict) else baseline
    pass_rate = values.get("pass_rate")
    avg_ms = values.get("avg_llm_ms")
    total_cases = values.get("total_cases")
    if total_cases is None:
        cases = baseline.get("cases", [])
        total_cases = len(cases) if isinstance(cases, list) else 0
    if pass_rate is None or avg_ms is None:
        raise ValueError("LLM baseline must include pass_rate and avg_llm_ms")
    return {
        "source": baseline.get("source") or source or "inline",
        "total_cases": int(total_cases or 0),
        "pass_rate": float(pass_rate),
        "avg_llm_ms": int(avg_ms),
    }


def _normalize_live_recipe_corpus(
    live_gate: dict[str, Any],
    *,
    source: str | None = None,
) -> dict[str, Any]:
    if "runs" not in live_gate:
        return {
            "source": live_gate.get("source") or source or "inline",
            "total_runs": int(live_gate.get("total_runs", 0)),
            "matched_runs": int(live_gate.get("matched_runs", 0)),
            "valid_recipe_plans": int(live_gate.get("valid_recipe_plans", 0)),
            "match_rate": float(live_gate.get("match_rate", 0.0)),
            "recipe_plan_pass_rate": float(live_gate.get("recipe_plan_pass_rate", 0.0)),
            "planner_calls_saved": int(live_gate.get("planner_calls_saved", 0)),
            "e2e_green": int(live_gate.get("e2e_green", 0)),
            "e2e_green_rate": float(live_gate.get("e2e_green_rate", 0.0)),
            "stacks": sorted(live_gate.get("stacks", [])),
            "cases": live_gate.get("cases", []),
        }

    registry = RecipeRegistry()
    rows = []
    runs = live_gate.get("runs")
    runs = runs if isinstance(runs, list) else []
    for run in runs:
        stack = str(run.get("stack") or "")
        goal = str(run.get("goal") or "")
        match = None
        plan_valid = False
        task_count = 0
        error = ""
        if stack and goal:
            try:
                match = registry.match(goal, stack)
                if match is not None:
                    plan = registry.get(
                        match.recipe_name, match.stack_slug
                    ).instantiate(
                        match,
                        slugify_project(goal),
                    )
                    plan_valid = True
                    task_count = len(plan.tasks)
            except Exception as exc:  # pragma: no cover - defensive report detail
                error = f"{type(exc).__name__}: {exc}"
        rows.append(
            {
                "stack": stack,
                "goal": goal,
                "matched": match is not None,
                "actual_recipe": match.recipe_name if match is not None else None,
                "plan_valid": plan_valid,
                "task_count": task_count,
                "e2e_green": bool(run.get("e2e_green")),
                "error": error,
            }
        )

    total = len(rows)
    matched = sum(1 for row in rows if row["matched"])
    valid = sum(1 for row in rows if row["plan_valid"])
    e2e_green = sum(1 for row in rows if row["e2e_green"])
    return {
        "source": live_gate.get("source") or source or "inline",
        "total_runs": total,
        "matched_runs": matched,
        "valid_recipe_plans": valid,
        "match_rate": round(matched / total, 4) if total else 0.0,
        "recipe_plan_pass_rate": round(valid / matched, 4) if matched else 0.0,
        "planner_calls_saved": matched,
        "e2e_green": e2e_green,
        "e2e_green_rate": round(e2e_green / total, 4) if total else 0.0,
        "stacks": sorted({row["stack"] for row in rows if row["stack"]}),
        "cases": rows,
    }


def _source_label(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def write_reports(result: dict[str, Any], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_to_markdown(result), encoding="utf-8")


def _to_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Scratch Recipe Benchmark",
        "",
        result["scope"],
        "",
        "## Summary",
        "",
        f"- cases: {summary['total_cases']}",
        f"- matched: {summary['matched_cases']}",
        f"- match rate: {summary['match_rate']:.2%}",
        f"- valid recipe plans: {summary['valid_recipe_plans']}",
        f"- recipe plan pass-rate: {summary['recipe_plan_pass_rate']:.2%}",
        f"- planner calls saved: {summary['planner_calls_saved']}",
        "",
        "## Release Gate Status",
        "",
    ]
    for gate, value in summary["release_gates"].items():
        lines.append(f"- {gate}: {value}")
    missing = summary.get("missing_release_evidence") or []
    if missing:
        lines.extend(["", "## Missing Release Evidence", ""])
        lines.extend(f"- {item}" for item in missing)
    baseline = summary.get("llm_baseline")
    if baseline:
        lines.extend(
            [
                "",
                "## LLM Baseline",
                "",
                f"- source: {baseline['source']}",
                f"- cases: {baseline['total_cases']}",
                f"- pass rate: {baseline['pass_rate']:.2%}",
                f"- avg LLM latency: {baseline['avg_llm_ms']} ms",
                f"- recipe pass-rate >= LLM: {summary['recipe_plan_pass_rate_ge_llm']}",
            ]
        )
    live = summary.get("live_corpus")
    if live:
        lines.extend(
            [
                "",
                "## Live Recipe Corpus",
                "",
                f"- source: {live['source']}",
                f"- runs: {live['total_runs']}",
                f"- matched: {live['matched_runs']}",
                f"- match rate: {live['match_rate']:.2%}",
                f"- valid recipe plans: {live['valid_recipe_plans']}",
                f"- recipe plan pass-rate: {live['recipe_plan_pass_rate']:.2%}",
                f"- planner calls saved: {live['planner_calls_saved']}",
                f"- e2e green: {live['e2e_green']}/{live['total_runs']}",
                f"- stacks: {', '.join(live['stacks'])}",
            ]
        )
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| stack | goal | recipe | matched | plan_valid |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in result["cases"]:
        lines.append(
            "| {stack} | {goal} | {recipe} | {matched} | {valid} |".format(
                stack=row["stack"],
                goal=row["goal"],
                recipe=row["actual_recipe"] or "-",
                matched=row["matched"],
                valid=row["plan_valid"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", type=Path, default=RESULTS_JSON)
    parser.add_argument("--md-output", type=Path, default=RESULTS_MD)
    parser.add_argument(
        "--llm-baseline-json",
        type=Path,
        help="Path to a captured recipe LLM baseline JSON.",
    )
    parser.add_argument(
        "--capture-llm-baseline-json",
        type=Path,
        help="Capture a planner LLM baseline for matched recipe goals.",
    )
    parser.add_argument(
        "--baseline-case-limit",
        type=int,
        help="Limit matched recipe cases when capturing an LLM baseline.",
    )
    parser.add_argument(
        "--live-gate-json",
        type=Path,
        default=LIVE_GATE_JSON,
        help="Path to scratch live-gate JSON used to prove real recipe corpus coverage.",
    )
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.llm_baseline_json and args.capture_llm_baseline_json:
        print(
            "choose only one of --llm-baseline-json or --capture-llm-baseline-json",
            file=sys.stderr,
        )
        return 2
    llm_baseline = None
    if args.capture_llm_baseline_json:
        baseline_work_dir = args.work_dir or (
            ROOT / ".tmp" / "scratch-recipes-llm-baseline"
        )
        try:
            captured = capture_llm_baseline(
                work_dir=baseline_work_dir,
                case_limit=args.baseline_case_limit,
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        write_llm_baseline(captured, args.capture_llm_baseline_json)
        llm_baseline = captured
    elif args.llm_baseline_json:
        llm_baseline = load_llm_baseline(args.llm_baseline_json)

    live_gate = None
    if args.live_gate_json and args.live_gate_json.is_file():
        live_gate = load_live_gate_evidence(args.live_gate_json)

    result = run_benchmark(llm_baseline=llm_baseline, live_gate=live_gate)
    write_reports(result, args.json_output, args.md_output)
    if not args.quiet:
        print(json.dumps(result["summary"], indent=2, sort_keys=True))
        print(f"wrote {args.json_output}")
        print(f"wrote {args.md_output}")
    gates = result["summary"]["release_gates"]
    return 0 if gates["recipe_match_ge_40"] and gates["matched_plans_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
