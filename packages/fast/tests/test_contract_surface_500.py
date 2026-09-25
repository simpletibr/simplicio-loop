import copy
import json
from pathlib import Path

import pytest

from simplicio_fast.contract_surface import (
    ContractSurfaceError,
    contract_manifest,
    invalidation_triggers,
    validate_decision_receipt,
    validate_telemetry_snapshot,
)

ROOT = Path(__file__).parents[1]
EXAMPLES = json.loads(
    (ROOT / "contracts/fast-local/v1/examples.json").read_text(encoding="utf-8")
)


def test_valid_examples_are_contract_authority_vectors():
    telemetry = validate_telemetry_snapshot(EXAMPLES["telemetry_snapshot"])
    decision = validate_decision_receipt(EXAMPLES["decision_receipt"])
    assert telemetry["message_type"] == "telemetry_snapshot"
    assert decision["message_type"] == "decision_receipt"
    assert telemetry["contract_version"] == decision["contract_version"] == "1.0"


def test_validation_is_deterministic_across_mapping_order():
    value = EXAMPLES["telemetry_snapshot"]
    first = validate_telemetry_snapshot(value)
    reordered = {key: value[key] for key in reversed(list(value))}
    reordered["payload"] = {
        key: value["payload"][key] for key in reversed(list(value["payload"]))
    }
    assert validate_telemetry_snapshot(reordered) == first


@pytest.mark.parametrize(
    "version,reason",
    [
        ("2.0", "contract_major_unsupported"),
        ("1.1", "contract_version_unsupported"),
        ("1", "contract_version_invalid"),
    ],
)
def test_version_rules_fail_closed(version, reason):
    value = copy.deepcopy(EXAMPLES["telemetry_snapshot"])
    value["contract_version"] = version
    with pytest.raises(ContractSurfaceError, match=reason):
        validate_telemetry_snapshot(value)


def test_required_and_unavailable_fields_are_distinct():
    value = copy.deepcopy(EXAMPLES["telemetry_snapshot"])
    value["payload"]["unavailable"]["tokens_per_second"] = "not_collected"
    with pytest.raises(ContractSurfaceError, match="required_field_unavailable"):
        validate_telemetry_snapshot(value)


def test_unknown_fields_and_digest_tampering_fail_closed():
    value = copy.deepcopy(EXAMPLES["decision_receipt"])
    value["payload"]["unexpected"] = True
    with pytest.raises(ContractSurfaceError, match="unknown_field"):
        validate_decision_receipt(value)
    value = copy.deepcopy(EXAMPLES["decision_receipt"])
    value["payload"]["confidence"] = 0.5
    with pytest.raises(ContractSurfaceError, match="decision_digest_mismatch"):
        validate_decision_receipt(value)


def test_invalidation_order_is_stable():
    previous = EXAMPLES["telemetry_snapshot"]["generation"]
    current = copy.deepcopy(previous)
    current["concurrency_digest"] = "sha256:" + "8" * 64
    current["model_digest"] = "sha256:" + "9" * 64
    current["hardware_digest"] = "sha256:" + "a" * 64
    assert invalidation_triggers(previous, current) == (
        "model_drift",
        "hardware_drift",
        "concurrency_drift",
    )


def test_manifest_declares_ownership_levels_and_versioning():
    manifest = contract_manifest()
    assert manifest["contract_version"] == "1.0"
    assert manifest["telemetry_levels"]["deep"]
    assert manifest["field_policy"]["required_unavailable"] == "reject"
