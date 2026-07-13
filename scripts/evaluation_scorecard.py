#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
import time
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from simplicio_mapper.cli import main as mapper_cli_main

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "tests" / "fixtures" / "evaluation_corpus" / "manifest.json"
DOC_PATH = ROOT / "docs" / "behavioral-scorecard.md"
SCHEMA = "simplicio.behavioral-scorecard/v1"


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _estimate_tokens_from_bytes(byte_count: int) -> int:
    return max(1, math.ceil(byte_count / 4))


def _measure_tree_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def _artifact_bytes(root: Path) -> int:
    artifact_root = root / ".simplicio"
    return _measure_tree_bytes(artifact_root) if artifact_root.exists() else 0


def _run_cli(args: list[str], cwd: Path) -> tuple[int, str, str, float]:
    started = time.perf_counter()
    stdout_buffer = StringIO()
    stderr_buffer = StringIO()
    previous_cwd = Path.cwd()
    try:
        os.chdir(cwd)
        with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
            try:
                code = mapper_cli_main(args)
            except SystemExit as exc:
                code = int(exc.code) if isinstance(exc.code, int) else 1
    finally:
        os.chdir(previous_cwd)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return code, stdout_buffer.getvalue(), stderr_buffer.getvalue(), round(elapsed_ms, 3)


@dataclass
class CaseRun:
    handoff: dict[str, Any]
    orient: dict[str, Any]
    handoff_latency_ms: float
    orient_latency_ms: float
    handoff_stdout_bytes: int
    source_bytes: int
    artifact_bytes: int
    context_pack_bytes: int
    selected_paths: list[str]
    selected_hits: int
    precision_at_k: float | None
    target_recall_at_k: float | None
    test_recall_at_k: float | None
    required_span_recall: float | None
    sufficiency: float
    task_success: float
    nonexistent_paths: int
    first_fingerprint: str
    second_fingerprint: str
    deterministic: bool


def _copy_case(case_root: Path) -> Path:
    tempdir = Path(tempfile.mkdtemp(prefix=f"mapper-eval-{case_root.name}-"))
    shutil.copytree(case_root / "source", tempdir, dirs_exist_ok=True)
    shutil.copy2(case_root / "task.md", tempdir / "task.md")
    shutil.copy2(case_root / "task.json", tempdir / "task.json")
    return tempdir


def _load_json(text: str, label: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} did not emit valid JSON: {exc}") from exc


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    case_root = CORPUS_PATH.parent / case["id"]
    tempdir = _copy_case(case_root)
    try:
        source_bytes = _measure_tree_bytes(tempdir)
        code, stdout, stderr, _ = _run_cli(["map", "--root", str(tempdir), "--silent"], ROOT)
        if code != 0:
            raise RuntimeError(f"map failed for {case['id']}: {stderr.strip()}")
        code, stdout, stderr, _ = _run_cli(["scan", str(tempdir), "--sync", "--json"], ROOT)
        if code != 0:
            raise RuntimeError(f"scan failed for {case['id']}: {stderr.strip()}")

        first_code, first_stdout, first_stderr, handoff_latency_ms = _run_cli(
            ["handoff", str(tempdir), "--task-file", str(tempdir / case["task_file"]), "--json", "--await"],
            ROOT,
        )
        if first_code != 0:
            raise RuntimeError(f"handoff failed for {case['id']}: {first_stderr.strip()}")

        second_code, second_stdout, second_stderr, _ = _run_cli(
            ["handoff", str(tempdir), "--task-file", str(tempdir / case["task_file"]), "--json", "--await"],
            ROOT,
        )
        if second_code != 0:
            raise RuntimeError(f"handoff(second pass) failed for {case['id']}: {second_stderr.strip()}")

        orient_code, orient_stdout, orient_stderr, orient_latency_ms = _run_cli(
            ["orient", str(tempdir), "--task-json", str(tempdir / case["task_json"]), "--json"],
            ROOT,
        )
        if orient_code != 0:
            raise RuntimeError(f"orient failed for {case['id']}: {orient_stderr.strip()}")

        first_handoff = _load_json(first_stdout, f"{case['id']} handoff")
        second_handoff = _load_json(second_stdout, f"{case['id']} handoff(second pass)")
        orient = _load_json(orient_stdout, f"{case['id']} orient")

        selected_paths = list(first_handoff.get("targets", []))
        selected_set = set(selected_paths)
        orient_candidate_paths = [candidate.get("path", "") for candidate in orient.get("candidates", []) if candidate.get("path")]
        covered_paths = set(selected_paths) | set(orient_candidate_paths)
        relevant_set = set(case["relevant_paths"])
        selected_hits = sum(1 for path in selected_paths if path in relevant_set)
        precision_at_k = (
            round(selected_hits / len(selected_paths), 6) if selected_paths else None
        )

        expected_targets = case["expected_targets"]
        expected_tests = case["expected_tests"]
        target_hits = sum(1 for path in expected_targets if path in covered_paths)
        test_hits = sum(1 for path in expected_tests if path in covered_paths)
        target_recall = (
            round(target_hits / len(expected_targets), 6) if expected_targets else None
        )
        test_recall = round(test_hits / len(expected_tests), 6) if expected_tests else None

        candidates = orient.get("candidates", [])
        span_hits = 0
        for span in case["required_spans"]:
            matched = False
            for candidate in candidates:
                if candidate.get("path") != span["path"]:
                    continue
                line = candidate.get("line")
                if isinstance(line, int) and span["start_line"] <= line <= span["end_line"]:
                    matched = True
                    break
            if matched:
                span_hits += 1
        required_span_recall = (
            round(span_hits / len(case["required_spans"]), 6) if case["required_spans"] else None
        )

        nonexistent_paths = sum(1 for path in selected_paths if not (tempdir / path).exists())

        abstained = bool(first_handoff.get("selection", {}).get("abstained"))
        needs_broader_context = bool(first_handoff.get("context_pack", {}).get("needs_broader_context"))

        if case["expect_abstain"]:
            sufficiency = 1.0 if abstained and not selected_paths else 0.0
            task_success = sufficiency
        else:
            sufficiency = 1.0 if (
                first_handoff.get("ready")
                and target_recall == 1.0
                and test_recall == 1.0
                and required_span_recall == 1.0
                and nonexistent_paths == 0
                and not needs_broader_context
            ) else 0.0
            task_success = sufficiency

        context_pack_bytes = len(
            _json_dump(first_handoff.get("context_pack", {})).encode("utf-8")
        )
        artifact_bytes = _artifact_bytes(tempdir)
        first_fingerprint = first_handoff.get("context_pack", {}).get("pack_hash", "")
        second_fingerprint = second_handoff.get("context_pack", {}).get("pack_hash", "")
        deterministic = (
            first_fingerprint == second_fingerprint
            and first_handoff.get("targets") == second_handoff.get("targets")
        )

        metrics = {
            "latency_ms": handoff_latency_ms,
            "orient_latency_ms": orient_latency_ms,
            "source_input_bytes": source_bytes,
            "artifact_output_bytes": artifact_bytes,
            "context_pack_bytes": context_pack_bytes,
            "handoff_payload_bytes": len(first_stdout.encode("utf-8")),
            "estimated_tokens": _estimate_tokens_from_bytes(context_pack_bytes),
            "precision_at_k": precision_at_k,
            "target_recall_at_k": target_recall,
            "test_recall_at_k": test_recall,
            "required_span_recall": required_span_recall,
            "sufficiency": sufficiency,
            "task_success": task_success,
            "nonexistent_paths": nonexistent_paths,
        }
        metric_status = {
            "latency_ms": "MEASURED",
            "orient_latency_ms": "MEASURED",
            "source_input_bytes": "MEASURED",
            "artifact_output_bytes": "MEASURED",
            "context_pack_bytes": "MEASURED",
            "handoff_payload_bytes": "MEASURED",
            "estimated_tokens": "ESTIMATED",
            "precision_at_k": "MEASURED" if precision_at_k is not None else "UNVERIFIED",
            "target_recall_at_k": "MEASURED" if target_recall is not None else "UNVERIFIED",
            "test_recall_at_k": "MEASURED" if test_recall is not None else "UNVERIFIED",
            "required_span_recall": "MEASURED" if required_span_recall is not None else "UNVERIFIED",
            "sufficiency": "MEASURED",
            "task_success": "MEASURED",
            "nonexistent_paths": "MEASURED",
        }
        return {
            "id": case["id"],
            "status": "pass" if task_success == 1.0 else "fail",
            "first_fingerprint": first_fingerprint,
            "second_fingerprint": second_fingerprint,
            "deterministic": deterministic,
            "selected_paths": selected_paths,
            "covered_paths": sorted(covered_paths),
            "metrics": metrics,
            "metric_status": metric_status,
            "ready": bool(first_handoff.get("ready")),
            "abstained": abstained,
            "reason": first_handoff.get("reason", ""),
            "selection": first_handoff.get("selection", {}),
            "orient": {"candidate_count": len(candidates), "needs_broader_context": orient.get("needs_broader_context")},
        }
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)


def _aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    positive_cases = [case for case in cases if case["metrics"]["target_recall_at_k"] is not None]
    target_recalls = [case["metrics"]["target_recall_at_k"] for case in positive_cases]
    test_recalls = [case["metrics"]["test_recall_at_k"] for case in positive_cases if case["metrics"]["test_recall_at_k"] is not None]
    span_recalls = [case["metrics"]["required_span_recall"] for case in positive_cases if case["metrics"]["required_span_recall"] is not None]
    precisions = [case["metrics"]["precision_at_k"] for case in cases if case["metrics"]["precision_at_k"] is not None]
    latencies = [case["metrics"]["latency_ms"] for case in cases]
    source_bytes = [case["metrics"]["source_input_bytes"] for case in cases]
    artifact_bytes = [case["metrics"]["artifact_output_bytes"] for case in cases]
    context_bytes = [case["metrics"]["context_pack_bytes"] for case in cases]
    estimated_tokens = [case["metrics"]["estimated_tokens"] for case in cases]
    sufficiency = [case["metrics"]["sufficiency"] for case in cases]
    task_success = [case["metrics"]["task_success"] for case in cases]
    determinism = [1.0 if case["deterministic"] else 0.0 for case in cases]
    abstention_cases = [case for case in cases if case["abstained"] or case["reason"] == "task_context_insufficient"]
    abstention_accuracy = [case["metrics"]["task_success"] for case in abstention_cases] if abstention_cases else []

    measurements = {
        "target_recall_at_k": round(sum(target_recalls) / len(target_recalls), 6) if target_recalls else None,
        "test_recall_at_k": round(sum(test_recalls) / len(test_recalls), 6) if test_recalls else None,
        "required_span_recall": round(sum(span_recalls) / len(span_recalls), 6) if span_recalls else None,
        "mean_precision_at_k": round(sum(precisions) / len(precisions), 6) if precisions else None,
        "sufficiency": round(sum(sufficiency) / len(sufficiency), 6) if sufficiency else None,
        "task_success": round(sum(task_success) / len(task_success), 6) if task_success else None,
        "determinism": round(sum(determinism) / len(determinism), 6) if determinism else None,
        "abstention_accuracy": round(sum(abstention_accuracy) / len(abstention_accuracy), 6) if abstention_accuracy else None,
        "mean_latency_ms": round(sum(latencies) / len(latencies), 3) if latencies else None,
        "max_latency_ms": round(max(latencies), 3) if latencies else None,
        "mean_source_input_bytes": round(sum(source_bytes) / len(source_bytes), 3) if source_bytes else None,
        "mean_artifact_output_bytes": round(sum(artifact_bytes) / len(artifact_bytes), 3) if artifact_bytes else None,
        "mean_context_pack_bytes": round(sum(context_bytes) / len(context_bytes), 3) if context_bytes else None,
        "estimated_tokens_mean": round(sum(estimated_tokens) / len(estimated_tokens), 3) if estimated_tokens else None,
    }
    measurement_status = {
        "target_recall_at_k": "MEASURED",
        "test_recall_at_k": "MEASURED",
        "required_span_recall": "MEASURED",
        "mean_precision_at_k": "MEASURED",
        "sufficiency": "MEASURED",
        "task_success": "MEASURED",
        "determinism": "MEASURED",
        "abstention_accuracy": "MEASURED",
        "mean_latency_ms": "MEASURED",
        "max_latency_ms": "MEASURED",
        "mean_source_input_bytes": "MEASURED",
        "mean_artifact_output_bytes": "MEASURED",
        "mean_context_pack_bytes": "MEASURED",
        "estimated_tokens_mean": "ESTIMATED",
    }
    return {"measurements": measurements, "measurement_status": measurement_status}


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Behavioral scorecard",
        "",
        "Reproducible benchmark for issues #199 and #208 using a reviewer-labeled corpus under `tests/fixtures/evaluation_corpus`.",
        "",
        "Replay commands:",
        "",
        "```bash",
        "python scripts/evaluation_scorecard.py --json",
        "python scripts/evaluation_scorecard.py --write",
        "python -m pytest tests/python/test_evaluation_benchmark.py tests/python/test_evaluation_corpus.py",
        "```",
        "",
        "## Aggregate measurements",
        "",
        "| Metric | Value | Status |",
        "|---|---:|---|",
    ]
    for key, value in payload["measurements"].items():
        rendered = "n/a" if value is None else value
        lines.append(f"| {key} | {rendered} | {payload['measurement_status'][key]} |")
    lines.extend([
        "",
        "## Per-case measurements",
        "",
        "| Case | latency_ms | context_pack_bytes | estimated_tokens | precision@k | required-span recall | sufficiency | task-success | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ])
    for case in payload["cases"]:
        metrics = case["metrics"]
        lines.append(
            f"| {case['id']} | {metrics['latency_ms']} | {metrics['context_pack_bytes']} | "
            f"{metrics['estimated_tokens']} | {metrics['precision_at_k'] if metrics['precision_at_k'] is not None else 'n/a'} | "
            f"{metrics['required_span_recall'] if metrics['required_span_recall'] is not None else 'n/a'} | "
            f"{metrics['sufficiency']} | {metrics['task_success']} | {case['status']} |"
        )
    lines.extend([
        "",
        "Notes:",
        "",
        "- `estimated_tokens` uses `utf8-bytes-div-4`, so it is labeled `ESTIMATED` rather than `MEASURED`.",
        "- `required_span_recall` is line-aware and comes from `orient` candidate evidence against reviewer-owned spans.",
        "- `target_recall_at_k` and `test_recall_at_k` use the combined retrieval surface from `handoff` targets plus `orient` candidates.",
        "- `task_success` is the benchmark verdict for each labeled case; it is not a claim about end-to-end downstream code generation outside this harness.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Behavioral scorecard for issues #199 and #208.")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    parser.add_argument("--write", action="store_true", help="Write docs/behavioral-scorecard.md.")
    args = parser.parse_args()

    corpus = _load_json(CORPUS_PATH.read_text(encoding="utf-8"), "corpus manifest")
    cases = [_evaluate_case(case) for case in corpus["cases"]]
    aggregate = _aggregate(cases)
    payload = {
        "schema": SCHEMA,
        "status": "pass" if all(case["status"] == "pass" for case in cases) else "fail",
        "corpus": {
            "path": str(CORPUS_PATH.relative_to(ROOT)).replace("\\", "/"),
            "case_count": len(cases),
        },
        "measurements": aggregate["measurements"],
        "measurement_status": aggregate["measurement_status"],
        "cases": cases,
    }

    if args.write:
        DOC_PATH.write_text(_render_markdown(payload) + "\n", encoding="utf-8")

    if args.json or not args.write:
        json.dump(payload, sys.stdout, indent=2, ensure_ascii=False, sort_keys=True)
        sys.stdout.write("\n")

    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
