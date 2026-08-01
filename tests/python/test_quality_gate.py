from __future__ import annotations

import json
import sys

from scripts.quality_gate import SCHEMA, _write_receipt, main, run_gate, verify_receipt


def test_quality_gate_receipt_is_sha_bound_and_records_failures(tmp_path):
    passing = run_gate(
        tmp_path,
        commands=[("pass", [sys.executable, "-c", "print('ok')"])],
    )
    assert passing["schema"] == SCHEMA
    assert passing["commit_sha"] is None
    assert passing["passed"] is False
    assert passing["commands"][0]["name"] == "pass"


def test_quality_gate_cli_persists_failure_receipt(tmp_path):
    receipt = tmp_path / "receipt.json"
    code = main(
        [
            "--root",
            str(tmp_path),
            "--receipt",
            str(receipt),
            "--command",
            f"fail={sys.executable} -c exit(3)",
        ]
    )
    assert code == 1
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["schema"] == SCHEMA
    assert payload["passed"] is False
    assert payload["commands"][0]["exit_code"] == 3
    assert payload["receipt_digest"].startswith("sha256:")


def test_quality_gate_verifier_rejects_tampering(tmp_path):
    receipt = tmp_path / "receipt.json"
    payload = run_gate(tmp_path, commands=[])
    payload["commit_sha"] = "not-current"
    _write_receipt(receipt, payload)
    ok, reason = verify_receipt(receipt, tmp_path)
    assert ok is False
    assert reason == "receipt_sha_stale"

    receipt.write_text(receipt.read_text(encoding="utf-8").replace('"passed": false', '"passed": true'), encoding="utf-8")
    ok, reason = verify_receipt(receipt, tmp_path)
    assert ok is False
    assert reason == "receipt_digest_invalid"


def test_quality_gate_records_command_timeout(tmp_path):
    payload = run_gate(
        tmp_path,
        commands=[("slow", [sys.executable, "-c", "import time; time.sleep(2)"])],
        timeout_s=0.01,
    )
    assert payload["passed"] is False
    assert payload["commands"][0]["exit_code"] == 124
    assert "TimeoutExpired" in payload["commands"][0]["error"]
