"""Causal HBP receipts for Prism tasks (#380, #369)."""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping
from typing import Any

from simplicio.hbp import HBP_MAGIC, row_content_hash
from simplicio.plan_compiler.canonical_hash import canonical_hash
from simplicio.prism_envelope import PrismExecutionEnvelope


def _redact_obj(value: Any) -> Any:
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            low = str(key).casefold()
            if any(token in low for token in ("token", "password", "secret", "authorization", "api_key")):
                out[key] = "[REDACTED]"
            else:
                out[key] = _redact_obj(item)
        return out
    if isinstance(value, list):
        return [_redact_obj(item) for item in value]
    if isinstance(value, str):
        for marker in ("ghp_", "gho_", "AKIA", "xoxb-"):
            if marker in value:
                return "[REDACTED]"
        return value
    return value


def build_effect_receipt(
    envelope: PrismExecutionEnvelope,
    *,
    status: str,
    before_hash: str | None,
    after_hash: str | None,
    checkpoint_hash: str | None,
    transitions: list[str],
    commands: list[Mapping[str, Any]] | None = None,
    previous_receipt_hash: str | None = None,
    metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = dict(metrics or {})
    for key in ("cpu_ms", "rss_bytes", "io_bytes", "wall_ms"):
        metrics.setdefault(key, None)
        if metrics[key] is None:
            metrics.setdefault(f"{key}_null_reason", "NOT_MEASURED")
    body = {
        "schema": "simplicio.prism-effect-receipt/v1",
        "envelope_hash": envelope.envelope_hash(),
        "goal_id": envelope.goal_id,
        "prism_id": envelope.prism_id,
        "parent_prism_id": envelope.parent_prism_id,
        "slot_id": envelope.slot_id,
        "task_id": envelope.task_id,
        "owner_agent_id": envelope.owner_agent_id,
        "attempt_id": envelope.attempt_id,
        "base_commit": envelope.base_commit,
        "context_graph_digest": envelope.context_graph_digest,
        "task_facts_digest": envelope.task_facts_digest,
        "change_set_hash": envelope.change_set_hash,
        "verification_plan_hash": envelope.verification_plan_hash,
        "lease_id": envelope.lease_id,
        "fence_token": envelope.fence_token,
        "authority_hash": envelope.authority_hash,
        "before_hash": before_hash,
        "after_hash": after_hash,
        "checkpoint_hash": checkpoint_hash,
        "transitions": transitions,
        "commands": list(commands or ()),
        "status": status,
        "metrics": metrics,
        "previous_receipt_hash": previous_receipt_hash,
        "producer": "simplicio-cli",
        "trace_id": envelope.trace_id,
    }
    body = _redact_obj(body)
    body["receipt_hash"] = canonical_hash(body)
    return body


def encode_receipt_hbp(receipt: Mapping[str, Any], *, seq: int = 1, prev_hash: str = "genesis") -> bytes:
    """Encode a receipt row with Runtime-compatible HBP1 framing."""
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    provenance = json.dumps(
        {
            "schema": receipt.get("schema"),
            "envelope_hash": receipt.get("envelope_hash"),
            "receipt_hash": receipt.get("receipt_hash"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    topic = "prism.effect_receipt"
    digest = row_content_hash(seq, prev_hash, topic, payload, provenance, None)
    body = bytearray()
    body.extend(struct.pack("<Q", seq))
    for field in (prev_hash, topic, payload, provenance, ""):
        encoded = field.encode("utf-8")
        body.extend(struct.pack("<I", len(encoded)))
        body.extend(encoded)
    body.extend(bytes.fromhex(digest))
    header = HBP_MAGIC + struct.pack("<HHI", 1, 0, len(body))
    return header + body


def verify_receipt_offline(receipt: Mapping[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in receipt.items() if key != "receipt_hash"}
    expected = canonical_hash(body)
    ok = expected == receipt.get("receipt_hash")
    return {
        "schema": "simplicio.receipt-verify/v1",
        "status": "valid" if ok else "tampered",
        "expected_hash": expected,
        "provided_hash": receipt.get("receipt_hash"),
    }


def llm_projection(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Short projection for Loop prompts — no secrets, hash-linked."""
    return {
        "schema": "simplicio.receipt-projection/v1",
        "task_id": receipt.get("task_id"),
        "status": receipt.get("status"),
        "receipt_hash": receipt.get("receipt_hash"),
        "envelope_hash": receipt.get("envelope_hash"),
        "transitions": receipt.get("transitions"),
        "after_hash": receipt.get("after_hash"),
    }
