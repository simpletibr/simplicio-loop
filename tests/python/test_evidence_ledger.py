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
    matrix = ledger.matrix(["AC1", "AC2"])
    assert matrix["claims"]["AC1"]["status"] == "MEASURED"
    assert matrix["claims"]["AC2"]["status"] == "UNVERIFIED"
    assert matrix["watcher"]["ok"] is True


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


def test_matrix_demotes_measured_claim_when_artifact_changes_after_append(tmp_path):
    artifact = tmp_path / "screenshot.png"
    artifact.write_bytes(b"expected-image")
    ledger = EvidenceLedger(tmp_path / "evidence.jsonl", base_sha="base-1", plan_hash="plan-1")
    ledger.record(criterion_id="AC-VISUAL", command="playwright test", exit_code=0, artifact=artifact)

    artifact.write_bytes(b"wrong-scenario-image")

    matrix = ledger.matrix(["AC-VISUAL"])

    assert matrix["claims"]["AC-VISUAL"]["status"] == "UNVERIFIED"
    assert matrix["claims"]["AC-VISUAL"]["receipts"] == []
    invalid = matrix["claims"]["AC-VISUAL"]["invalid_receipts"]
    assert len(invalid) == 1
    assert invalid[0]["watcher_reason"] == "artifact-hash-mismatch"
    assert matrix["watcher"]["ok"] is False
    assert matrix["watcher"]["failures"][0]["criterion_id"] == "AC-VISUAL"


def test_matrix_demotes_measured_claim_when_artifact_disappears(tmp_path):
    artifact = tmp_path / "trace.zip"
    artifact.write_bytes(b"trace")
    ledger = EvidenceLedger(tmp_path / "evidence.jsonl", base_sha="base-1", plan_hash="plan-1")
    ledger.record(criterion_id="AC-E2E", command="playwright test", exit_code=0, artifact=artifact)

    artifact.unlink()

    matrix = ledger.matrix(["AC-E2E"])

    assert matrix["claims"]["AC-E2E"]["status"] == "UNVERIFIED"
    invalid = matrix["claims"]["AC-E2E"]["invalid_receipts"]
    assert len(invalid) == 1
    assert invalid[0]["watcher_reason"] == "artifact-missing"
    assert matrix["watcher"]["ok"] is False
