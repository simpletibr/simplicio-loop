from __future__ import annotations

import json

import pytest

from simplicio.evidence_ledger import ArtifactMismatchError, EvidenceLedger, StaleEvidenceError


def test_ledger_records_measured_artifact_and_matrix(tmp_path):
    artifact = tmp_path / "result.json"
    artifact.write_text(json.dumps({"scenario": "ac1"}), encoding="utf-8")
    ledger = EvidenceLedger(tmp_path / "evidence.jsonl", base_sha="base-1", plan_hash="plan-1")

    row = ledger.record(criterion_id="AC1", command="pytest tests/e2e/ac1.py", exit_code=0, artifact=artifact)

    assert row["status"] == "MEASURED"
    assert row["artifact_hash"].startswith("sha256:")
    assert ledger.matrix(["AC1", "AC2"])["claims"]["AC1"]["status"] == "MEASURED"
    assert ledger.matrix(["AC1", "AC2"])["claims"]["AC2"]["status"] == "UNVERIFIED"


def test_ledger_rejects_stale_identity(tmp_path):
    artifact = tmp_path / "out.txt"
    artifact.write_text("ok", encoding="utf-8")
    ledger = EvidenceLedger(tmp_path / "evidence.jsonl", base_sha="base-1", plan_hash="plan-1")

    with pytest.raises(StaleEvidenceError):
        ledger.record(
            criterion_id="AC1", command="pytest", exit_code=0, artifact=artifact, plan_hash="old-plan"
        )


def test_ledger_rejects_changed_artifact_hash(tmp_path):
    artifact = tmp_path / "out.txt"
    artifact.write_text("ok", encoding="utf-8")
    ledger = EvidenceLedger(tmp_path / "evidence.jsonl", base_sha="base-1", plan_hash="plan-1")
    wrong_hash = "sha256:" + "0" * 64

    with pytest.raises(ArtifactMismatchError):
        ledger.append(
            {
                "criterion_id": "AC1",
                "command": "pytest",
                "exit_code": 0,
                "artifact": str(artifact),
                "artifact_hash": wrong_hash,
                "base_sha": "base-1",
                "plan_hash": "plan-1",
                "status": "MEASURED",
            }
        )
