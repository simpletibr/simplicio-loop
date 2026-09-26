from __future__ import annotations

import json

from scripts.issue_412_acceptance_gate import SCHEMA, build_matrix, main


def _report(schema: str, commit_sha: str, **extra):
    return {"schema": schema, "commit_sha": commit_sha, **extra}


def test_acceptance_gate_refuses_missing_or_unverified_evidence(tmp_path):
    payload = build_matrix(tmp_path, {})

    assert payload["schema"] == SCHEMA
    assert payload["ready_to_close"] is False
    assert "installed-cross-repo-e2e" in payload["blocking_criteria"]
    assert all(row["status"] in {"BLOCKED", "UNVERIFIED"} for row in payload["criteria"])


def test_acceptance_gate_rejects_stale_report_sha(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.issue_412_acceptance_gate._git_sha", lambda _root: "current")
    report = tmp_path / "quality.json"
    report.write_text(
        json.dumps(_report("simplicio.dev-cli.quality-gate-receipt/v1", "stale", passed=True, dirty=False))
    )

    payload = build_matrix(tmp_path, {"quality": report})
    row = next(item for item in payload["criteria"] if item["criterion"] == "local-quality-gate")
    assert row["status"] == "FAIL"
    assert payload["ready_to_close"] is False


def test_acceptance_gate_cli_returns_nonzero_without_all_criteria(tmp_path):
    output = tmp_path / "matrix.json"
    assert main(["--root", str(tmp_path), "--output", str(output)]) == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["ready_to_close"] is False


def test_acceptance_gate_treats_malformed_report_as_unverified(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.issue_412_acceptance_gate._git_sha", lambda _root: "current")
    report = tmp_path / "issue-416.json"
    report.write_text(
        json.dumps(
            _report(
                "simplicio.dev-cli.issue-416-transaction-benchmark/v1",
                "current",
                rows=[{"lane": "python_transaction", "size": 1, "status": "PASS", "repeats": None}],
            )
        )
    )

    payload = build_matrix(tmp_path, {"issue-416": report})
    row = next(item for item in payload["criteria"] if item["criterion"] == "atomic-recoverable-transaction")
    assert row["status"] == "UNVERIFIED"


def test_acceptance_gate_has_no_fast_criteria(tmp_path):
    payload = build_matrix(tmp_path, {})

    assert not [row["criterion"] for row in payload["criteria"] if "fast" in row["criterion"]]
