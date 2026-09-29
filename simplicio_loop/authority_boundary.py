"""Coordinator-only effect-authorization boundary.

The Loop may carry a model proposal through planning, but it must never treat
that proposal (or text found in Mapper output) as permission to mutate.  The
only authorization source accepted here is the coordinator-owned
``effect-authorization.json`` artifact.  The Dev CLI/Runtime still performs
the final effect-specific binding; this module is the earlier fail-closed
handoff gate.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

AUTHORIZATION_SCHEMA = "simplicio.effect-authorization/v1"
AUTHORIZATION_FILENAME = "effect-authorization.json"
_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/-]{0,255}$")
_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = (
    "proposal_digest", "effect_digest", "effect_id", "plan_node_id", "authority",
    "capability", "policy_revision", "attempt_id", "lease_id", "fencing_token",
    "context_handle", "issuer", "issued_at", "expires_at", "human_gate_receipt",
    "authorization_digest",
)
_ALLOWED_FIELDS = frozenset(_FIELDS) | {"schema"}
_LLM_ISSUERS = frozenset({"llm", "model", "assistant", "language-model"})


class AuthorityBoundaryError(ValueError):
    """Raised when a coordinator authorization cannot be trusted."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def canonical_hash(payload: Any) -> str:
    """Match the Dev CLI canonical JSON hash exactly."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _text(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if name == "human_gate_receipt" and value == "":
        return ""
    if not isinstance(value, str) or not value.strip() or not _REFERENCE.fullmatch(value.strip()):
        raise AuthorityBoundaryError("AUTHORIZATION_FIELD_INVALID", name)
    return value.strip()


def _unsigned(payload: Mapping[str, Any]) -> Dict[str, Any]:
    return {"schema": AUTHORIZATION_SCHEMA, **{
        key: payload[key] for key in _FIELDS if key != "authorization_digest"
    }}


def validate_effect_authorization(
    payload: Mapping[str, Any], *, now: Optional[float] = None,
    expected: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Validate a coordinator-issued authorization without importing the Dev CLI.

    ``expected`` is deliberately limited to causal fields known by the Loop.
    Effect/plan digests remain bound by the Dev CLI Runtime sink immediately
    before transport, so this gate cannot accidentally replace that check.
    """
    if not isinstance(payload, Mapping) or payload.get("schema") != AUTHORIZATION_SCHEMA:
        raise AuthorityBoundaryError("AUTHORIZATION_SCHEMA_INVALID", "schema mismatch")
    unknown = sorted(set(payload) - _ALLOWED_FIELDS)
    if unknown:
        raise AuthorityBoundaryError("AUTHORIZATION_FIELDS_INVALID", ", ".join(unknown))
    missing = [name for name in _FIELDS if name not in payload]
    if missing:
        raise AuthorityBoundaryError("AUTHORIZATION_FIELDS_MISSING", ", ".join(missing))

    for name in _FIELDS:
        if name in {"issued_at", "expires_at"}:
            continue
        _text(payload, name)
    for name in ("proposal_digest", "effect_digest", "authorization_digest"):
        if not _HEX_DIGEST.fullmatch(str(payload[name])):
            raise AuthorityBoundaryError("AUTHORIZATION_DIGEST_INVALID", name)
    issuer = str(payload["issuer"]).lower()
    if issuer in _LLM_ISSUERS:
        raise AuthorityBoundaryError("LLM_CANNOT_AUTHORIZE", "model output is not authority")
    try:
        issued_at = float(payload["issued_at"])
        expires_at = float(payload["expires_at"])
    except (TypeError, ValueError, OverflowError) as exc:
        raise AuthorityBoundaryError("AUTHORIZATION_FIELDS_INVALID", "timestamps") from exc
    if expires_at <= issued_at:
        raise AuthorityBoundaryError("AUTHORIZATION_WINDOW_INVALID", "expiry must follow issue time")
    current = time.time() if now is None else float(now)
    if current < issued_at or current >= expires_at:
        raise AuthorityBoundaryError("AUTHORIZATION_EXPIRED", "authorization is outside its validity window")
    if str(payload["authorization_digest"]) != canonical_hash(_unsigned(payload)):
        raise AuthorityBoundaryError("AUTHORIZATION_DIGEST_INVALID", "content does not match digest")

    for name, expected_value in (expected or {}).items():
        if expected_value and str(payload.get(name, "")) != str(expected_value):
            raise AuthorityBoundaryError("AUTHORIZATION_BINDING_MISMATCH", name)
    return {
        "schema": AUTHORIZATION_SCHEMA,
        "authorization_digest": str(payload["authorization_digest"]),
        "issuer": str(payload["issuer"]),
        "authority": str(payload["authority"]),
        "expires_at": expires_at,
    }


def prepare_authorization_handoff(
    run_root: str | Path, *, required: bool = False, now: Optional[float] = None,
) -> Tuple[Sequence[str], Dict[str, Any]]:
    """Load only the coordinator-owned run artifact and prepare CLI argv.

    Mapper/LLM payloads are intentionally not inspected for an authorization
    path.  A missing artifact is a typed absence; callers may make it a hard
    block with ``required=True``.
    """
    root = Path(run_root).resolve()
    path = root / AUTHORIZATION_FILENAME
    if not path.exists():
        if required:
            raise AuthorityBoundaryError("EFFECT_AUTHORIZATION_REQUIRED", "coordinator artifact is missing")
        return [], {"status": "not_provided", "reason_code": "EFFECT_AUTHORIZATION_UNAVAILABLE"}
    resolved_path = path.resolve()
    if path.is_symlink() or resolved_path.parent != root or not resolved_path.is_file():
        raise AuthorityBoundaryError("AUTHORIZATION_PATH_INVALID", "coordinator artifact escapes the run root")
    try:
        payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuthorityBoundaryError("AUTHORIZATION_UNREADABLE", "coordinator artifact is invalid") from exc
    summary = validate_effect_authorization(payload, now=now)
    return ["--effect-authorization", str(resolved_path)], {
        "status": "propagated",
        "source": "coordinator-artifact",
        "authorization_digest": summary["authorization_digest"],
        "issuer": summary["issuer"],
        "expires_at": summary["expires_at"],
    }


__all__ = [
    "AUTHORIZATION_FILENAME", "AUTHORIZATION_SCHEMA", "AuthorityBoundaryError",
    "canonical_hash", "prepare_authorization_handoff", "validate_effect_authorization",
]
