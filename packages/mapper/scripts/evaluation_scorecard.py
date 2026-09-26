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

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "tests" / "fixtures" / "evaluation_corpus" / "manifest.json"
DOC_PATH = ROOT / "docs" / "behavioral-scorecard.md"
JSON_DOC_PATH = ROOT / "docs" / "evidence" / "behavioral-scorecard.json"
SCHEMA = "simplicio.behavioral-scorecard/v1"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simplicio_mapper.cli import main as mapper_cli_main  # noqa: E402
from simplicio_mapper.savings import warm_estimator  # noqa: E402


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _estimate_tokens_from_bytes(byte_count: int) -> int:
    return max(1, math.ceil(byte_count / 4))


def _infer_language(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".md": "markdown",
        ".json": "json",
    }.get(suffix, "other")


def _infer_layers(path: str) -> set[str]:
    normalized = path.replace("\\", "/").lower()
    parts = set(piece for piece in normalized.split("/") if piece)
    layers: set[str] = set()
    if "tests" in parts or Path(normalized).name.startswith(("test_",)) or ".test." in normalized:
        layers.add("test")
    if {"frontend", "components", "ui", "web"} & parts:
        layers.add("frontend")
    if {"api", "backend", "server"} & parts:
        layers.add("backend")
    if {"state", "store"} & parts:
        layers.add("state")
    if not layers and normalized.startswith("src/"):
        layers.add("implementation")
    return layers


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
        # `scan --sync` only maps its own process exit code to a "timeout"
        # vs. everything-else distinction: a deep-index worker that failed
        # (crash, resource contention, a leftover lock) or left a stale
        # index still exits 0 with `phase: "failed"` in its JSON envelope —
        # see `_run_scan` / `test_scan_sync_lock_guarded`, where this is the
        # documented, intentional CLI contract: callers that need to know
        # the scan actually completed must read `phase`, not just the exit
        # code. Without that check a failed scan silently fell through to
        # `handoff` against a stale/absent project map, producing a
        # spuriously low recall instead of a clear, retryable error. A
        # worker failure under contention (lock held a beat too long,
        # transient spawn hiccup) is inherently transient, so retry the scan
        # itself a bounded number of times before treating it as real.
        scan_envelope: dict[str, Any] = {}
        scan_attempts = 3
        for attempt in range(scan_attempts):
            code, stdout, stderr, _ = _run_cli(["scan", str(tempdir), "--sync", "--json"], ROOT)
            if code != 0:
                raise RuntimeError(f"scan failed for {case['id']}: {stderr.strip()}")
            scan_envelope = _load_json(stdout, f"{case['id']} scan")
            if scan_envelope.get("phase") == "complete":
                break
            if attempt == scan_attempts - 1:
                raise RuntimeError(
                    f"scan for {case['id']} did not complete after {scan_attempts} attempts: "
                    f"phase={scan_envelope.get('phase')!r} "
                    f"failure_reason={scan_envelope.get('deep', {}).get('failure_reason')!r}"
                )
            time.sleep(0.2)

        first_code, first_stdout, first_stderr, handoff_latency_ms = _run_cli(
            [
                "handoff",
                str(tempdir),
                "--task-file",
                str(tempdir / case["task_file"]),
                "--json",
                "--await",
                "--token-budget",
                str(case.get("token_budget", 8000)),
            ],
            ROOT,
        )
        if first_code != 0:
            raise RuntimeError(f"handoff failed for {case['id']}: {first_stderr.strip()}")

        second_code, second_stdout, second_stderr, _ = _run_cli(
            [
                "handoff",
                str(tempdir),
                "--task-file",
                str(tempdir / case["task_file"]),
                "--json",
                "--await",
                "--token-budget",
                str(case.get("token_budget", 8000)),
            ],
            ROOT,
        )
        if second_code != 0:
            raise RuntimeError(f"handoff(second pass) failed for {case['id']}: {second_stderr.strip()}")

        orient_code, orient_stdout, orient_stderr, orient_latency_ms = _run_cli(
            [
                "orient",
                str(tempdir),
                "--task-json",
                str(tempdir / case["task_json"]),
                "--json",
                "--token-budget",
                str(case.get("token_budget", 8000)),
            ],
            ROOT,
        )
        if orient_code != 0:
            raise RuntimeError(f"orient failed for {case['id']}: {orient_stderr.strip()}")

        first_handoff = _load_json(first_stdout, f"{case['id']} handoff")
        second_handoff = _load_json(second_stdout, f"{case['id']} handoff(second pass)")
        orient = _load_json(orient_stdout, f"{case['id']} orient")

        selected_paths = list(first_handoff.get("targets", []))
        orient_candidate_paths = [
            candidate.get("path", "") for candidate in orient.get("candidates", []) if candidate.get("path")
        ]
        covered_paths = set(selected_paths) | set(orient_candidate_paths)
        covered_languages = {_infer_language(path) for path in covered_paths if path}
        covered_layers = set().union(*(_infer_layers(path) for path in covered_paths if path)) if covered_paths else set()
        relevant_set = set(case["relevant_paths"])
        selected_hits = sum(1 for path in selected_paths if path in relevant_set)
        precision_at_k = round(selected_hits / len(selected_paths), 6) if selected_paths else None

        expected_targets = case["expected_targets"]
        expected_tests = case["expected_tests"]
        target_hits = sum(1 for path in expected_targets if path in covered_paths)
        test_hits = sum(1 for path in expected_tests if path in covered_paths)
        target_recall = round(target_hits / len(expected_targets), 6) if expected_targets else None
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

        # `handoff`'s slimmed envelope ("slim handoff envelope", Refs
        # wesleysimplicio/simplicio-loop#1284) only wraps `selection`/
        # `context_pack` into a `simplicio.context-reference/v1` envelope
        # (full content moved one level deeper, under the wrapper's own
        # `summary`) when the field had to be referenced-out to fit the
        # handoff envelope's token budget; a field that stayed inline keeps
        # its original shape with no `summary` nesting. Normalize both.
        raw_selection = first_handoff.get("selection", {})
        selection_view = raw_selection.get("summary", raw_selection) if isinstance(raw_selection, dict) else {}
        raw_context_pack = first_handoff.get("context_pack", {})
        context_pack_view = (
            raw_context_pack.get("summary", raw_context_pack) if isinstance(raw_context_pack, dict) else {}
        )
        abstained = bool(selection_view.get("abstained") or selection_view.get("fidelity", {}).get("abstained"))
        needs_broader_context = bool(context_pack_view.get("needs_broader_context"))
        token_budget_fit = dict(selection_view.get("token_budget_fit", {}))
        serialization_budget = dict(context_pack_view.get("serialization_budget", {}))
        declared_budget = int(case.get("token_budget", token_budget_fit.get("token_budget", 8000)))
        budget_within_limit = bool(serialization_budget.get("within_budget"))
        required_languages = {str(item).lower() for item in case.get("required_languages", [])}
        required_layers = {str(item).lower() for item in case.get("required_layers", [])}
        required_language_recall = (
            round(sum(1 for item in required_languages if item in covered_languages) / len(required_languages), 6)
            if required_languages
            else None
        )
        required_layer_recall = (
            round(sum(1 for item in required_layers if item in covered_layers) / len(required_layers), 6)
            if required_layers
            else None
        )

        if case["expect_abstain"]:
            sufficiency = 1.0 if abstained and not selected_paths else 0.0
            task_success = sufficiency
        else:
            sufficiency = (
                1.0
                if (
                    first_handoff.get("ready")
                    and target_recall == 1.0
                    and test_recall == 1.0
                    and required_span_recall == 1.0
                    and (required_language_recall is None or required_language_recall == 1.0)
                    and (required_layer_recall is None or required_layer_recall == 1.0)
                    and budget_within_limit
                    and nonexistent_paths == 0
                    and not needs_broader_context
                )
                else 0.0
            )
            task_success = sufficiency

        context_pack_bytes = int(
            raw_context_pack.get("serialized_bytes")
            or len(_json_dump(raw_context_pack).encode("utf-8"))
        )
        artifact_bytes = _artifact_bytes(tempdir)
        first_fingerprint = context_pack_view.get("pack_hash", "")
        second_raw_context_pack = second_handoff.get("context_pack", {})
        second_context_pack_view = (
            second_raw_context_pack.get("summary", second_raw_context_pack)
            if isinstance(second_raw_context_pack, dict)
            else {}
        )
        second_fingerprint = second_context_pack_view.get("pack_hash", "")
        deterministic = first_fingerprint == second_fingerprint and first_handoff.get(
            "targets"
        ) == second_handoff.get("targets")

        metrics = {
            "latency_ms": handoff_latency_ms,
            "orient_latency_ms": orient_latency_ms,
            "source_input_bytes": source_bytes,
            "artifact_output_bytes": artifact_bytes,
            "context_pack_bytes": context_pack_bytes,
            "handoff_payload_bytes": len(first_stdout.encode("utf-8")),
            "estimated_tokens": _estimate_tokens_from_bytes(context_pack_bytes),
            "budget_token_limit": declared_budget,
            "budget_estimated_tokens": int(token_budget_fit.get("estimated_tokens", 0)),
            "budget_serialized_bytes": int(serialization_budget.get("serialized_bytes", 0)),
            "budget_within_limit": budget_within_limit,
            "precision_at_k": precision_at_k,
            "target_recall_at_k": target_recall,
            "test_recall_at_k": test_recall,
            "required_span_recall": required_span_recall,
            "required_language_recall": required_language_recall,
            "required_layer_recall": required_layer_recall,
            "selected_language_count": len(covered_languages),
            "selected_layer_count": len(covered_layers),
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
            "budget_token_limit": "MEASURED",
            "budget_estimated_tokens": "ESTIMATED",
            "budget_serialized_bytes": "MEASURED",
            "budget_within_limit": "ESTIMATED",
            "precision_at_k": "MEASURED" if precision_at_k is not None else "UNVERIFIED",
            "target_recall_at_k": "MEASURED" if target_recall is not None else "UNVERIFIED",
            "test_recall_at_k": "MEASURED" if test_recall is not None else "UNVERIFIED",
            "required_span_recall": "MEASURED" if required_span_recall is not None else "UNVERIFIED",
            "required_language_recall": "MEASURED" if required_language_recall is not None else "UNVERIFIED",
            "required_layer_recall": "MEASURED" if required_layer_recall is not None else "UNVERIFIED",
            "selected_language_count": "MEASURED",
            "selected_layer_count": "MEASURED",
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
            "orient": {
                "candidate_count": len(candidates),
                "needs_broader_context": orient.get("needs_broader_context"),
            },
        }
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)


def _aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    positive_cases = [case for case in cases if case["metrics"]["target_recall_at_k"] is not None]
    target_recalls = [case["metrics"]["target_recall_at_k"] for case in positive_cases]
    test_recalls = [
        case["metrics"]["test_recall_at_k"]
        for case in positive_cases
        if case["metrics"]["test_recall_at_k"] is not None
    ]
    span_recalls = [
        case["metrics"]["required_span_recall"]
        for case in positive_cases
        if case["metrics"]["required_span_recall"] is not None
    ]
    language_recalls = [
        case["metrics"]["required_language_recall"]
        for case in cases
        if case["metrics"]["required_language_recall"] is not None
    ]
    layer_recalls = [
        case["metrics"]["required_layer_recall"]
        for case in cases
        if case["metrics"]["required_layer_recall"] is not None
    ]
    budget_fit = [
        1.0 if case["metrics"]["budget_within_limit"] else 0.0
        for case in cases
        if case["metrics"]["budget_token_limit"] > 0
    ]
    precisions = [
        case["metrics"]["precision_at_k"] for case in cases if case["metrics"]["precision_at_k"] is not None
    ]
    latencies = [case["metrics"]["latency_ms"] for case in cases]
    source_bytes = [case["metrics"]["source_input_bytes"] for case in cases]
    artifact_bytes = [case["metrics"]["artifact_output_bytes"] for case in cases]
    context_bytes = [case["metrics"]["context_pack_bytes"] for case in cases]
    estimated_tokens = [case["metrics"]["estimated_tokens"] for case in cases]
    sufficiency = [case["metrics"]["sufficiency"] for case in cases]
    task_success = [case["metrics"]["task_success"] for case in cases]
    determinism = [1.0 if case["deterministic"] else 0.0 for case in cases]
    abstention_cases = [
        case for case in cases if case["abstained"] or case["reason"] == "task_context_insufficient"
    ]
    abstention_accuracy = (
        [case["metrics"]["task_success"] for case in abstention_cases] if abstention_cases else []
    )

    measurements = {
        "target_recall_at_k": round(sum(target_recalls) / len(target_recalls), 6) if target_recalls else None,
        "test_recall_at_k": round(sum(test_recalls) / len(test_recalls), 6) if test_recalls else None,
        "required_span_recall": round(sum(span_recalls) / len(span_recalls), 6) if span_recalls else None,
        "required_language_recall": round(sum(language_recalls) / len(language_recalls), 6) if language_recalls else None,
        "required_layer_recall": round(sum(layer_recalls) / len(layer_recalls), 6) if layer_recalls else None,
        "budget_fit_rate": round(sum(budget_fit) / len(budget_fit), 6) if budget_fit else None,
        "mean_precision_at_k": round(sum(precisions) / len(precisions), 6) if precisions else None,
        "sufficiency": round(sum(sufficiency) / len(sufficiency), 6) if sufficiency else None,
        "task_success": round(sum(task_success) / len(task_success), 6) if task_success else None,
        "determinism": round(sum(determinism) / len(determinism), 6) if determinism else None,
        "abstention_accuracy": round(sum(abstention_accuracy) / len(abstention_accuracy), 6)
        if abstention_accuracy
        else None,
        "mean_latency_ms": round(sum(latencies) / len(latencies), 3) if latencies else None,
        "max_latency_ms": round(max(latencies), 3) if latencies else None,
        "mean_source_input_bytes": round(sum(source_bytes) / len(source_bytes), 3) if source_bytes else None,
        "mean_artifact_output_bytes": round(sum(artifact_bytes) / len(artifact_bytes), 3)
        if artifact_bytes
        else None,
        "mean_context_pack_bytes": round(sum(context_bytes) / len(context_bytes), 3)
        if context_bytes
        else None,
        "estimated_tokens_mean": round(sum(estimated_tokens) / len(estimated_tokens), 3)
        if estimated_tokens
        else None,
    }
    measurement_status = {
        "target_recall_at_k": "MEASURED",
        "test_recall_at_k": "MEASURED",
        "required_span_recall": "MEASURED",
        "required_language_recall": "MEASURED" if language_recalls else "UNVERIFIED",
        "required_layer_recall": "MEASURED" if layer_recalls else "UNVERIFIED",
        "budget_fit_rate": "ESTIMATED" if budget_fit else "UNVERIFIED",
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
    lines.extend(
        [
            "",
            "## Per-case measurements",
            "",
            "| Case | latency_ms | context_pack_bytes | estimated_tokens | precision@k | required-span recall | sufficiency | task-success | Status |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for case in payload["cases"]:
        metrics = case["metrics"]
        lines.append(
            f"| {case['id']} | {metrics['latency_ms']} | {metrics['context_pack_bytes']} | "
            f"{metrics['estimated_tokens']} | {metrics['precision_at_k'] if metrics['precision_at_k'] is not None else 'n/a'} | "
            f"{metrics['required_span_recall'] if metrics['required_span_recall'] is not None else 'n/a'} | "
            f"{metrics['sufficiency']} | {metrics['task_success']} | {case['status']} |"
        )
    lines.extend(
        [
            "",
            "Notes:",
            "",
            "- `estimated_tokens` uses `utf8-bytes-div-4`, so it is labeled `ESTIMATED` rather than `MEASURED`.",
            "- `budget_within_limit` and `budget_fit_rate` depend on that declared tokenizer policy, so they are also labeled `ESTIMATED` even though the serialized bytes themselves are `MEASURED`.",
            "- `required_span_recall` is line-aware and comes from `orient` candidate evidence against reviewer-owned spans.",
            "- `required_language_recall` / `required_layer_recall` prove the selected retrieval surface kept the requested polyglot/cross-layer diversity for labeled cases.",
            "- `target_recall_at_k` and `test_recall_at_k` use the combined retrieval surface from `handoff` targets plus `orient` candidates.",
            "- `task_success` is the benchmark verdict for each labeled case; it is not a claim about end-to-end downstream code generation outside this harness.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Behavioral scorecard for issues #199 and #208.")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    parser.add_argument("--write", action="store_true", help="Write docs/behavioral-scorecard.md.")
    parser.add_argument("--write-json", action="store_true", help="Write docs/evidence/behavioral-scorecard.json.")
    args = parser.parse_args()

    # Every case's `handoff`/`orient` pass (in this process) and its `map`/
    # `scan` deep-index subprocess (see `_evaluate_case`) call
    # `estimate_tokens` for budget/cost accounting. On a cold machine that
    # function's tiktoken backend lazily fetches its ranks file over the
    # network the first time any process needs it; leaving that fetch to
    # happen wherever it is first needed means every case, and every
    # subprocess this script spawns, independently races to populate the
    # same on-disk cache -- and a transient failure in any one of those
    # races silently swaps in a materially different (coarser) token count
    # for just that case, breaking the "deterministic and measured"
    # contract this scorecard exists to prove (see issue backing
    # `warm_estimator`'s docstring). Warm it once, eagerly, right here,
    # before any case starts: every later caller in this process and every
    # subsequent subprocess sharing the default cache directory then hits
    # disk, not network.
    warm_estimator()

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
    if args.write_json:
        JSON_DOC_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    if args.json or (not args.write and not args.write_json):
        json.dump(payload, sys.stdout, indent=2, ensure_ascii=False, sort_keys=True)
        sys.stdout.write("\n")

    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
