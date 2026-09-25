from __future__ import annotations

import copy

import pytest

from simplicio.plan_compiler.errors import PlanValidationError
from simplicio.plan_compiler.execution_contracts import (
    BOUND_VERIFICATION_PLAN_SCHEMA,
    CHANGE_SET_SCHEMA,
    BoundVerificationPlan,
    ChangeSet,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def changeset_payload(*, mode: str = "write") -> dict:
    return {
        "schema": CHANGE_SET_SCHEMA,
        "change_set_id": "change-363",
        "idempotency_key": "idem-363",
        "generation": 7,
        "mode": mode,
        "context_hashes": {
            "context_packet": DIGEST_A,
            "fast_generation": DIGEST_B,
            "plan_dag": DIGEST_C,
        },
        "preconditions": ["git-head:" + DIGEST_A],
        "operations": [
            {
                "operation_id": "op-1",
                "kind": "replace",
                "target": "src/app.py",
                "before_hash": DIGEST_A,
                "content_handle": "hbp://sha256/" + DIGEST_B,
                "producer_extension": {"safe": True},
            }
        ],
        "write_set": ["src/app.py"],
        "consumer_extension": "preserved",
    }


def verification_payload(change_set_hash: str) -> dict:
    return {
        "schema": BOUND_VERIFICATION_PLAN_SCHEMA,
        "verification_plan_id": "verify-363",
        "change_set_hash": change_set_hash,
        "context_hashes": {
            "context_packet": DIGEST_A,
            "fast_generation": DIGEST_B,
            "plan_dag": DIGEST_C,
        },
        "commands": [
            {
                "command_id": "pytest-targeted",
                "level": "targeted",
                "argv": ["python", "-m", "pytest", "-q", "tests/test_app.py"],
                "timeout_s": 30,
                "expected_signals": ["exit_code:0"],
            }
        ],
        "future_policy": {"preserve": True},
    }


@pytest.mark.parametrize("mode", ["dry-run", "write"])
def test_changeset_supports_modes_and_preserves_unknown_fields(mode: str) -> None:
    contract = ChangeSet.from_dict(changeset_payload(mode=mode))
    assert contract.to_dict() == changeset_payload(mode=mode)


def test_changeset_requires_all_context_hashes_for_write() -> None:
    payload = changeset_payload()
    payload["context_hashes"]["fast_generation"] = ""
    with pytest.raises(PlanValidationError, match="fast_generation: hash_required"):
        ChangeSet.from_dict(payload)


def test_open_ambiguous_instruction_cannot_become_arbitrary_edit() -> None:
    payload = changeset_payload()
    payload["operations"][0]["instruction"] = "improve this however you think best"
    with pytest.raises(PlanValidationError, match="open_instruction_rejected"):
        ChangeSet.from_dict(payload)


@pytest.mark.parametrize("target", ["/etc/passwd", "../escape.py", "src/../../escape.py"])
def test_target_must_be_repo_relative_and_fenced(target: str) -> None:
    payload = changeset_payload()
    payload["operations"][0]["target"] = target
    payload["write_set"] = [target]
    with pytest.raises(PlanValidationError, match="unsafe_target"):
        ChangeSet.from_dict(payload)


def test_verification_plan_is_deterministic_and_context_bound() -> None:
    change_set = ChangeSet.from_dict(changeset_payload())
    payload = verification_payload(change_set.canonical_hash())
    first = BoundVerificationPlan.from_dict(copy.deepcopy(payload))
    second = BoundVerificationPlan.from_dict(copy.deepcopy(payload))
    assert first.to_dict() == payload
    assert first.canonical_hash() == second.canonical_hash()


def test_verification_uses_argv_not_open_shell_text() -> None:
    payload = verification_payload(DIGEST_A)
    payload["commands"][0]["argv"] = []
    with pytest.raises(PlanValidationError, match="argv_required"):
        BoundVerificationPlan.from_dict(payload)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda payload: payload.update(change_set_id=""), "change_set_id: required"),
        (lambda payload: payload.update(idempotency_key=""), "idempotency_key: required"),
        (lambda payload: payload.update(generation=0), "generation: positive_value_required"),
        (lambda payload: payload.update(mode="plan"), "mode: unsupported_mode"),
        (lambda payload: payload.update(operations=[]), "mechanical_operation_required"),
        (lambda payload: payload.update(preconditions=[]), "preconditions: required"),
        (
            lambda payload: payload.update(write_set=["src/app.py", "src/app.py"]),
            "duplicate_target",
        ),
        (lambda payload: payload.update(write_set=["other.py"]), "operation_target_mismatch"),
    ],
)
def test_changeset_reports_stable_reason_codes(mutation, reason: str) -> None:
    payload = changeset_payload()
    mutation(payload)
    with pytest.raises(PlanValidationError, match=reason):
        ChangeSet.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("kind", "improvise", "unsupported_operation"),
        ("content_handle", None, "content_handle_required"),
        ("before_hash", None, "before_hash: hash_required"),
    ],
)
def test_operation_is_fully_mechanical(field: str, value, reason: str) -> None:
    payload = changeset_payload()
    payload["operations"][0][field] = value
    with pytest.raises(PlanValidationError, match=reason):
        ChangeSet.from_dict(payload)


def test_wrong_schema_is_rejected() -> None:
    payload = changeset_payload()
    payload["schema"] = "simplicio.change-set/v2"
    with pytest.raises(ValueError, match="expected schema"):
        ChangeSet.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("verification_plan_id", "", "verification_plan_id: required"),
        ("commands", [], "commands: required"),
    ],
)
def test_verification_required_fields(field: str, value, reason: str) -> None:
    payload = verification_payload(DIGEST_A)
    payload[field] = value
    with pytest.raises(PlanValidationError, match=reason):
        BoundVerificationPlan.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("level", "arbitrary", "unsupported_level"),
        ("timeout_s", 0, "timeout_required"),
        ("expected_signals", [], "expected_signal_required"),
    ],
)
def test_verification_command_is_closed(field: str, value, reason: str) -> None:
    payload = verification_payload(DIGEST_A)
    payload["commands"][0][field] = value
    with pytest.raises(PlanValidationError, match=reason):
        BoundVerificationPlan.from_dict(payload)
