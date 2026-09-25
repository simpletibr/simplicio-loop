#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "tests" / "fixtures" / "evaluation_corpus" / "advanced" / "manifest.json"
SCHEMA = "simplicio.hypothesis-report/v1"
OUT_DIR = ".simplicio"
TOKEN_BUDGET = 512
LIMIT = 2

if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

from scripts import evaluation_scorecard  # noqa: E402
from simplicio_mapper.cli._status_engine import _load_mapper_artifacts  # noqa: E402
from simplicio_mapper.context_pack import build_context_pack  # noqa: E402
from simplicio_mapper.retrieval_index import load_retrieval_index, select_context_targets  # noqa: E402
from simplicio_mapper.task_intent import parse_task_intent  # noqa: E402


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def _estimate_tokens_from_bytes(byte_count: int) -> int:
    return max(1, math.ceil(byte_count / 4))


def _copy_case(case_root: Path) -> Path:
    tempdir = Path(tempfile.mkdtemp(prefix=f"mapper-hypothesis-{case_root.name}-"))
    shutil.copytree(case_root / "source", tempdir, dirs_exist_ok=True)
    return tempdir


def _task_goal(case_root: Path) -> tuple[str, dict[str, Any]]:
    task_file = case_root / "task.md"
    task_json = _load_json(case_root / "task.json")
    task_intent = parse_task_intent(task_file.read_text(encoding="utf-8"))
    goal = str(task_json.get("goal") or task_intent.get("goal") or "").strip()
    if not goal:
        goal = task_file.read_text(encoding="utf-8").strip()
    return goal, task_intent


def _filtered_artifacts(artifacts: dict[str, Any]) -> dict[str, Any]:
    project_map = dict(artifacts["project_map"])
    filtered_files = []
    for row in project_map.get("files", []):
        relpath = str(row.get("path") or "").replace("\\", "/")
        if relpath in {"task.md", "task.json"}:
            continue
        filtered_files.append(row)
    project_map["files"] = filtered_files
    for key in ("recent_changes", "changed_files", "entry_points", "test_files"):
        values = project_map.get(key)
        if isinstance(values, list):
            project_map[key] = [
                item
                for item in values
                if str((item.get("path") if isinstance(item, dict) else item) or "").replace("\\", "/")
                not in {"task.md", "task.json"}
            ]
    return {
        **artifacts,
        "project_map": project_map,
    }


def _score_baseline_file(root: Path, relpath: str, query_terms: set[str]) -> tuple[float, dict[str, Any]]:
    path = root / relpath
    preview = ""
    try:
        preview = path.read_text(encoding="utf-8")[:1200]
    except UnicodeDecodeError:
        preview = ""
    path_terms = set(_tokenize(relpath.replace("\\", "/")))
    content_terms = set(_tokenize(preview))
    path_hits = sorted(query_terms & path_terms)
    content_hits = sorted(query_terms & content_terms)
    score = float(len(path_hits) * 3 + len(content_hits))
    if relpath.startswith("src/"):
        score += 0.25
    elif relpath.startswith("tests/"):
        score += 0.15
    elif relpath.startswith("docs/"):
        score += 0.05
    return score, {
        "path_hits": path_hits,
        "content_hits": content_hits,
    }


def _baseline_selection(root: Path, project_map: dict[str, Any], goal: str) -> dict[str, Any]:
    query_terms = set(_tokenize(goal))
    rows: list[dict[str, Any]] = []
    for file_row in project_map.get("files", []):
        relpath = str(file_row.get("path") or "").replace("\\", "/")
        if not relpath or not (root / relpath).is_file():
            continue
        score, evidence = _score_baseline_file(root, relpath, query_terms)
        if score <= 0:
            continue
        rows.append(
            {
                "path": relpath,
                "relevance_score": round(score, 6),
                "relevance_reason": (
                    f"path_hits={','.join(evidence['path_hits']) or 'none'};"
                    f"content_hits={','.join(evidence['content_hits']) or 'none'}"
                ),
                "matched_terms": sorted(set(evidence["path_hits"] + evidence["content_hits"])),
                "recent_change_boost": False,
                "score_components": {
                    "path_hits": len(evidence["path_hits"]) * 3,
                    "content_hits": len(evidence["content_hits"]),
                },
                "reason_codes": [
                    *(f"path:{term}" for term in evidence["path_hits"]),
                    *(f"content:{term}" for term in evidence["content_hits"]),
                ],
                "ranges": [],
            }
        )
    rows.sort(key=lambda row: (-float(row["relevance_score"]), row["path"]))
    rows = rows[:LIMIT]
    return {
        "selector": "deterministic_baseline",
        "query_terms": sorted(query_terms),
        "targets": rows,
        "abstained": not rows,
    }


def _build_pack(
    root: Path,
    artifacts: dict[str, Any],
    goal: str,
    task_intent: dict[str, Any],
    selection_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return build_context_pack(
        root=str(root),
        targets=selection_rows,
        project_map=artifacts["project_map"],
        symbol_index=artifacts["symbol_index"],
        call_graph=artifacts["call_graph"],
        goal=goal,
        task_intent=task_intent,
        query_terms=[term for row in selection_rows for term in row.get("matched_terms", [])] or _tokenize(goal),
        minimum_query_coverage=0.2,
    )


def _selector_metrics(
    *,
    selected_paths: list[str],
    case: dict[str, Any],
    latency_ms: float,
    estimated_tokens: int,
) -> tuple[dict[str, Any], dict[str, str]]:
    relevant_set = set(case["relevant_paths"])
    expected_targets = case["expected_targets"]
    expected_tests = case["expected_tests"]
    selected_hits = sum(1 for path in selected_paths if path in relevant_set)
    target_hits = sum(1 for path in expected_targets if path in selected_paths)
    test_hits = sum(1 for path in expected_tests if path in selected_paths)
    precision = round(selected_hits / len(selected_paths), 6) if selected_paths else None
    target_recall = round(target_hits / len(expected_targets), 6) if expected_targets else None
    test_recall = round(test_hits / len(expected_tests), 6) if expected_tests else None
    metrics = {
        "selected_count": len(selected_paths),
        "precision_at_k": precision,
        "target_recall_at_k": target_recall,
        "test_recall_at_k": test_recall,
        "latency_ms": round(latency_ms, 3),
        "estimated_tokens": int(estimated_tokens),
    }
    statuses = {
        "selected_count": "MEASURED",
        "precision_at_k": "MEASURED" if precision is not None else "UNVERIFIED",
        "target_recall_at_k": "MEASURED" if target_recall is not None else "UNVERIFIED",
        "test_recall_at_k": "MEASURED" if test_recall is not None else "UNVERIFIED",
        "latency_ms": "MEASURED",
        "estimated_tokens": "ESTIMATED",
    }
    return metrics, statuses


def _measure_baseline(case: dict[str, Any], root: Path, artifacts: dict[str, Any], goal: str, task_intent: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    selection = _baseline_selection(root, artifacts["project_map"], goal)
    pack = _build_pack(root, artifacts, goal, task_intent, selection["targets"])
    latency_ms = (time.perf_counter() - started) * 1000
    selected_paths = [row["path"] for row in selection["targets"]]
    metrics, statuses = _selector_metrics(
        selected_paths=selected_paths,
        case=case,
        latency_ms=latency_ms,
        estimated_tokens=_estimate_tokens_from_bytes(len(_json_dump(pack).encode("utf-8"))),
    )
    return {
        "selector": "deterministic_baseline",
        "abstained": selection["abstained"],
        "selected_paths": selected_paths,
        "metrics": metrics,
        "measurement_status": statuses,
    }


def _measure_indexed(case: dict[str, Any], root: Path, artifacts: dict[str, Any], goal: str, task_intent: dict[str, Any]) -> dict[str, Any]:
    retrieval_index = load_retrieval_index(str(root), OUT_DIR)
    started = time.perf_counter()
    selection = select_context_targets(
        str(root),
        artifacts["project_map"],
        goal=goal,
        task_intent=task_intent,
        limit=LIMIT,
        symbol_index=artifacts["symbol_index"],
        call_graph=artifacts["call_graph"],
        token_budget=TOKEN_BUDGET,
        minimum_query_coverage=0.2,
        retrieval_index=retrieval_index,
    )
    latency_ms = (time.perf_counter() - started) * 1000
    selected_paths = [row["path"] for row in selection["targets"]]
    metrics, statuses = _selector_metrics(
        selected_paths=selected_paths,
        case=case,
        latency_ms=latency_ms,
        estimated_tokens=int(selection["token_budget_fit"]["estimated_tokens"]),
    )
    return {
        "selector": "indexed_selector",
        "abstained": bool(selection["abstained"]),
        "selected_paths": selected_paths,
        "metrics": metrics,
        "measurement_status": statuses,
    }


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    case_root = CORPUS_PATH.parent / case["id"]
    tempdir = _copy_case(case_root)
    try:
        map_code, _, map_stderr, _ = evaluation_scorecard._run_cli(["map", "--root", str(tempdir), "--silent"], ROOT)
        if map_code != 0:
            raise RuntimeError(f"map failed for {case['id']}: {map_stderr.strip()}")
        scan_code, _, scan_stderr, _ = evaluation_scorecard._run_cli(
            ["scan", str(tempdir), "--sync", "--json"],
            ROOT,
        )
        if scan_code != 0:
            raise RuntimeError(f"scan failed for {case['id']}: {scan_stderr.strip()}")
        artifacts = _filtered_artifacts(_load_mapper_artifacts(str(tempdir), OUT_DIR))
        goal, task_intent = _task_goal(case_root)
        baseline = _measure_baseline(case, tempdir, artifacts, goal, task_intent)
        indexed = _measure_indexed(case, tempdir, artifacts, goal, task_intent)
        return {
            "id": case["id"],
            "baseline": baseline,
            "indexed": indexed,
        }
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)


def _mean(values: list[float | int | None]) -> float | None:
    numeric = [float(value) for value in values if value is not None]
    return round(sum(numeric) / len(numeric), 6) if numeric else None


def _aggregate_selector(cases: list[dict[str, Any]], key: str) -> dict[str, Any]:
    rows = [case[key] for case in cases]
    return {
        "precision_at_k": _mean([row["metrics"]["precision_at_k"] for row in rows]),
        "target_recall_at_k": _mean([row["metrics"]["target_recall_at_k"] for row in rows]),
        "test_recall_at_k": _mean([row["metrics"]["test_recall_at_k"] for row in rows]),
        "estimated_tokens_mean": _mean([row["metrics"]["estimated_tokens"] for row in rows]),
        "latency_ms_mean": _mean([row["metrics"]["latency_ms"] for row in rows]),
        "latency_ms_max": max(float(row["metrics"]["latency_ms"]) for row in rows),
    }


def _hypotheses(cases: list[dict[str, Any]], aggregates: dict[str, Any]) -> list[dict[str, Any]]:
    baseline = aggregates["deterministic_baseline"]
    indexed = aggregates["indexed_selector"]
    h1_pass = (
        indexed["precision_at_k"] is not None
        and baseline["precision_at_k"] is not None
        and indexed["precision_at_k"] > baseline["precision_at_k"]
        and indexed["target_recall_at_k"] is not None
        and baseline["target_recall_at_k"] is not None
        and indexed["target_recall_at_k"] >= baseline["target_recall_at_k"]
    )
    h2_pass = (
        indexed["estimated_tokens_mean"] is not None
        and baseline["estimated_tokens_mean"] is not None
        and indexed["estimated_tokens_mean"] < baseline["estimated_tokens_mean"]
    )
    return [
        {
            "id": "H1",
            "claim": "Indexed selector improves precision while preserving or improving target recall versus the deterministic baseline on the advanced corpus.",
            "measurements": {
                "baseline_precision_at_k": baseline["precision_at_k"],
                "indexed_precision_at_k": indexed["precision_at_k"],
                "baseline_target_recall_at_k": baseline["target_recall_at_k"],
                "indexed_target_recall_at_k": indexed["target_recall_at_k"],
            },
            "measurement_status": {
                "baseline_precision_at_k": "MEASURED",
                "indexed_precision_at_k": "MEASURED",
                "baseline_target_recall_at_k": "MEASURED",
                "indexed_target_recall_at_k": "MEASURED",
            },
            "verdict": "pass" if h1_pass else "refuted",
        },
        {
            "id": "H2",
            "claim": "Indexed selector reduces estimated context tokens versus the deterministic baseline; latency is reported separately as a measured tradeoff.",
            "measurements": {
                "baseline_estimated_tokens_mean": baseline["estimated_tokens_mean"],
                "indexed_estimated_tokens_mean": indexed["estimated_tokens_mean"],
                "baseline_latency_ms_mean": baseline["latency_ms_mean"],
                "indexed_latency_ms_mean": indexed["latency_ms_mean"],
            },
            "measurement_status": {
                "baseline_estimated_tokens_mean": "ESTIMATED",
                "indexed_estimated_tokens_mean": "ESTIMATED",
                "baseline_latency_ms_mean": "MEASURED",
                "indexed_latency_ms_mean": "MEASURED",
            },
            "verdict": "pass" if h2_pass else "refuted",
        },
    ]


def build_report() -> dict[str, Any]:
    manifest = _load_json(CORPUS_PATH)
    cases = [_evaluate_case(case) for case in manifest["cases"]]
    aggregates = {
        "deterministic_baseline": _aggregate_selector(cases, "baseline"),
        "indexed_selector": _aggregate_selector(cases, "indexed"),
    }
    hypotheses = _hypotheses(cases, aggregates)
    return {
        "schema": SCHEMA,
        "corpus": {
            "path": str(CORPUS_PATH.relative_to(ROOT)).replace("\\", "/"),
            "case_count": len(cases),
        },
        "selectors": aggregates,
        "selector_measurement_status": {
            "precision_at_k": "MEASURED",
            "target_recall_at_k": "MEASURED",
            "test_recall_at_k": "MEASURED",
            "estimated_tokens_mean": "ESTIMATED",
            "latency_ms_mean": "MEASURED",
            "latency_ms_max": "MEASURED",
        },
        "hypotheses": hypotheses,
        "cases": cases,
        "status": "pass" if all(item["verdict"] == "pass" for item in hypotheses) else "fail",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Advanced H1/H2 selector benchmark report.")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    args = parser.parse_args()
    payload = build_report()
    if args.json or True:
        json.dump(payload, os.sys.stdout, indent=2, ensure_ascii=False, sort_keys=True)
        os.sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
