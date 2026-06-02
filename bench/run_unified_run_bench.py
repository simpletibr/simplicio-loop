"""Fixture-backed F5 report for the unified ``simplicio-py run`` bench.

Issue #41 asks for a head-to-head bench comparing the existing cli+ag task loop,
the unified feature/sprint orchestrator, and Codex ``/goal`` on a controlled
sprint. This script records that comparison shape without invoking any LLM or
external agent. The output is intentionally marked as fixture evidence so a
future live run can replace the rows without changing the report schema.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent

RESULTS_JSON = ROOT / "bench" / "results_unified_run_bench.json"
RESULTS_MD = ROOT / "bench" / "results_unified_run_bench.md"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)

DEFAULT_CASES: list[dict[str, Any]] = [
    {
        "case_id": "single-file-task",
        "scope": "task",
        "goal": "Fix email validation in src/forms/UserForm.tsx.",
        "expected_tasks": 1,
        "expected_files": 1,
        "dod_gates": 1,
    },
    {
        "case_id": "feature-auth-flow",
        "scope": "feature",
        "goal": "Implement JWT login with refresh tokens across API and UI.",
        "expected_tasks": 4,
        "expected_files": 4,
        "dod_gates": 2,
    },
    {
        "case_id": "sprint-checkout-hardening",
        "scope": "sprint",
        "goal": "Finish checkout sprint with billing, reports, and DoD green.",
        "expected_tasks": 7,
        "expected_files": 8,
        "dod_gates": 4,
    },
]

MODES: list[dict[str, Any]] = [
    {
        "mode_id": "cli_ag",
        "label": "cli+ag task loop",
        "entrypoint": "simplicio-py task",
        "decomposition_owner": "human",
        "replan_scope": "none",
        "cost_visibility": "per atomic task",
        "observable": True,
    },
    {
        "mode_id": "unified_feature",
        "label": "unified run feature",
        "entrypoint": "simplicio-py run --scope feature",
        "decomposition_owner": "planner",
        "replan_scope": "remaining feature tasks",
        "cost_visibility": "cost governor",
        "observable": True,
    },
    {
        "mode_id": "unified_sprint",
        "label": "unified run sprint",
        "entrypoint": "simplicio-py run --scope sprint --max-cost <usd>",
        "decomposition_owner": "sprint loader and planner",
        "replan_scope": "feature tasks inside sprint",
        "cost_visibility": "required cost governor",
        "observable": True,
    },
    {
        "mode_id": "codex_goal",
        "label": "Codex /goal",
        "entrypoint": "codex /goal",
        "decomposition_owner": "external agent",
        "replan_scope": "opaque",
        "cost_visibility": "opaque in this repo bench",
        "observable": False,
    },
]


def run_benchmark(
    cases: list[dict[str, Any]] | None = None,
    *,
    live_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    fixtures = _normalize_cases(cases or DEFAULT_CASES)
    rows = [
        _fixture_row(case, mode)
        for case in fixtures
        for mode in MODES
    ]
    live_errors: list[str] = []
    if live_results:
        rows, live_errors = _merge_live_results(rows, live_results)
    summary = _summarize(rows, fixtures)
    if live_errors:
        summary["live_result_errors"] = live_errors
        summary["release_ready"] = False
    return {
        "benchmark": (
            "unified-run-f5-live" if summary["evidence_level"] == "live"
            else "unified-run-f5-fixture"
        ),
        "issue": "#41",
        "phase": "F5",
        "scope": (
            "planned fixture comparison for cli+ag, unified feature/sprint, "
            "and Codex /goal; fixture rows are replaced by live rows when "
            "--live-results-json supplies comparable evidence"
        ),
        "fixture_only": summary["fixture_only"],
        "date": time.strftime("%Y-%m-%d"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "modes": MODES,
        "cases": fixtures,
        "rows": rows,
        "summary": summary,
    }


def _normalize_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for index, case in enumerate(cases, start=1):
        scope = str(case.get("scope", "")).strip()
        if scope not in {"task", "feature", "sprint"}:
            raise ValueError(f"case {index} has unsupported scope: {scope!r}")
        expected_tasks = int(case.get("expected_tasks", 0))
        if expected_tasks < 1:
            raise ValueError(f"case {index} expected_tasks must be >= 1")
        normalized.append(
            {
                "case_id": str(case.get("case_id") or f"case-{index:02d}"),
                "scope": scope,
                "goal": str(case.get("goal", "")).strip(),
                "expected_tasks": expected_tasks,
                "expected_files": int(case.get("expected_files", expected_tasks)),
                "dod_gates": int(case.get("dod_gates", 0)),
            }
        )
    return normalized


def _fixture_row(case: dict[str, Any], mode: dict[str, Any]) -> dict[str, Any]:
    scope = case["scope"]
    mode_id = mode["mode_id"]
    expected_tasks = case["expected_tasks"]

    row: dict[str, Any] = {
        "case_id": case["case_id"],
        "scope": scope,
        "mode_id": mode_id,
        "fixture": True,
        "llm_invoked": False,
        "external_agent_invoked": False,
        "expected_task_runs": expected_tasks,
        "planner_calls": 0,
        "manual_decomposition_required": False,
        "replan_supported": False,
        "resume_state_supported": False,
        "dod_gate_supported": False,
        "cost_cap_required": False,
        "cost_observable": bool(mode["observable"]),
        "outcome": "planned",
        "notes": [],
        "command": "",
        "exit_code": None,
        "duration_s": None,
        "success": None,
        "cost_usd": None,
        "artifacts": [],
        "transcript_sha256": "",
    }

    if mode_id == "cli_ag":
        if scope == "task":
            row["expected_task_runs"] = 1
            row["outcome"] = "covered_by_existing_atomic_loop"
        else:
            row["manual_decomposition_required"] = True
            row["outcome"] = "requires_human_decomposition"
            row["notes"].append("cli+ag has no native feature or sprint planner")
    elif mode_id == "unified_feature":
        if scope == "task":
            row["expected_task_runs"] = 1
            row["outcome"] = "dispatches_to_task"
        elif scope == "feature":
            row["planner_calls"] = 1
            row["replan_supported"] = True
            row["outcome"] = "covered_by_feature_orchestrator"
        else:
            row["planner_calls"] = max(1, expected_tasks // 3)
            row["manual_decomposition_required"] = True
            row["replan_supported"] = True
            row["outcome"] = "feature_loop_only_after_sprint_decomposition"
            row["notes"].append("needs sprint loader to provide feature-sized goals")
    elif mode_id == "unified_sprint":
        row["cost_cap_required"] = scope == "sprint"
        row["dod_gate_supported"] = scope in {"feature", "sprint"}
        row["resume_state_supported"] = scope == "sprint"
        if scope == "sprint":
            row["planner_calls"] = max(1, expected_tasks // 3)
            row["replan_supported"] = True
            row["outcome"] = "covered_by_sprint_orchestrator"
        else:
            row["outcome"] = "not_the_primary_scope"
            row["notes"].append("use task or feature mode for this scope")
    elif mode_id == "codex_goal":
        row["external_agent_invoked"] = False
        row["cost_observable"] = False
        row["replan_supported"] = True
        row["resume_state_supported"] = None
        row["dod_gate_supported"] = None
        row["outcome"] = "external_baseline_placeholder"
        row["notes"].append("live Codex /goal run is required for real comparison")
    return row


def _merge_live_results(
    fixture_rows: list[dict[str, Any]],
    live_results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows_by_key = {
        (row["case_id"], row["mode_id"]): dict(row)
        for row in fixture_rows
    }
    errors = []
    seen_live_keys: set[tuple[str, str]] = set()
    for index, live in enumerate(live_results, start=1):
        case_id = str(live.get("case_id") or "").strip()
        mode_id = str(live.get("mode_id") or "").strip()
        key = (case_id, mode_id)
        if key in seen_live_keys:
            errors.append(f"live row {index} duplicates case/mode: {case_id}/{mode_id}")
            continue
        seen_live_keys.add(key)
        if key not in rows_by_key:
            errors.append(f"live row {index} has unknown case/mode: {case_id}/{mode_id}")
            continue
        row = rows_by_key[key]
        command = str(live.get("command") or "").strip()
        exit_code = live.get("exit_code")
        success = live.get("success")
        duration_s = _nonnegative_number(live.get("duration_s"))
        cost_usd = _optional_nonnegative_number(live.get("cost_usd"))
        if not command or not isinstance(exit_code, int) or not isinstance(success, bool):
            errors.append(
                f"live row {index} missing required command, exit_code, or success"
            )
            continue
        if success != (exit_code == 0):
            errors.append(
                f"live row {index} success must match exit_code==0"
            )
            continue
        if duration_s is None:
            errors.append(f"live row {index} duration_s must be finite and >= 0")
            continue
        if cost_usd is None and live.get("cost_usd") is not None:
            errors.append(f"live row {index} cost_usd must be finite and >= 0")
            continue
        artifacts, artifact_errors = _artifact_list(live.get("artifacts"), index)
        if artifact_errors:
            errors.extend(artifact_errors)
            continue
        row.update(
            {
                "fixture": False,
                "llm_invoked": bool(live.get("llm_invoked", mode_id != "cli_ag")),
                "external_agent_invoked": bool(
                    live.get("external_agent_invoked", mode_id == "codex_goal")
                ),
                "outcome": "live_success" if success else "live_failure",
                "command": command,
                "exit_code": exit_code,
                "duration_s": duration_s,
                "success": success,
                "cost_usd": cost_usd,
                "artifacts": artifacts,
                "transcript_sha256": str(live.get("transcript_sha256") or ""),
                "notes": _string_list(live.get("notes")),
            }
        )
        rows_by_key[key] = row
    return list(rows_by_key.values()), errors


def _nonnegative_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _optional_nonnegative_number(value: Any) -> float | None:
    if value is None:
        return None
    return _nonnegative_number(value)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _artifact_list(value: Any, row_index: int) -> tuple[list[Any], list[str]]:
    if not isinstance(value, list):
        return [], []
    artifacts: list[Any] = []
    errors: list[str] = []
    for artifact_index, artifact in enumerate(value, start=1):
        if isinstance(artifact, str):
            label = artifact.strip()
            if label:
                artifacts.append(label)
            continue
        if not isinstance(artifact, dict):
            errors.append(
                _artifact_error(
                    row_index,
                    artifact_index,
                    "must be a string label or object",
                )
            )
            continue
        normalized, error = _verified_artifact(artifact)
        if error:
            errors.append(_artifact_error(row_index, artifact_index, error))
        else:
            artifacts.append(normalized)
    return artifacts, errors


def _artifact_error(row_index: int, artifact_index: int, message: str) -> str:
    return f"live row {row_index} artifact {artifact_index} {message}"


def _verified_artifact(artifact: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    path_value = artifact.get("path")
    sha_value = artifact.get("sha256")
    kind_value = artifact.get("kind")
    if (
        not isinstance(path_value, str)
        or not path_value.strip()
        or not isinstance(sha_value, str)
        or not sha_value.strip()
        or not isinstance(kind_value, str)
        or not kind_value.strip()
    ):
        return {}, "must include non-empty string path, sha256, and kind"
    expected_sha = sha_value.strip().lower()
    if not _is_sha256(expected_sha):
        return {}, "sha256 must be 64 hex characters"
    artifact_path = _resolve_artifact_path(path_value.strip())
    if artifact_path is None:
        return {}, "path must reference a file under repo root"
    actual_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        return {}, "sha256 does not match file contents"
    return {
        "path": artifact_path.relative_to(ROOT.resolve()).as_posix(),
        "sha256": expected_sha,
        "kind": kind_value.strip(),
        "verified": True,
    }, None


def _resolve_artifact_path(path_value: str) -> Path | None:
    root = ROOT.resolve()
    candidate = Path(path_value)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    if not resolved.is_file():
        return None
    return resolved


def _summarize(
    rows: list[dict[str, Any]],
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    by_mode: dict[str, dict[str, Any]] = {}
    for mode in MODES:
        mode_rows = [row for row in rows if row["mode_id"] == mode["mode_id"]]
        by_mode[mode["mode_id"]] = {
            "label": mode["label"],
            "rows": len(mode_rows),
            "manual_decomposition_cases": sum(
                1 for row in mode_rows if row["manual_decomposition_required"]
            ),
            "replan_supported_cases": sum(
                1 for row in mode_rows if row["replan_supported"] is True
            ),
            "resume_state_supported_cases": sum(
                1 for row in mode_rows if row["resume_state_supported"] is True
            ),
            "cost_observable_cases": sum(
                1 for row in mode_rows if row["cost_observable"] is True
            ),
            "cost_cap_required_cases": sum(
                1 for row in mode_rows if row["cost_cap_required"] is True
            ),
            "llm_invocations": sum(1 for row in mode_rows if row["llm_invoked"]),
            "external_agent_invocations": sum(
                1 for row in mode_rows if row["external_agent_invoked"]
            ),
        }

    expected_rows = len(cases) * len(MODES)
    live_rows = [row for row in rows if row["fixture"] is False]
    complete_live_matrix = len(live_rows) == expected_rows
    all_live_success = complete_live_matrix and all(
        row.get("success") is True for row in live_rows
    )
    codex_live = any(
        row["mode_id"] == "codex_goal"
        and row["fixture"] is False
        and row["external_agent_invoked"] is True
        and _is_sha256(row["transcript_sha256"])
        for row in rows
    )
    release_blockers = [
        "real cli+ag runs on the controlled task, feature, and sprint cases",
        "real unified feature/sprint runs with cost governor telemetry",
        "real Codex /goal baseline runs with comparable success and cost data",
        "artifact collection for sprint DoD evidence",
    ]
    if complete_live_matrix:
        release_blockers = []
        if not all_live_success:
            release_blockers.append("all live comparison rows must succeed")
        if not codex_live:
            release_blockers.append("Codex /goal live row needs transcript hash")
        if not any(
            _has_verified_artifact(row)
            for row in live_rows
            if row["scope"] == "sprint"
        ):
            release_blockers.append("artifact collection for sprint DoD evidence")
    evidence_level = "live" if complete_live_matrix and not release_blockers else (
        "partial-live" if live_rows else "fixture"
    )
    return {
        "fixture_only": not live_rows,
        "evidence_level": evidence_level,
        "case_count": len(cases),
        "mode_count": len(MODES),
        "row_count": len(rows),
        "expected_row_count": expected_rows,
        "live_row_count": len(live_rows),
        "schema_fixture_complete": len(rows) == expected_rows,
        "real_llm_runs_present": any(row["llm_invoked"] for row in rows),
        "external_codex_goal_run_present": codex_live,
        "release_ready": evidence_level == "live" and not release_blockers,
        "release_blockers": release_blockers,
        "head_to_head_ready_for_live_run": len(rows) == expected_rows,
        "by_mode": by_mode,
        "missing_live_evidence": release_blockers,
    }


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value.strip()))


def _has_verified_artifact(row: dict[str, Any]) -> bool:
    artifacts = row.get("artifacts")
    if not isinstance(artifacts, list):
        return False
    return any(
        isinstance(artifact, dict) and artifact.get("verified") is True
        for artifact in artifacts
    )


def write_reports(result: dict[str, Any], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_to_markdown(result), encoding="utf-8")


def write_partial_results(result: dict[str, Any], json_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(_partial_results(result), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _partial_results(result: dict[str, Any]) -> dict[str, Any]:
    """Build a non-release artifact for partial live observations."""
    observations = [
        {
            "case_id": row["case_id"],
            "scope": row["scope"],
            "mode_id": row["mode_id"],
            "outcome": row["outcome"],
            "observable": row["cost_observable"],
            "llm_invoked": row["llm_invoked"],
            "external_agent_invoked": row["external_agent_invoked"],
            "notes": row["notes"],
        }
        for row in result["rows"]
        if row["cost_observable"] is True
    ]
    return {
        "benchmark": result["benchmark"],
        "issue": result["issue"],
        "phase": result["phase"],
        "artifact": "partial-live-observations",
        "partial_only": True,
        "release_evidence": False,
        "release_ready": False,
        "evidence_level": "partial-only",
        "source_evidence_level": result["summary"]["evidence_level"],
        "observation_count": len(observations),
        "observations": observations,
        "notes": [
            "Partial live observations are diagnostic-only.",
            "This artifact must not be used as release evidence.",
        ],
    }


def _to_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Unified Run F5 Bench Fixture",
        "",
        result["scope"],
        "",
        "## Summary",
        "",
        f"- issue: {result['issue']}",
        f"- phase: {result['phase']}",
        f"- fixture only: {summary['fixture_only']}",
        f"- evidence level: {summary['evidence_level']}",
        f"- cases: {summary['case_count']}",
        f"- modes: {summary['mode_count']}",
        f"- rows: {summary['row_count']}/{summary['expected_row_count']}",
        f"- release ready: {summary['release_ready']}",
        (
            "- ready for live run: "
            f"{summary['head_to_head_ready_for_live_run']}"
        ),
        f"- live rows: {summary['live_row_count']}/{summary['expected_row_count']}",
        "",
        "## Modes",
        "",
        "| mode | entrypoint | decomposition | replan | cost visibility |",
        "| --- | --- | --- | --- | --- |",
    ]
    for mode in result["modes"]:
        lines.append(
            f"| {mode['label']} | `{mode['entrypoint']}` | "
            f"{mode['decomposition_owner']} | {mode['replan_scope']} | "
            f"{mode['cost_visibility']} |"
        )

    lines.extend(
        [
            "",
            "## Fixture Matrix",
            "",
            (
                "| case | scope | mode | outcome | task runs | planner calls | "
                "manual split | replan | cost observable |"
            ),
            "| --- | --- | --- | --- | ---: | ---: | --- | --- | --- |",
        ]
    )
    mode_labels = {mode["mode_id"]: mode["label"] for mode in result["modes"]}
    for row in result["rows"]:
        lines.append(
            f"| {row['case_id']} | {row['scope']} | "
            f"{mode_labels[row['mode_id']]} | {row['outcome']} | "
            f"{row['expected_task_runs']} | {row['planner_calls']} | "
            f"{row['manual_decomposition_required']} | "
            f"{row['replan_supported']} | {row['cost_observable']} |"
        )

    if summary["missing_live_evidence"]:
        lines.extend(["", "## Missing Live Evidence", ""])
        for item in summary["missing_live_evidence"]:
            lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-json",
        type=Path,
        help="Optional case fixture JSON. Expected shape: {'cases': [...]} or [...].",
    )
    parser.add_argument("--json-output", type=Path, default=RESULTS_JSON)
    parser.add_argument("--md-output", type=Path, default=RESULTS_MD)
    parser.add_argument(
        "--live-results-json",
        type=Path,
        help=(
            "Optional live evidence JSON with rows keyed by case_id and mode_id. "
            "Rows require command, exit_code, success, and duration_s."
        ),
    )
    parser.add_argument(
        "--partial-results-json",
        type=Path,
        help=(
            "Optional JSON path for partial live observations. The generated "
            "artifact is partial-only and never release evidence."
        ),
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def _load_cases(path: Path | None) -> list[dict[str, Any]] | None:
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("cases", [])
    if not isinstance(data, list):
        raise ValueError("fixture JSON must be a list or an object with a cases list")
    return data


def _load_live_results(path: Path | None) -> list[dict[str, Any]] | None:
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("rows", [])
    if not isinstance(data, list):
        raise ValueError("live results JSON must be a list or an object with a rows list")
    return data


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_benchmark(
        _load_cases(args.fixture_json),
        live_results=_load_live_results(args.live_results_json),
    )
    write_reports(result, args.json_output, args.md_output)
    if args.partial_results_json is not None:
        write_partial_results(result, args.partial_results_json)
    if not args.quiet:
        print(json.dumps(result["summary"], indent=2, sort_keys=True))
        print(f"wrote {args.json_output}")
        print(f"wrote {args.md_output}")
        if args.partial_results_json is not None:
            print(f"wrote {args.partial_results_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
