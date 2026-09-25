"""Fail-closed validation for provider-neutral context packets."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from .universal_context import CONTEXT_SCHEMA


SECURITY_SCHEMA = "simplicio.fast.context-security/v1"
_PRIVATE_FIELDS = frozenset({"offset", "mmap_offset", "address", "pointer"})
_MAX_PACKET_ITEMS = 100_000


class ContextSecurityError(ValueError):
    """Raised when a packet cannot be trusted as a derived facts-only result."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def security_manifest() -> dict[str, Any]:
    """Return the consumer-side security boundary and residual external gates."""
    return {
        "schema": SECURITY_SCHEMA,
        "packet_schema": CONTEXT_SCHEMA,
        "checks": {
            "authority": "facts_only",
            "instructions": False,
            "trusted_for_instruction": False,
            "private_layout_fields": "reject",
            "projection_item_cap": _MAX_PACKET_ITEMS,
        },
        "threats": [
            "projection_poisoning",
            "digest_or_handle_tamper",
            "prompt_injection",
            "trust_escalation",
            "cross_scope_leakage",
        ],
        "authority": "derived_read_only",
        "external_gates": [
            "installed_consumer_e2e",
            "fault_injection_recovery",
            "resource_benchmark",
            "rollout_receipt",
        ],
    }


def validate_context_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a packet before a consumer exposes it to a model or tool.

    Retrieved payloads remain opaque data. The validator does not interpret
    their text, grant authority, or authorize an action.
    """
    if not isinstance(packet, Mapping) or packet.get("schema") != CONTEXT_SCHEMA:
        raise ContextSecurityError("context_packet_schema_invalid")
    if packet.get("authority") != "facts_only":
        raise ContextSecurityError("context_authority_invalid")
    if packet.get("instructions") is not False:
        raise ContextSecurityError("context_instruction_boundary_invalid")
    projections = packet.get("projections")
    if not isinstance(projections, Sequence) or isinstance(projections, (str, bytes)):
        raise ContextSecurityError("context_projections_invalid")
    if len(projections) > _MAX_PACKET_ITEMS:
        raise ContextSecurityError("context_item_limit")
    for item in projections:
        _validate_item(item)
    selection = packet.get("selection")
    if not isinstance(selection, Mapping):
        raise ContextSecurityError("context_selection_invalid")
    truncation_reasons = packet.get("truncation_reasons")
    if not isinstance(truncation_reasons, Sequence) or isinstance(truncation_reasons, (str, bytes)):
        raise ContextSecurityError("context_truncation_invalid")
    if bool(packet.get("truncated")) != bool(truncation_reasons):
        raise ContextSecurityError("context_truncation_invalid")
    try:
        encoded = json.dumps(packet, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise ContextSecurityError("context_packet_not_json") from error
    if len(encoded) > 8 * 1024 * 1024:
        raise ContextSecurityError("context_packet_size_limit")
    return {
        "schema": SECURITY_SCHEMA,
        "packet_schema": CONTEXT_SCHEMA,
        "status": "passed",
        "checks": {
            "projection_count": len(projections),
            "authority": "facts_only",
            "instructions": False,
            "trusted_for_instruction": False,
            "private_layout_fields": "absent",
        },
        "authority": "derived_read_only",
    }


def _validate_item(item: object) -> None:
    if not isinstance(item, Mapping):
        raise ContextSecurityError("context_item_invalid")
    required = ("stable_handle", "digest", "producer", "projection_type", "payload")
    if any(not isinstance(item.get(key), str) or not str(item.get(key)).strip() for key in required[:-1]):
        raise ContextSecurityError("context_item_provenance_invalid")
    if not isinstance(item.get("payload"), Mapping):
        raise ContextSecurityError("context_item_invalid")
    if item.get("trusted_for_instruction") is not False or item.get("authority") != "producer":
        raise ContextSecurityError("context_instruction_boundary_invalid")
    _reject_private_fields(item)


def _reject_private_fields(value: object) -> None:
    if isinstance(value, Mapping):
        if _PRIVATE_FIELDS.intersection(value):
            raise ContextSecurityError("context_private_layout_field")
        for child in value.values():
            _reject_private_fields(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_private_fields(child)


__all__ = [
    "ContextSecurityError",
    "SECURITY_SCHEMA",
    "security_manifest",
    "validate_context_packet",
]
