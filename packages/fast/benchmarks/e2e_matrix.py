"""Deterministic Python S0-S3 benchmark receipt with fail-closed gaps."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

try:
    from benchmarks.compare_fast import run as run_local_fixture
except ModuleNotFoundError:
    from compare_fast import run as run_local_fixture

SCHEMA = "simplicio.fast.s0-s3-benchmark/v1"
SCENARIOS = ("S0_BASELINE", "S1_RUNTIME", "S2_RUNTIME_LOOP", "S3_FULL_STACK")
_NULL_METRICS = (
    "wall_ms",
    "cpu_ms",
    "peak_rss_kib",
    "page_faults",
    "input_tokens",
    "output_tokens",
    "cache_tokens",
    "tool_tokens",
    "cost",
)


def _positive(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _source_commit(root: Path) -> tuple[str | None, str | None]:
    try:
        value = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None, "source_commit_unavailable"
    return value or None, None if value else "source_commit_unavailable"


def _corpus_digest(files: int, functions: int) -> str:
    digest = hashlib.sha256()
    for index in range(files):
        digest.update(f"service_{index}.py\n".encode())
        digest.update(f"class Service{index}:\n".encode())
        for function in range(functions):
            digest.update(f"    def task_{function}(self, value):\n".encode())
            digest.update(b"        return value\n")
    return digest.hexdigest()


def _wall_metrics(receipt: dict[str, Any]) -> dict[str, Any]:
    wall = receipt["wall_ms"]
    return {
        "wall_ms": {
            "samples": list(wall["samples"]),
            "p50": wall["median"],
            "p95": wall["p95"],
            "p99": wall["p99"],
        },
        "cpu_ms": None,
        "peak_rss_kib": None,
        "page_faults": None,
        "input_tokens": receipt["estimated_input_tokens"],
        "output_tokens": None,
        "cache_tokens": None,
        "tool_tokens": None,
        "cost": None,
    }


def _blocked(reason_code: str, reason: str) -> dict[str, Any]:
    metrics = {name: None for name in _NULL_METRICS}
    return {
        "status": "blocked",
        "observed": False,
        "valid_repetitions": 0,
        "metrics": metrics,
        "metric_reason_codes": {name: reason_code for name in _NULL_METRICS},
        "reason_code": reason_code,
        "reason": reason,
    }


def run_matrix(
    *,
    files: int = 50,
    functions: int = 20,
    repetitions: int = 10,
    repo_root: Path = Path("."),
) -> dict[str, Any]:
    _positive(files, "files")
    _positive(functions, "functions")
    _positive(repetitions, "repetitions")
    if repetitions < 10:
        raise ValueError("repetitions must be at least 10 for S0-S3 receipts")
    root = repo_root.resolve()
    local = run_local_fixture(files=files, functions=functions, repetitions=repetitions)
    commit, commit_reason = _source_commit(root)
    term = local["workload"]["term"]
    baseline = local["scenarios"]["without_fast_ast_reparse"]
    s0_metrics = _wall_metrics(baseline)
    s0 = {
        "status": "complete",
        "observed": True,
        "valid_repetitions": repetitions,
        "operation": "local_ast_reparse_without_fast",
        "metrics": s0_metrics,
        "metric_reason_codes": {
            "cpu_ms": "counter_not_collected",
            "peak_rss_kib": "counter_not_collected",
            "page_faults": "counter_not_collected",
            "output_tokens": "provider_not_present",
            "cache_tokens": "provider_not_present",
            "tool_tokens": "provider_not_present",
            "cost": "provider_not_present",
        },
        "token_measurement": "whitespace-v1-estimate",
        "tokens_observed": False,
        "raw": {"wall_ms": baseline["wall_ms"], "source_schema": local["schema"]},
    }
    scenarios = {
        "S0_BASELINE": s0,
        "S1_RUNTIME": _blocked(
            "runtime_capability_unavailable",
            "simplicio-runtime capability handshake was not provided to this local run",
        ),
        "S2_RUNTIME_LOOP": _blocked(
            "runtime_loop_integration_unavailable",
            "Runtime + Loop delivery integration was not provided to this local run",
        ),
        "S3_FULL_STACK": _blocked(
            "full_stack_integration_unavailable",
            "Runtime + Loop + Mapper + Dev CLI integration was not provided to this local run",
        ),
    }
    return {
        "schema": SCHEMA,
        "status": "partial",
        "protocol": {
            "version": "python-s0-s3-v1",
            "warmup_repetitions": 0,
            "order": [*SCENARIOS],
        },
        "source_commit": commit,
        "source_commit_reason": commit_reason,
        "corpus": {
            "files": files,
            "functions_per_file": functions,
            "term": term,
            "sha256": _corpus_digest(files, functions),
        },
        "environment": local["environment"],
        "scenarios": scenarios,
        "limitations": [
            "S0 is a deterministic local Python fixture, not an LLM/provider delivery run.",
            "Unavailable metrics are null with reason codes.",
            "S1-S3 remain blocked until their cross-repository capability handshakes are supplied.",
            "Token values are whitespace-v1 estimates, not provider billing telemetry.",
        ],
    }


def markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# Python S0-S3 benchmark",
        "",
        f"- Status: {result['status']}",
        f"- Source commit: {result['source_commit'] or 'unavailable'}",
        f"- Corpus SHA-256: {result['corpus']['sha256']}",
        "",
        "| Scenario | Status | Valid repetitions | Reason |",
        "|---|---:|---:|---|",
    ]
    for name in SCENARIOS:
        scenario = result["scenarios"][name]
        lines.append(
            f"| {name} | {scenario['status']} | {scenario['valid_repetitions']} | {scenario.get('reason_code', 'observed')} |"
        )
    lines.extend(
        [
            "",
            "Unavailable metrics are null with explicit reason codes. S0 token values use whitespace-v1 estimates; they are not provider billing telemetry.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=50)
    parser.add_argument("--functions", type=int, default=20)
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args()
    result = run_matrix(
        files=args.files,
        functions=args.functions,
        repetitions=args.repetitions,
        repo_root=args.repo_root,
    )
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.write_text(payload, encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.write_text(markdown_report(result), encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
