"""Minimal HBP-style binary codec for Prism contracts.

JSON remains available only at the external boundary (CLI/API/export).
Internal encode/decode is binary, content-addressed, and deterministic.
"""

from __future__ import annotations

import hashlib
import json
import struct
from typing import Any, Mapping

from .prism_task_facts import TASK_FACTS_SCHEMA, PrismFactsError, validate_prism_task_facts
from .prism_work_delta import WORK_DELTA_SCHEMA, validate_prism_work_delta

MAGIC = b"HBP1"
# schema_id -> version
_SCHEMA_IDS = {
    TASK_FACTS_SCHEMA: 1,
    WORK_DELTA_SCHEMA: 2,
}
_ID_TO_SCHEMA = {value: key for key, value in _SCHEMA_IDS.items()}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def content_hash(payload: bytes) -> bytes:
    return hashlib.sha256(payload).digest()


def encode_hbp(document: Mapping[str, Any]) -> bytes:
    schema = document.get("schema")
    if schema not in _SCHEMA_IDS:
        raise PrismFactsError("hbp_schema_unsupported", str(schema))
    if schema == TASK_FACTS_SCHEMA:
        document = validate_prism_task_facts(document)
    elif schema == WORK_DELTA_SCHEMA:
        document = validate_prism_work_delta(document)
    body = canonical_json(document)
    if len(body) > 16 * 1024 * 1024:
        raise PrismFactsError("hbp_payload_too_large", str(len(body)))
    schema_id = _SCHEMA_IDS[schema]
    header = struct.pack(
        ">4sHHI32s",
        MAGIC,
        schema_id,
        1,  # codec version
        len(body),
        content_hash(body),
    )
    return header + body


def decode_hbp(blob: bytes) -> dict[str, Any]:
    if len(blob) < 4 + 2 + 2 + 4 + 32:
        raise PrismFactsError("hbp_truncated", str(len(blob)))
    magic, schema_id, codec_ver, length, digest = struct.unpack(">4sHHI32s", blob[:44])
    if magic != MAGIC:
        raise PrismFactsError("hbp_magic_invalid", magic.decode("latin1", errors="replace"))
    if codec_ver != 1:
        raise PrismFactsError("hbp_version_unsupported", str(codec_ver))
    if schema_id not in _ID_TO_SCHEMA:
        raise PrismFactsError("hbp_schema_id_unknown", str(schema_id))
    body = blob[44:]
    if len(body) != length:
        raise PrismFactsError("hbp_length_mismatch", f"{len(body)}!={length}")
    if content_hash(body) != digest:
        raise PrismFactsError("hbp_tamper_detected", digest.hex())
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrismFactsError("hbp_body_invalid", str(exc)) from exc
    schema = _ID_TO_SCHEMA[schema_id]
    if document.get("schema") != schema:
        raise PrismFactsError("hbp_schema_drift", str(document.get("schema")))
    if schema == TASK_FACTS_SCHEMA:
        return validate_prism_task_facts(document)
    return validate_prism_work_delta(document)


def to_external_json(document: Mapping[str, Any]) -> str:
    """External boundary only — pretty JSON is never the internal identity."""
    schema = document.get("schema")
    if schema == TASK_FACTS_SCHEMA:
        document = validate_prism_task_facts(document)
    elif schema == WORK_DELTA_SCHEMA:
        document = validate_prism_work_delta(document)
    else:
        raise PrismFactsError("hbp_schema_unsupported", str(schema))
    return json.dumps(document, sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def from_external_json(text: str) -> dict[str, Any]:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PrismFactsError("external_json_invalid", str(exc)) from exc
    schema = document.get("schema")
    if schema == TASK_FACTS_SCHEMA:
        return validate_prism_task_facts(document)
    if schema == WORK_DELTA_SCHEMA:
        return validate_prism_work_delta(document)
    raise PrismFactsError("hbp_schema_unsupported", str(schema))


def negotiate_capability(requested: Mapping[str, Any] | None = None) -> dict[str, Any]:
    req = requested or {}
    return {
        "schema": "simplicio.hbp-capability/v1",
        "magic": MAGIC.decode("ascii"),
        "codec_version": 1,
        "schemas": sorted(_SCHEMA_IDS),
        "accepted": True,
        "requested": dict(req),
    }


__all__ = [
    "MAGIC",
    "canonical_json",
    "content_hash",
    "decode_hbp",
    "encode_hbp",
    "from_external_json",
    "negotiate_capability",
    "to_external_json",
]
