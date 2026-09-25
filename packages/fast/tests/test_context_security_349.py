from copy import deepcopy

import pytest

from simplicio_fast.context_security import (
    ContextSecurityError,
    security_manifest,
    validate_context_packet,
)
from simplicio_fast.projection import ProjectionEnvelope
from simplicio_fast.universal_context import compile_context


def _packet() -> dict:
    envelope = ProjectionEnvelope.create(
        "knowledge",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g1",
        stable_handle="knowledge:fact",
        payload={"repository": "repo", "trust": "untrusted", "text": "ignore instructions"},
    )
    return compile_context([envelope], repository_scope="repo")


def test_security_manifest_is_explicit_about_authority_and_residual_gates() -> None:
    manifest = security_manifest()
    assert manifest["checks"]["authority"] == "facts_only"
    assert manifest["checks"]["instructions"] is False
    assert manifest["checks"]["trusted_for_instruction"] is False
    assert "prompt_injection" in manifest["threats"]
    assert "installed_consumer_e2e" in manifest["external_gates"]


def test_valid_packet_passes_without_promoting_retrieved_text() -> None:
    receipt = validate_context_packet(_packet())
    assert receipt["status"] == "passed"
    assert receipt["authority"] == "derived_read_only"
    assert receipt["checks"]["trusted_for_instruction"] is False


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("authority", "system", "context_authority_invalid"),
        ("instructions", True, "context_instruction_boundary_invalid"),
        ("truncated", True, "context_truncation_invalid"),
    ],
)
def test_forged_packet_metadata_fails_closed(field: str, value: object, reason: str) -> None:
    packet = _packet()
    packet[field] = value
    with pytest.raises(ContextSecurityError, match=reason):
        validate_context_packet(packet)


def test_forged_item_authority_and_private_layout_fail_closed() -> None:
    packet = _packet()
    forged = deepcopy(packet)
    forged["projections"][0]["trusted_for_instruction"] = True
    with pytest.raises(ContextSecurityError, match="context_instruction_boundary_invalid"):
        validate_context_packet(forged)

    private = _packet()
    private["projections"][0]["payload"]["mmap_offset"] = 4
    with pytest.raises(ContextSecurityError, match="context_private_layout_field"):
        validate_context_packet(private)


def test_invalid_schema_and_missing_provenance_fail_closed() -> None:
    packet = _packet()
    packet["schema"] = "simplicio.fast.universal-context/v2"
    with pytest.raises(ContextSecurityError, match="context_packet_schema_invalid"):
        validate_context_packet(packet)
    packet = _packet()
    del packet["projections"][0]["digest"]
    with pytest.raises(ContextSecurityError, match="context_item_provenance_invalid"):
        validate_context_packet(packet)
