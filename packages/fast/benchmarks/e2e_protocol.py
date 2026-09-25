"""Auditable S0-S3 benchmark protocol.

This module validates and preregisters runs; it does not manufacture measurements.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.fast.e2e-benchmark/v1"
SCENARIOS = ("S0_BASELINE", "S1_RUNTIME", "S2_RUNTIME_LOOP", "S3_FULL_STACK")
WORKLOADS = (
    "crud",
    "bugfix_failing_test",
    "cross_cutting_refactor",
    "warm_single_file_change",
    "retry_after_test_failure",
)
ENGINES = {
    "S0_BASELINE": ("off",),
    "S1_RUNTIME": ("off",),
    "S2_RUNTIME_LOOP": ("off",),
    "S3_FULL_STACK": ("rust", "python", "off"),
}
REASON_CODES = {
    "component_unavailable",
    "capability_handshake_failed",
    "environment_unavailable",
    "metric_not_exposed",
    "provider_telemetry_unavailable",
    "run_failed",
    "source_restore_failed",
    "toolchain_unavailable",
    "unsupported_platform",
}
METRICS = (
    "total_ms",
    "orientation_ms",
    "context_ms",
    "planning_ms",
    "mutation_ms",
    "tests_ms",
    "review_ms",
    "refresh_ms",
    "ipc_ms",
    "ttft_ms",
    "llm_latency_ms",
    "tokens_input",
    "tokens_output",
    "tokens_cache",
    "tool_schema_tokens",
    "cpu_ms",
    "peak_rss_kib",
    "page_faults",
    "io_bytes",
    "snapshot_bytes",
    "index_bytes",
    "cache_hits",
    "cache_misses",
    "files_reprocessed",
    "files_reused",
    "retries",
    "observed_cost",
)


class ProtocolError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def cell_id(scenario: str, engine: str, workload: str, slots: int) -> str:
    return f"{scenario}:{engine}:{workload}:slots-{slots}"


def preregister(*, seed: int, repetitions: int = 10, slots=(1, 20, 100)) -> dict:
    if repetitions < 10:
        raise ProtocolError("repetitions_must_be_at_least_10")
    cells = [
        {
            "scenario": scenario,
            "engine": engine,
            "workload": workload,
            "slots": slot,
            "repetition": repetition,
        }
        for scenario in SCENARIOS
        for engine in ENGINES[scenario]
        for workload in WORKLOADS
        for slot in slots
        for repetition in range(1, repetitions + 1)
    ]
    random.Random(seed).shuffle(cells)
    plan = {
        "schema": SCHEMA,
        "kind": "preregistration",
        "seed": seed,
        "repetitions": repetitions,
        "slots": list(slots),
        "runs": cells,
    }
    plan["plan_sha256"] = sha256(plan)
    return plan


def unavailable(reason: str, detail: str | None = None) -> dict:
    if reason not in REASON_CODES:
        raise ProtocolError(f"unknown_reason_code:{reason}")
    return {"value": None, "reason": reason, "detail": detail}


def blocked_run(run: dict, reason: str, detail: str | None = None) -> dict:
    receipt = dict(run)
    receipt.update(
        {
            "schema": SCHEMA,
            "kind": "run",
            "status": "blocked",
            "blocked": unavailable(reason, detail),
            "metrics": {name: unavailable(reason, detail) for name in METRICS},
        }
    )
    return receipt


def _require_hash(value: Any, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ProtocolError(f"{name}_must_be_sha256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ProtocolError(f"{name}_must_be_sha256") from exc


def validate_run(run: dict) -> None:
    required = (
        "schema",
        "kind",
        "status",
        "scenario",
        "engine",
        "workload",
        "slots",
        "repetition",
        "corpus_sha256",
        "source_commit",
        "environment_sha256",
        "component_versions",
        "metrics",
    )
    missing = [key for key in required if key not in run]
    if missing:
        raise ProtocolError("missing:" + ",".join(missing))
    if run["schema"] != SCHEMA or run["kind"] != "run":
        raise ProtocolError("schema_or_kind_invalid")
    if (
        run["scenario"] not in SCENARIOS
        or run["engine"] not in ENGINES[run["scenario"]]
    ):
        raise ProtocolError("invalid_cell")
    if run["status"] not in {"complete", "partial", "blocked", "failed"}:
        raise ProtocolError("invalid_status")
    _require_hash(run["corpus_sha256"], "corpus_sha256")
    _require_hash(run["environment_sha256"], "environment_sha256")
    if not run["source_commit"] or not run["component_versions"]:
        raise ProtocolError("identity_incomplete")
    for name in METRICS:
        if name not in run["metrics"]:
            raise ProtocolError(f"metric_missing:{name}")
        metric = run["metrics"][name]
        if (
            not isinstance(metric, dict)
            or "value" not in metric
            or "reason" not in metric
        ):
            raise ProtocolError(f"metric_shape_invalid:{name}")
        if metric["value"] is None:
            if metric["reason"] not in REASON_CODES:
                raise ProtocolError(f"metric_reason_invalid:{name}")
        elif metric["reason"] is not None or not isinstance(
            metric["value"], (int, float)
        ):
            raise ProtocolError(f"metric_value_invalid:{name}")
    if run["status"] == "complete" and any(
        m["value"] is None for m in run["metrics"].values()
    ):
        raise ProtocolError("complete_run_has_null_metric")
    if run["status"] == "blocked" and not run.get("blocked"):
        raise ProtocolError("blocked_run_requires_reason")


def validate_dataset(document: dict) -> dict:
    if document.get("schema") != SCHEMA or document.get("kind") != "dataset":
        raise ProtocolError("dataset_schema_or_kind_invalid")
    runs = document.get("runs")
    if not isinstance(runs, list):
        raise ProtocolError("runs_must_be_list")
    for run in runs:
        validate_run(run)
    identities = {
        (r["corpus_sha256"], r["source_commit"], r["environment_sha256"]) for r in runs
    }
    if len(identities) > 1:
        raise ProtocolError("frozen_identity_drift")
    counts = Counter(
        cell_id(r["scenario"], r["engine"], r["workload"], r["slots"])
        for r in runs
        if r["status"] in {"complete", "partial"}
    )
    underfilled = sorted(cell for cell, count in counts.items() if count < 10)
    return {
        "valid": True,
        "runs": len(runs),
        "underfilled_cells": underfilled,
        "dataset_sha256": sha256(document),
    }


def load_and_validate(path: str | Path) -> dict:
    return validate_dataset(json.loads(Path(path).read_text(encoding="utf-8")))
