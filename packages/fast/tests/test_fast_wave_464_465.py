from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from simplicio_fast.mapper_ingest import MapperIngestError, validate_handoff
from simplicio_fast.receipts import (
    EXECUTION_REPORT_SCHEMA,
    ReceiptError,
    benchmark_receipt,
    validate_execution_report,
)
from simplicio_fast.quant_benchmark import run_benchmark


def _handoff(root: Path, *, generation: str = "g1") -> dict[str, object]:
    artifact = root / "context.json"
    artifact.write_text('{"schema":"mapper"}\n', encoding="utf-8")
    return {
        "handoff": {
            "schema": "simplicio.mapper-fast-handoff/v1",
            "repository_id": root.name,
            "revision": "a" * 40,
            "generation": generation,
            "producer": {"name": "simplicio-mapper", "version": "0.26.11"},
            "fidelity": {"gate": "ready"},
            "artifacts": [{
                "name": "context",
                "path": "context.json",
                "bytes": artifact.stat().st_size,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            }],
            "delta": {"changed_paths": []},
        },
        "receipt": {
            "schema": "simplicio.mapper-fast-handoff-receipt/v1",
            "status": "parsed",
            "generation": generation,
            "handoff_sha256": "b" * 64,
        },
    }


def test_stale_mapper_generation_is_rejected_against_pinned_generation(tmp_path: Path) -> None:
    envelope = _handoff(tmp_path, generation="new")
    with patch("simplicio_fast.mapper_ingest._head", return_value="a" * 40):
        with pytest.raises(MapperIngestError, match="mapper_generation_stale"):
            validate_handoff(tmp_path, envelope, expected_generation="pinned")


def test_repository_identity_is_verified_not_just_present(tmp_path: Path) -> None:
    envelope = _handoff(tmp_path)
    envelope["handoff"]["repository_id"] = "another-repository"
    with patch("simplicio_fast.mapper_ingest._head", return_value="a" * 40):
        with pytest.raises(MapperIngestError, match="mapper_repository_mismatch"):
            validate_handoff(tmp_path, envelope)


def test_digest_mismatch_is_rejected_before_ingest(tmp_path: Path) -> None:
    envelope = _handoff(tmp_path)
    envelope["handoff"]["artifacts"][0]["sha256"] = "c" * 64
    with patch("simplicio_fast.mapper_ingest._head", return_value="a" * 40):
        with pytest.raises(MapperIngestError, match="mapper_digest_mismatch"):
            validate_handoff(tmp_path, envelope)


def test_execution_and_benchmark_receipts_have_standard_shape() -> None:
    receipt = benchmark_receipt(
        repository_id="simplicio-fast",
        source_commit="a" * 40,
        generation="g1",
        fixture={"name": "fixture", "sha256": "b" * 64},
        workload={"name": "query", "sha256": "c" * 64},
        hardware={"platform": "test"},
        cache_policy="cold",
        repetitions=10,
        baseline={"status": "blocked", "reason": "not-run"},
        classification="BLOCKED",
        evidence={"command": "pytest", "exit_code": 0},
    )
    assert receipt["schema"] == EXECUTION_REPORT_SCHEMA
    assert receipt["kind"] == "benchmark"
    assert receipt["repetitions"] == 10
    assert validate_execution_report(receipt) == receipt
    with pytest.raises(ReceiptError, match="measured evidence"):
        validate_execution_report({**receipt, "classification": "MEASURED", "metrics": {}})


def test_quant_benchmark_publishes_execution_report_receipt(tmp_path: Path) -> None:
    receipt = run_benchmark(
        Path(__file__).parents[1],
        sizes=(16,),
        repetitions=10,
        max_vectors=16,
        dimension=4,
        candidate_k=4,
        result_k=2,
    )
    report = receipt["execution_report"]
    assert report["schema"] == EXECUTION_REPORT_SCHEMA
    assert report["fixture"]["sizes"] == [16]
    assert report["workload"]["result_k"] == 2
    assert report["baseline"]["status"] == "blocked"
    assert validate_execution_report(report) == report
