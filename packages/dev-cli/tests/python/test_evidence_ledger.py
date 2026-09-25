from __future__ import annotations

import json

import pytest

from simplicio.evidence_ledger import (
    ArtifactMismatchError,
    EvidenceLedger,
    LedgerError,
    StaleEvidenceError,
    artifact_digest,
)


def test_ledger_records_measured_artifact_and_matrix(tmp_path):
    artifact = tmp_path / "result.json"
    artifact.write_text(json.dumps({"scenario": "ac1"}), encoding="utf-8")
    trace = tmp_path / "trace.zip"
    trace.write_bytes(b"trace")
    ledger = EvidenceLedger(
        tmp_path / "evidence.jsonl", base_sha="base-1", plan_hash="plan-1", commit_sha="commit-1"
    )

    row = ledger.record(
        criterion_id="AC1",
        command="pytest tests/e2e/ac1.py",
        exit_code=0,
        artifact=artifact,
        prototype="fixtures/planes.json",
        attachments=({"path": str(trace), "kind": "trace"},),
    )

    assert row["status"] == "MEASURED"
    assert row["commit_sha"] == "commit-1"
    assert row["prototype"] == "fixtures/planes.json"
    assert row["attachments"][0]["kind"] == "trace"
    assert row["attachments"][0]["sha256"].startswith("sha256:")
    assert row["artifact_hash"].startswith("sha256:")
    matrix = ledger.watch(["AC1", "AC2"])
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


def test_ledger_rejects_stale_commit_identity(tmp_path):
    artifact = tmp_path / "out.txt"
    artifact.write_text("ok", encoding="utf-8")
    ledger = EvidenceLedger(
        tmp_path / "evidence.jsonl", base_sha="base-1", plan_hash="plan-1", commit_sha="new"
    )

    with pytest.raises(StaleEvidenceError):
        ledger.record(criterion_id="AC1", command="pytest", exit_code=0, artifact=artifact, commit_sha="old")


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


def test_watcher_rejects_stale_receipt_and_changed_attachment(tmp_path):
    artifact = tmp_path / "result.json"
    artifact.write_text("ok", encoding="utf-8")
    attachment = tmp_path / "screenshot.png"
    attachment.write_bytes(b"expected")
    ledger = EvidenceLedger(
        tmp_path / "evidence.jsonl", base_sha="base-1", plan_hash="plan-1", commit_sha="commit-1"
    )
    ledger.record(
        criterion_id="AC-WATCH",
        command="playwright test",
        exit_code=0,
        artifact=artifact,
        attachments=({"path": str(attachment), "kind": "screenshot"},),
    )
    attachment.write_bytes(b"wrong-scenario")
    matrix = ledger.watch(["AC-WATCH"])
    assert matrix["claims"]["AC-WATCH"]["status"] == "UNVERIFIED"
    assert matrix["watcher"]["failures"][0]["reason"] == "attachment-hash-mismatch"

    stale = EvidenceLedger(
        tmp_path / "evidence.jsonl", base_sha="new-base", plan_hash="plan-1", commit_sha="commit-1"
    )
    stale_matrix = stale.watch(["AC-WATCH"])
    assert stale_matrix["watcher"]["failures"][0]["reason"] == "stale-identity"


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


@pytest.mark.parametrize(
    ("receipt", "error", "message"),
    [
        ({"schema": "wrong"}, LedgerError, "unsupported evidence ledger schema"),
        ({"criterion_id": "", "base_sha": "base-1", "plan_hash": "plan-1"}, LedgerError, "criterion_id"),
        (
            {"criterion_id": "AC1", "base_sha": "base-1", "plan_hash": "plan-1", "status": "BLOCKED"},
            LedgerError,
            "status",
        ),
        (
            {
                "criterion_id": "AC1",
                "base_sha": "base-1",
                "plan_hash": "plan-1",
                "status": "MEASURED",
                "artifact": "missing.txt",
            },
            LedgerError,
            "command",
        ),
        (
            {
                "criterion_id": "AC1",
                "base_sha": "base-1",
                "plan_hash": "plan-1",
                "status": "MEASURED",
                "command": "pytest",
                "exit_code": 0,
            },
            LedgerError,
            "artifact",
        ),
        (
            {
                "criterion_id": "AC1",
                "base_sha": "base-1",
                "plan_hash": "plan-1",
                "status": "MEASURED",
                "command": "pytest",
                "exit_code": 0,
                "artifact": "missing.txt",
            },
            ArtifactMismatchError,
            "unavailable",
        ),
    ],
)
def test_ledger_rejects_invalid_receipts(tmp_path, receipt, error, message):
    ledger = EvidenceLedger(tmp_path / "evidence.jsonl", base_sha="base-1", plan_hash="plan-1")
    with pytest.raises(error, match=message):
        ledger.append(receipt)


@pytest.mark.parametrize(
    ("attachments", "message"),
    [
        ("not-a-list", "attachments must be a list"),
        (["not-an-object"], "each attachment must be an object"),
        ([{}], "each attachment requires path, artifact, or file"),
        ([{"path": "missing.zip"}], "attachment is unavailable"),
    ],
)
def test_ledger_rejects_invalid_attachments(tmp_path, attachments, message):
    artifact = tmp_path / "result.json"
    artifact.write_text("ok", encoding="utf-8")
    ledger = EvidenceLedger(tmp_path / "evidence.jsonl", base_sha="base-1", plan_hash="plan-1")
    with pytest.raises((LedgerError, ArtifactMismatchError), match=message):
        ledger.record(
            criterion_id="AC-ATTACH",
            command="pytest",
            exit_code=0,
            artifact=artifact,
            attachments=attachments,
        )


def test_matrix_reports_missing_and_invalid_attachment_hashes(tmp_path):
    artifact = tmp_path / "result.json"
    attachment = tmp_path / "trace.zip"
    artifact.write_text("ok", encoding="utf-8")
    attachment.write_bytes(b"trace")
    ledger = EvidenceLedger(tmp_path / "evidence.jsonl", base_sha="base-1", plan_hash="plan-1")
    ledger.record(
        criterion_id="AC-HASH",
        command="pytest",
        exit_code=0,
        artifact=artifact,
        attachments=({"path": str(attachment), "kind": "trace"},),
    )
    row = ledger.rows()[0]
    row["attachments"][0].pop("sha256")
    ledger.path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert ledger.matrix(["AC-HASH"])["claims"]["AC-HASH"]["invalid_receipts"][0]["watcher_reason"] == (
        "missing-attachment-hash"
    )


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        ({"status": "MEASURED"}, "missing-artifact-path"),
        ({"status": "MEASURED", "artifact": "out.txt"}, "stale-identity"),
        (
            {
                "status": "MEASURED",
                "artifact": "out.txt",
                "base_sha": "base-1",
                "plan_hash": "plan-1",
                "commit_sha": "",
            },
            "stale-identity",
        ),
    ],
)
def test_matrix_reports_missing_or_stale_artifact_identity(tmp_path, row, reason):
    ledger = EvidenceLedger(tmp_path / "evidence.jsonl", base_sha="base-1", plan_hash="plan-1")
    row = {"criterion_id": "AC-STATE", **row}
    ledger.path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    result = ledger.matrix(["AC-STATE"])
    assert result["claims"]["AC-STATE"]["invalid_receipts"][0]["watcher_reason"] == reason


@pytest.mark.parametrize(
    ("attachment", "reason"),
    [
        ("not-an-object", "invalid-attachments"),
        ({}, "missing-attachment-path"),
        ({"path": "missing.zip"}, "attachment-missing"),
    ],
)
def test_matrix_reports_invalid_attachment_shapes(tmp_path, attachment, reason):
    artifact = tmp_path / "out.txt"
    artifact.write_text("ok", encoding="utf-8")
    ledger = EvidenceLedger(tmp_path / "evidence.jsonl", base_sha="base-1", plan_hash="plan-1")
    row = {
        "criterion_id": "AC-ATTACH-WATCH",
        "status": "MEASURED",
        "artifact": str(artifact),
        "artifact_hash": artifact_digest(artifact),
        "base_sha": "base-1",
        "plan_hash": "plan-1",
        "commit_sha": ledger.commit_sha,
        "attachments": [attachment],
    }
    ledger.path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    result = ledger.matrix(["AC-ATTACH-WATCH"])
    assert result["claims"]["AC-ATTACH-WATCH"]["invalid_receipts"][0]["watcher_reason"] == reason


def test_matrix_ignores_unverified_receipt_without_watcher_failure(tmp_path):
    ledger = EvidenceLedger(tmp_path / "evidence.jsonl", base_sha="base-1", plan_hash="plan-1")
    ledger.path.write_text(
        json.dumps({"criterion_id": "AC-UNVERIFIED", "status": "UNVERIFIED"}) + "\n",
        encoding="utf-8",
    )
    result = ledger.matrix(["AC-UNVERIFIED"])
    assert result["claims"]["AC-UNVERIFIED"]["status"] == "UNVERIFIED"
    assert result["watcher"]["ok"] is True
