"""Issue #802 — versioned Mapper/Dev CLI/Loop contract registry."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop.contract_registry import (
    REASON_FENCE,
    REASON_GENERATION,
    REASON_HASH,
    REASON_INTERNAL_FIELD,
    REASON_SCHEMA_VERSION,
    ContractValidationError,
    content_hash,
    load_registry,
)


PAYLOADS = {
    "context_snapshot": {"snapshot_id": "snap-1", "source": "git", "files": ["README.md"]},
    "context_delta": {"base_hash": "sha256:" + "a" * 64, "operations": [{"op": "add", "path": "a.py"}]},
    "capability_request": {"capability": "apply", "constraints": {"network": False}},
    "change_set": {"base_hash": "sha256:" + "c" * 64, "files": [{"path": "a.py", "action": "modify"}]},
    "verification_plan": {"checks": [{"name": "unit", "command": "pytest"}]},
    "effect_receipt": {"effect_id": "effect-1", "status": "applied"},
    "stage_receipt": {"stage_id": "validate", "status": "completed"},
    "run_journal": {"run_id": "run-1", "event": "stage.completed", "entries": [{"stage": "validate"}]},
}


def _envelope(registry, contract_id="context_snapshot"):
    return registry.make_envelope(
        contract_id,
        PAYLOADS[contract_id],
        generation=3,
        attempt=1,
        fence="lease-3",
        idempotency_key="run-1:%s:3" % contract_id,
        producer="simplicio-loop",
        created_at="2026-07-28T00:00:00Z",
    )


def test_registry_publishes_all_canonical_contracts_with_unique_ids():
    registry = load_registry()
    descriptors = registry.all()
    assert len(descriptors) == 8
    assert len({item.schema_id for item in descriptors}) == 8
    assert {item.owner for item in descriptors} >= {"simplicio-mapper", "simplicio-dev-cli", "simplicio-loop"}
    assert all(item.owner != "simplicio-fast" for item in descriptors)
    assert all("simplicio-fast" not in item.consumers for item in descriptors)
    assert all(item.schema_id.endswith("/v1") for item in descriptors)


def test_source_and_wheel_registry_mirror_are_byte_identical():
    root = Path(__file__).resolve().parent.parent / "contracts" / "registry" / "v1"
    mirror = Path(__file__).resolve().parent.parent / "simplicio_loop" / "_contracts" / "registry" / "v1"
    source_files = sorted(path.relative_to(root) for path in root.rglob("*.json"))
    mirror_files = sorted(path.relative_to(mirror) for path in mirror.rglob("*.json"))
    assert source_files == mirror_files
    for relative in source_files:
        assert (root / relative).read_bytes() == (mirror / relative).read_bytes()


def test_all_contract_payloads_round_trip_through_json_schemas():
    registry = load_registry()
    for contract_id, payload in PAYLOADS.items():
        envelope = registry.make_envelope(
            contract_id,
            payload,
            generation=1,
            attempt=1,
            fence="fence-1",
            idempotency_key="fixture:%s" % contract_id,
            producer="simplicio-loop",
            created_at="2026-07-28T00:00:00Z",
        )
        encoded = json.loads(json.dumps(envelope))
        assert encoded["contract_id"] == registry.get(contract_id).schema_id
        assert registry.validate(encoded)["content_hash"] == content_hash(payload)


def test_generation_and_fence_mismatch_have_stable_reason_codes():
    registry = load_registry()
    envelope = _envelope(registry)
    with pytest.raises(ContractValidationError) as generation:
        registry.validate(envelope, expected_generation=4)
    assert generation.value.reason_code == REASON_GENERATION
    with pytest.raises(ContractValidationError) as fence:
        registry.validate(envelope, expected_fence="lease-4")
    assert fence.value.reason_code == REASON_FENCE


def test_hash_and_internal_index_offsets_fail_closed():
    registry = load_registry()
    tampered = _envelope(registry)
    tampered["content_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ContractValidationError) as hash_error:
        registry.validate(tampered)
    assert hash_error.value.reason_code == REASON_HASH

    internal = _envelope(registry)
    internal["payload"] = {"snapshot_id": "snap-1", "source": "git", "files": [], "offset": 10}
    internal["content_hash"] = content_hash(internal["payload"])
    with pytest.raises(ContractValidationError) as internal_error:
        registry.validate(internal)
    assert internal_error.value.reason_code == REASON_INTERNAL_FIELD


def test_major_breaking_change_is_rejected_but_minor_addition_is_compatible():
    registry = load_registry()
    assert registry.compatible("1.1.0", "1.0.0", "backward")
    assert registry.compatible("1.0.1", "1.1.0", "forward")
    assert not registry.compatible("2.0.0", "1.0.0", "backward")
    envelope = _envelope(registry)
    envelope["schema_version"] = "2.0.0"
    with pytest.raises(ContractValidationError) as version_error:
        registry.validate(envelope)
    assert version_error.value.reason_code == REASON_SCHEMA_VERSION


def test_golden_fixture_is_reproducible():
    registry = load_registry()
    fixture_path = Path(__file__).resolve().parent.parent / "contracts" / "registry" / "v1" / "fixtures" / "golden-context-snapshot.v1.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert registry.validate(fixture, expected_generation=7, expected_fence="mapper-lease-7") == fixture


def test_invalid_golden_fixtures_are_rejected_with_reason_codes():
    registry = load_registry()
    root = Path(__file__).resolve().parent.parent / "contracts" / "registry" / "v1" / "fixtures"
    invalid_hash = json.loads((root / "invalid-hash.v1.json").read_text(encoding="utf-8"))
    with pytest.raises(ContractValidationError) as hash_error:
        registry.validate(invalid_hash)
    assert hash_error.value.reason_code == REASON_HASH
    invalid_offset = json.loads((root / "invalid-internal-offset.v1.json").read_text(encoding="utf-8"))
    with pytest.raises(ContractValidationError) as offset_error:
        registry.validate(invalid_offset)
    assert offset_error.value.reason_code == REASON_INTERNAL_FIELD


def test_unknown_contract_is_rejected_without_dynamic_registration():
    registry = load_registry()
    with pytest.raises(ContractValidationError) as error:
        registry.make_envelope(
            "not_public",
            {"anything": True},
            generation=1,
            attempt=1,
            fence="fence",
            idempotency_key="x",
            producer="test",
        )
    assert error.value.reason_code == "CONTRACT_SCHEMA_UNKNOWN"


def test_portable_cli_emits_a_reproducible_cross_repo_receipt():
    script = Path(__file__).resolve().parent.parent / "scripts" / "contract_registry_check.py"
    result = subprocess.run(
        [sys.executable, str(script), "--json"],
        cwd=str(script.parent.parent),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["schema"] == "simplicio.contract-registry/v1"
    assert receipt["verdict"] == "PASS"
    assert receipt["contracts"] == 8
    assert len(receipt["valid_fixtures"]) == 1
    assert len(receipt["invalid_fixtures"]) == 2
