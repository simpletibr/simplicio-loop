from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from simplicio_loop.hbp_ledger import (
    AcceptanceEvidence, GENESIS_HASH, HbpAppendError, HbpBinding, HbpLedger,
    build_receipt, canonical_bytes, canonical_sha256, completion_oracle,
    verify_file, verify_receipts,
)


def binding(**changes):
    values = {
        "run_id": "run-813", "plan_hash": "plan-sha256",
        "generation": "g1", "attempt": 1, "fence": 7, "stage": "verify",
    }
    values.update(changes)
    return HbpBinding(**values)


def evidence(ac="AC1", verdict="PASS"):
    return AcceptanceEvidence(
        ac, "artifact://pytest/report", canonical_sha256({"test": ac}),
        verdict=verdict,
    )


def chain():
    first = build_receipt(
        sequence=1, binding=binding(), previous_receipt_hash=GENESIS_HASH,
        evidence=[evidence("AC1")], payload={"exit_code": 0},
        observed_at_ns=1,
    )
    second = build_receipt(
        sequence=2, binding=binding(),
        previous_receipt_hash=first["receipt_hash"],
        evidence=[evidence("AC2")], payload={"coverage": 92},
        observed_at_ns=2,
    )
    return [first, second]


def test_golden_canonical_hash_is_order_and_unicode_stable():
    left = {"b": 2, "a": "cafe\u0301"}
    right = {"a": "café", "b": 2}
    assert canonical_bytes(left) == canonical_bytes(right)
    assert canonical_sha256(left) == "6d25402cde044dae7bc06b10f117a4e1ad4b9068984aa262f46af63e330e7aa6"
    with pytest.raises(TypeError, match="floats"):
        canonical_sha256({"ambiguous": 1.2})


def test_append_verify_and_oracle_complete_offline(tmp_path):
    ledger = HbpLedger(tmp_path / "evidence.hbp", binding())
    first = ledger.append(evidence=[evidence("AC1")], payload={"exit_code": 0})
    second = ledger.append(evidence=[evidence("AC2")], payload={"coverage": 92})
    assert second["previous_receipt_hash"] == first["receipt_hash"]
    verified = ledger.verify()
    assert verified["status"] == "VERIFIED"
    receipts = [
        json.loads(line) for line in ledger.path.read_text(encoding="utf-8").splitlines()
    ]
    oracle = completion_oracle(
        receipts, expected=binding(), acceptance_criteria=["AC1", "AC2"]
    )
    assert oracle["verdict"] == "COMPLETE"
    assert all(row["evidence_hashes"] for row in oracle["acceptance_matrix"])
    assert oracle["offline"] is True


def test_one_byte_tamper_invalidates_receipt_and_file(tmp_path):
    receipts = chain()
    receipts[0]["payload"]["exit_code"] = 1
    verified = verify_receipts(receipts, expected=binding())
    assert verified["status"] == "INVALID"
    assert verified["reason_code"] == "PAYLOAD_TAMPERED"

    path = tmp_path / "chain.hbp"
    path.write_bytes(canonical_bytes(chain()[0]) + b"\n")
    raw = path.read_bytes().replace(b'"exit_code":0', b'"exit_code":1')
    path.write_bytes(raw)
    assert verify_file(path, expected=binding())["reason_code"] == "PAYLOAD_TAMPERED"


@pytest.mark.parametrize(
    ("changed", "reason"),
    [
        ({"run_id": "other"}, "CROSS_RUN_ID"),
        ({"stage": "apply"}, "CROSS_STAGE"),
        ({"fence": 8}, "CROSS_FENCE"),
        ({"plan_hash": "old"}, "STALE_PLAN_HASH"),
        ({"generation": "old"}, "STALE_GENERATION"),
        ({"attempt": 2}, "STALE_ATTEMPT"),
    ],
)
def test_cross_and_stale_replay_are_rejected(changed, reason):
    assert verify_receipts(chain(), expected=binding(**changed))["reason_code"] == reason


def test_previous_hash_break_and_invalid_history_block_append(tmp_path):
    receipts = chain()
    receipts[1]["previous_receipt_hash"] = "f" * 64
    assert verify_receipts(receipts, expected=binding())["reason_code"] == "PREVIOUS_HASH_MISMATCH"
    path = tmp_path / "ledger.hbp"
    path.write_text("\n".join(json.dumps(item) for item in receipts) + "\n")
    with pytest.raises(HbpAppendError):
        HbpLedger(path, binding()).append(evidence=[evidence()], payload={"x": 1})


def test_missing_evidence_is_partial_and_invalid_chain_is_blocked():
    partial = completion_oracle(
        chain(), expected=binding(), acceptance_criteria=["AC1", "AC2", "AC3"]
    )
    assert partial["verdict"] == "PARTIAL"
    assert partial["reason_code"] == "AC_EVIDENCE_MISSING"
    tampered = copy.deepcopy(chain())
    tampered[0]["payload"]["exit_code"] = 9
    blocked = completion_oracle(
        tampered, expected=binding(), acceptance_criteria=["AC1"]
    )
    assert blocked["verdict"] == "BLOCKED"


def test_legacy_is_classified_partial_not_trusted():
    legacy = [{"schema": "simplicio.evidence-receipt/v1", "status": "VERIFIED"}]
    verification = verify_receipts(legacy, expected=binding())
    assert verification["status"] == "LEGACY"
    oracle = completion_oracle(
        legacy, expected=binding(), acceptance_criteria=["AC1"]
    )
    assert oracle["verdict"] == "PARTIAL"
    assert oracle["reason_code"] == "LEGACY_CHAIN"


def test_golden_fixture_verifies_and_hashes_reproduce():
    fixture = Path(__file__).parent / "fixtures" / "hbp_chain_813.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    receipts = payload["receipts"]
    assert verify_receipts(receipts, expected=binding())["status"] == "VERIFIED"
    expected_hash = payload["fixture_hash"]
    assert expected_hash == canonical_sha256({"receipts": receipts})


def test_measured_benchmark_receipt_hash_reproduces():
    fixture = Path(__file__).parent / "fixtures" / "hbp_benchmark_813.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    assert payload["classification"] == "MEASURED_LOCAL"
    assert payload["runs"] >= 100
    assert payload["verdict"] == "COMPLETE"
    assert payload["local_llm"] is False
    expected = payload.pop("receipt_hash")
    assert expected == canonical_sha256(payload)
