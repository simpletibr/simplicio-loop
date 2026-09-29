"""Receipt content/schema/hash/freshness/provenance validation (issue #288).

Today ``receipt_status`` becomes ``VERIFIED`` in ``simplicio_loop/runner.py`` the moment
two files exist on disk (``Path(receipt).is_file() and Path(evidence_receipt).is_file()``)
-- no schema check, no tamper detection, no staleness check, no provenance check. That is
exactly the gap issue #288 calls out: "receipt_status vira VERIFIED quando dois arquivos
existem; conteudo, schema, freshness, commit, fence e hashes nao sao necessariamente
comprovados nesse ponto."

``verify_receipt()`` is a real, reusable validator that closes that gap for one class of
receipt at a time. It is deliberately shaped around the receipts this codebase already
produces -- ``simplicio_loop/evidence.py::build_evidence_receipt`` and
``simplicio_loop/runner.py::_prepare_operator_receipt`` -- rather than inventing a parallel
schema disconnected from reality. It does not implement the full ``ProductionPipeline``
saga described in the epic (attempt coordinator, merge queue, restart/recovery, etc.);
those remain open.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

_MISSING = object()


class ReceiptStatus:
    """Verdict statuses more specific than a single existence boolean."""

    VERIFIED = "VERIFIED"
    STALE = "STALE"
    TAMPERED = "TAMPERED"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    MISSING_FIELD = "MISSING_FIELD"


ALL_STATUSES = (
    ReceiptStatus.VERIFIED,
    ReceiptStatus.STALE,
    ReceiptStatus.TAMPERED,
    ReceiptStatus.INVALID_SCHEMA,
    ReceiptStatus.MISSING_FIELD,
)


@dataclass(frozen=True)
class ReceiptVerdict:
    """Structured verification result -- never a bare true/false."""

    status: str
    reason: str
    checked_at: float

    @property
    def verified(self) -> bool:
        return self.status == ReceiptStatus.VERIFIED

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "verified": self.verified,
            "reason": self.reason,
            "checked_at": self.checked_at,
        }


@dataclass(frozen=True)
class ReceiptSchema:
    """Declares what "valid content" means for one receipt kind.

    ``required_fields``: dotted paths (e.g. ``"run.commit_sha"``) that must be present
        (may be present-but-empty; use ``provenance_fields`` to also require non-empty).
    ``required_values``: dotted path -> exact expected value (e.g. the schema id literal).
    ``provenance_fields``: dotted paths that must resolve to a non-empty value --
        identity/attempt/fence-like fields that prove *who* produced the receipt and
        *for what attempt*, not merely that a JSON blob exists on disk.
    ``content_fields``: dotted paths hashed to build the canonical content hash used for
        tamper detection. ``None`` hashes every top-level field except the hash/freshness
        bookkeeping fields themselves.
    ``freshness_field``: dotted path to the receipt's own timestamp, used for staleness.
    ``hash_field``: dotted path where the receipt may carry its own declared content hash
        (e.g. ``receipt_sha`` or ``hash``), used when no external ``expected_hash`` is given.
    """

    name: str
    required_fields: Sequence[str] = ()
    provenance_fields: Sequence[str] = ()
    required_values: Mapping[str, Any] = field(default_factory=dict)
    content_fields: Sequence[str] | None = None
    freshness_field: str = "measured_at"
    hash_field: str = "receipt_sha"


def _get_path(data: Mapping[str, Any], path: str) -> Any:
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return _MISSING
        node = node[part]
    return node


def _parse_timestamp(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        candidate = value.strip()
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            dt = datetime.datetime.fromisoformat(candidate)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    return None


def canonical_content_hash(receipt: Mapping[str, Any], content_fields: Sequence[str] | None = None) -> str:
    """Recompute a stable sha256 over the receipt's declared content fields.

    Mirrors ``evidence.py::_stable_hash`` (sorted-key, separator-compact JSON) so the same
    logical content always hashes the same value regardless of key order, and so tampering
    with any hashed field is detectable by comparison against a declared/expected hash.
    """
    if content_fields:
        payload: dict[str, Any] = {}
        for path in content_fields:
            value = _get_path(receipt, path)
            if value is not _MISSING:
                payload[path] = value
    else:
        payload = {k: v for k, v in receipt.items() if k not in {"receipt_sha", "hash"}}
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def verify_receipt(
    receipt: Mapping[str, Any],
    *,
    schema: ReceiptSchema | None = None,
    expected_hash: str | None = None,
    max_age_seconds: float | None = None,
    now: float | None = None,
) -> ReceiptVerdict:
    """Validate one receipt against schema/hash/freshness/provenance -- not just presence.

    Returns a :class:`ReceiptVerdict` with a status drawn from :class:`ReceiptStatus`.
    Only ``VERIFIED`` should ever be treated as "safe to mark done"; every other status is
    an explicit, actionable reason it is not.
    """
    checked_at = time.time() if now is None else float(now)
    if not isinstance(receipt, Mapping) or not receipt:
        return ReceiptVerdict(ReceiptStatus.MISSING_FIELD, "receipt is empty or not an object", checked_at)

    schema = schema or ReceiptSchema(name="generic")

    # 1. structural/content schema validation ------------------------------------
    missing = [path for path in schema.required_fields if _get_path(receipt, path) is _MISSING]
    if missing:
        return ReceiptVerdict(
            ReceiptStatus.MISSING_FIELD,
            f"missing required field(s): {', '.join(missing)}",
            checked_at,
        )
    for path, expected_value in (schema.required_values or {}).items():
        actual = _get_path(receipt, path)
        if actual != expected_value:
            return ReceiptVerdict(
                ReceiptStatus.INVALID_SCHEMA,
                f"field {path!r} expected {expected_value!r}, got {actual!r}",
                checked_at,
            )
    empty_provenance = [
        path for path in schema.provenance_fields
        if _get_path(receipt, path) in (_MISSING, None, "", [], {})
    ]
    if empty_provenance:
        return ReceiptVerdict(
            ReceiptStatus.MISSING_FIELD,
            f"missing/empty provenance field(s): {', '.join(empty_provenance)}",
            checked_at,
        )

    # 2. content hash / tamper validation -----------------------------------------
    declared_hash = expected_hash
    if declared_hash is None:
        declared = _get_path(receipt, schema.hash_field)
        declared_hash = declared if declared not in (_MISSING, None, "") else None
    if declared_hash:
        recomputed = canonical_content_hash(receipt, schema.content_fields)
        if recomputed != declared_hash:
            return ReceiptVerdict(
                ReceiptStatus.TAMPERED,
                f"content hash mismatch: declared {declared_hash}, recomputed {recomputed}",
                checked_at,
            )

    # 3. freshness ------------------------------------------------------------------
    if max_age_seconds is not None:
        raw_ts = _get_path(receipt, schema.freshness_field)
        if raw_ts is _MISSING:
            return ReceiptVerdict(
                ReceiptStatus.MISSING_FIELD,
                f"missing freshness field: {schema.freshness_field}",
                checked_at,
            )
        ts = _parse_timestamp(raw_ts)
        if ts is None:
            return ReceiptVerdict(
                ReceiptStatus.INVALID_SCHEMA,
                f"unparseable timestamp in {schema.freshness_field}: {raw_ts!r}",
                checked_at,
            )
        age = checked_at - ts
        if age > max_age_seconds:
            return ReceiptVerdict(
                ReceiptStatus.STALE,
                f"receipt age {age:.1f}s exceeds max_age_seconds {max_age_seconds:.1f}s",
                checked_at,
            )
        if age < -60:  # small clock-skew allowance; a receipt claiming to be from the future is suspect
            return ReceiptVerdict(
                ReceiptStatus.TAMPERED,
                f"receipt timestamp is {(-age):.1f}s in the future",
                checked_at,
            )

    return ReceiptVerdict(
        ReceiptStatus.VERIFIED,
        "schema, hash, freshness and provenance checks passed",
        checked_at,
    )


# ---------------------------------------------------------------------------
# Concrete schemas for the receipts this codebase actually produces.
# ---------------------------------------------------------------------------

OPERATOR_RECEIPT_SCHEMA = ReceiptSchema(
    name="operator-receipt",
    required_fields=("schema", "execution_state", "target", "measured_at", "source"),
    required_values={"schema": "simplicio.operator-receipt/v0"},
    provenance_fields=("tool", "target", "source", "repo_state_before"),
    freshness_field="measured_at",
    hash_field="receipt_sha",
)

EVIDENCE_RECEIPT_SCHEMA = ReceiptSchema(
    name="evidence-receipt",
    required_fields=("schema", "run_id", "status", "measured_at", "run.commit_sha", "operator.execution_state"),
    required_values={"schema": "simplicio.evidence-receipt/v1"},
    provenance_fields=("run_id", "run.commit_sha", "operator.receipt_path"),
    freshness_field="measured_at",
    hash_field="receipt_sha",
)


__all__ = [
    "ReceiptStatus",
    "ALL_STATUSES",
    "ReceiptVerdict",
    "ReceiptSchema",
    "canonical_content_hash",
    "verify_receipt",
    "OPERATOR_RECEIPT_SCHEMA",
    "EVIDENCE_RECEIPT_SCHEMA",
]
