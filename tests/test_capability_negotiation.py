from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from simplicio_loop.capability_negotiation import (
    NegotiationError, negotiate_stage,
)


def doctor(status="available", evidence=True):
    capability_evidence = {
        cap: {"status": "verified", "evidence_ref": f"doctor:test:{cap}"}
        for cap in ("edit", "validate", "safe_edit")
    } if evidence else {}
    return {
        "schema": "simplicio.ecosystem-doctor/v1",
        "components": [{
            "name": "simplicio-dev-cli", "status": status,
            "reason_code": "verified" if status == "available" else status,
            "capabilities": ["edit", "validate", "safe_edit"],
            "capability_evidence": capability_evidence,
        }],
        "handshake": {
            "written": True,
            "record": {"handshake_sha": "sha256:" + "a" * 64},
        },
    }


def manifests():
    parity = "sha256:" + "b" * 64
    return [
        {
            "executor_id": "dev-cli-python", "component": "simplicio-dev-cli",
            "language": "python", "capabilities": ["edit", "validate"],
            "compatibility": 100, "cost_rank": 20, "offline": True,
            "parity_status": "verified", "parity_contract_hash": parity,
        },
        {
            "executor_id": "dev-cli-rust", "component": "simplicio-dev-cli",
            "language": "rust", "capabilities": ["edit", "validate"],
            "compatibility": 100, "cost_rank": 10, "offline": True,
            "parity_status": "verified", "parity_contract_hash": parity,
        },
    ]


REQ = {
    "stage_id": "execute", "required_capabilities": ["edit", "validate"],
    "preferred_languages": ["rust", "python"], "offline_required": True,
}


def test_ranking_selects_verified_rust_deterministically():
    receipt = negotiate_stage(doctor(), manifests(), REQ)
    assert receipt["status"] == "SELECTED"
    assert receipt["selected"]["executor_id"] == "dev-cli-rust"
    assert receipt["doctor_handshake_sha"].startswith("sha256:")
    assert receipt["execution_started"] is False
    assert receipt["model_provider_started"] is False


def test_same_input_permutations_produce_same_receipt():
    expected = negotiate_stage(doctor(), manifests(), REQ)["receipt_hash"]
    rng = random.Random(811)
    for _ in range(100):
        values = manifests()
        rng.shuffle(values)
        assert negotiate_stage(doctor(), values, REQ)["receipt_hash"] == expected


def test_missing_or_degraded_doctor_never_becomes_empty_success():
    for state in ("missing", "degraded", "incompatible"):
        receipt = negotiate_stage(doctor(status=state), manifests(), REQ)
        assert receipt["status"] == "BLOCKED"
        assert receipt["reason_code"] == "no_safe_executor"
        assert {row["reason_code"] for row in receipt["unavailable"]} == {
            f"doctor_{state}"
        }


def test_capability_without_doctor_evidence_is_unavailable():
    receipt = negotiate_stage(doctor(evidence=False), manifests(), REQ)
    assert receipt["status"] == "BLOCKED"
    assert all(
        row["reason_code"] == "capability_evidence_missing"
        for row in receipt["unavailable"]
    )


def test_policy_can_deny_installed_rust_and_select_python():
    receipt = negotiate_stage(
        doctor(), manifests(), REQ, policy={"denied_languages": ["rust"]}
    )
    assert receipt["selected"]["executor_id"] == "dev-cli-python"
    assert any(
        row["executor_id"] == "dev-cli-rust"
        and row["reason_code"] == "policy_denied"
        for row in receipt["unavailable"]
    )


def test_rust_without_python_parity_falls_back_to_python():
    values = manifests()
    values[1]["parity_contract_hash"] = "sha256:" + "c" * 64
    receipt = negotiate_stage(doctor(), values, REQ)
    assert receipt["selected"]["executor_id"] == "dev-cli-python"
    assert any(
        row["executor_id"] == "dev-cli-rust"
        and row["reason_code"] == "rust_python_parity_unverified"
        for row in receipt["skipped"]
    )


def test_offline_requirement_blocks_online_executor():
    values = manifests()
    for row in values:
        row["offline"] = False
    receipt = negotiate_stage(doctor(), values, REQ)
    assert receipt["status"] == "BLOCKED"
    assert {row["reason_code"] for row in receipt["skipped"]} == {
        "offline_requirement_not_met"
    }


def test_explicit_capability_fallback_is_recorded():
    values = [{
        "executor_id": "safe-python", "component": "simplicio-dev-cli",
        "language": "python", "capabilities": ["safe_edit"],
        "compatibility": 90, "cost_rank": 5, "offline": True,
        "parity_status": "verified", "parity_contract_hash": "sha256:" + "d" * 64,
    }]
    requirement = {
        **REQ, "alternatives": [["safe_edit"]],
    }
    receipt = negotiate_stage(doctor(), values, requirement)
    assert receipt["status"] == "SELECTED"
    assert receipt["fallback"] == {
        "used": True,
        "from_capabilities": ["edit", "validate"],
        "to_capabilities": ["safe_edit"],
        "reason_code": "primary_unavailable_explicit_fallback",
    }


def test_provider_side_effect_manifest_is_denied_without_starting_it():
    values = [{
        **manifests()[0], "executor_id": "unsafe",
        "starts_model_or_provider": True,
    }]
    receipt = negotiate_stage(doctor(), values, REQ)
    assert receipt["status"] == "BLOCKED"
    assert receipt["unavailable"][0]["reason_code"] == "provider_side_effect_forbidden"
    assert receipt["model_provider_started"] is False


def test_missing_handshake_fails_closed():
    report = doctor()
    report["handshake"]["written"] = False
    with pytest.raises(NegotiationError, match="doctor_handshake_evidence_missing"):
        negotiate_stage(report, manifests(), REQ)


def test_receipt_fixture_is_reproducible():
    receipt = negotiate_stage(doctor(), manifests(), REQ)
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "executor_negotiation_receipt.json").read_text()
    )
    assert receipt == fixture
