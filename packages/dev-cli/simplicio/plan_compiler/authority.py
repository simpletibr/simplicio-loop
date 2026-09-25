"""Fail-closed proposal/authorization contract for effect execution.

The model may produce a :class:`ChangeProposal`, but only an external
coordinator may issue :class:`EffectAuthorization`.  The Runtime sink checks
the binding again immediately before transport, so an authorization cannot be
replayed for a different effect, attempt, lease, fence, target, or policy.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, fields
from math import isfinite
from typing import TYPE_CHECKING, Any

from simplicio.plan_compiler.canonical_hash import canonical_hash
from simplicio.plan_compiler.models import IRREVERSIBLE_EFFECT_KINDS, EffectPlan

if TYPE_CHECKING:
    from simplicio.plan_compiler.effect_sink import EffectDispatchContext

PROPOSAL_SCHEMA = "simplicio.change-proposal/v1"
AUTHORIZATION_SCHEMA = "simplicio.effect-authorization/v1"
_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/-]{0,255}$")


class AuthorizationError(ValueError):
    """Raised when an effect proposal or authorization fails closed."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _reference(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise AuthorizationError("AUTHORIZATION_REFERENCE_INVALID", field)
    value = value.strip()
    if not value or not _REFERENCE.fullmatch(value):
        raise AuthorizationError("AUTHORIZATION_REFERENCE_INVALID", field)
    return value


def _finite_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AuthorizationError("AUTHORIZATION_FIELDS_INVALID", field)
    number = float(value)
    if not isfinite(number):
        raise AuthorizationError("AUTHORIZATION_FIELDS_INVALID", field)
    return number


@dataclass(frozen=True)
class ChangeProposal:
    """Deterministic, non-authorizing description of one proposed effect."""

    proposal_id: str
    effect_id: str
    plan_node_id: str
    effect_digest: str
    capability: str
    write_set: tuple[str, ...]
    context_handle: str
    attempt_id: str
    lease_id: str
    fencing_token: str
    source_hash: str
    policy_revision: str
    irreversible: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PROPOSAL_SCHEMA,
            "proposal_id": self.proposal_id,
            "effect_id": self.effect_id,
            "plan_node_id": self.plan_node_id,
            "effect_digest": self.effect_digest,
            "capability": self.capability,
            "write_set": list(self.write_set),
            "context_handle": self.context_handle,
            "attempt_id": self.attempt_id,
            "lease_id": self.lease_id,
            "fencing_token": self.fencing_token,
            "source_hash": self.source_hash,
            "policy_revision": self.policy_revision,
            "irreversible": self.irreversible,
        }

    def digest(self) -> str:
        return canonical_hash(self.to_dict())


def build_change_proposal(effect: EffectPlan, context: EffectDispatchContext) -> ChangeProposal:
    """Build the proposal the sink must authorize for this exact dispatch."""

    for field, value in (
        ("effect_id", effect.effect_id),
        ("plan_node_id", effect.plan_node_id),
        ("capability", effect.authority_required),
        ("coordinator_id", context.coordinator_id),
        ("lease_id", context.lease_id),
        ("fencing_token", context.fencing_token),
        ("context_handle", context.context_handle),
        ("source_hash", context.source_hash),
        ("policy_revision", context.policy_revision),
    ):
        try:
            _reference(value, field=field)
        except AuthorizationError as exc:
            raise AuthorizationError("AUTHORIZATION_CONTEXT_INVALID", field) from exc
    if effect.context_handle != context.context_handle:
        raise AuthorizationError("CONTEXT_HANDLE_MISMATCH", "effect and dispatch context differ")
    effect_digest = canonical_hash(effect.to_dict())
    material = {
        "effect_digest": effect_digest,
        "effect_id": effect.effect_id,
        "plan_node_id": effect.plan_node_id,
        "capability": effect.authority_required,
        "write_set": list(context.plan_node.write_set),
        "context_handle": context.context_handle,
        "attempt_id": context.coordinator_id,
        "lease_id": context.lease_id,
        "fencing_token": context.fencing_token,
        "source_hash": context.source_hash,
        "policy_revision": context.policy_revision,
    }
    proposal_id = f"proposal-{canonical_hash(material)[:24]}"
    return ChangeProposal(
        proposal_id=proposal_id,
        effect_id=effect.effect_id,
        plan_node_id=effect.plan_node_id,
        effect_digest=effect_digest,
        capability=effect.authority_required,
        write_set=tuple(context.plan_node.write_set),
        context_handle=context.context_handle,
        attempt_id=context.coordinator_id,
        lease_id=context.lease_id,
        fencing_token=context.fencing_token,
        source_hash=context.source_hash,
        policy_revision=context.policy_revision,
        irreversible=effect.kind in IRREVERSIBLE_EFFECT_KINDS or context.plan_node.requires_gate,
    )


@dataclass(frozen=True)
class EffectAuthorization:
    """Short-lived authorization bound to one immutable change proposal."""

    proposal_digest: str
    effect_digest: str
    effect_id: str
    plan_node_id: str
    authority: str
    capability: str
    policy_revision: str
    attempt_id: str
    lease_id: str
    fencing_token: str
    context_handle: str
    issuer: str
    issued_at: float
    expires_at: float
    human_gate_receipt: str
    authorization_digest: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EffectAuthorization:
        """Load coordinator-issued JSON without accepting additive ambiguity."""
        if not isinstance(payload, dict) or payload.get("schema") != AUTHORIZATION_SCHEMA:
            raise AuthorizationError("AUTHORIZATION_SCHEMA_INVALID", "effect authorization schema is invalid")
        allowed = {field.name for field in fields(cls)} | {"schema"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise AuthorizationError("AUTHORIZATION_FIELDS_INVALID", ", ".join(unknown))
        required = [field.name for field in fields(cls)]
        missing = [name for name in required if name not in payload]
        if missing:
            raise AuthorizationError("AUTHORIZATION_FIELDS_MISSING", ", ".join(missing))
        string_fields = (
            "proposal_digest",
            "effect_digest",
            "effect_id",
            "plan_node_id",
            "authority",
            "capability",
            "policy_revision",
            "attempt_id",
            "lease_id",
            "fencing_token",
            "context_handle",
            "issuer",
            "human_gate_receipt",
            "authorization_digest",
        )
        invalid_types = [name for name in string_fields if not isinstance(payload[name], str)]
        if invalid_types:
            raise AuthorizationError("AUTHORIZATION_FIELDS_INVALID", ", ".join(invalid_types))
        try:
            return cls(
                **{name: payload[name] for name in string_fields},
                issued_at=_finite_number(payload["issued_at"], field="issued_at"),
                expires_at=_finite_number(payload["expires_at"], field="expires_at"),
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise AuthorizationError(
                "AUTHORIZATION_FIELDS_INVALID", "effect authorization fields are invalid"
            ) from exc

    @classmethod
    def issue(
        cls,
        proposal: ChangeProposal,
        *,
        authority: str,
        issuer: str,
        human_gate_receipt: str = "",
        now: float | None = None,
        ttl_s: float = 60.0,
    ) -> EffectAuthorization:
        ttl = _finite_number(ttl_s, field="ttl_s")
        if ttl <= 0:
            raise AuthorizationError("AUTHORIZATION_TTL_INVALID", "ttl_s must be positive")
        authority = _reference(authority, field="authority")
        issuer = _reference(issuer, field="issuer")
        if issuer.lower() in {"llm", "model", "assistant", "language-model"}:
            raise AuthorizationError("LLM_CANNOT_AUTHORIZE", "authorization issuer must be a coordinator")
        if proposal.irreversible:
            human_gate_receipt = _reference(human_gate_receipt, field="human_gate_receipt")
        elif human_gate_receipt:
            human_gate_receipt = _reference(human_gate_receipt, field="human_gate_receipt")
        issued_at = time.time() if now is None else _finite_number(now, field="issued_at")
        authorization = cls(
            proposal_digest=proposal.digest(),
            effect_digest=proposal.effect_digest,
            effect_id=proposal.effect_id,
            plan_node_id=proposal.plan_node_id,
            authority=authority,
            capability=proposal.capability,
            policy_revision=proposal.policy_revision,
            attempt_id=proposal.attempt_id,
            lease_id=proposal.lease_id,
            fencing_token=proposal.fencing_token,
            context_handle=proposal.context_handle,
            issuer=issuer,
            issued_at=issued_at,
            expires_at=issued_at + ttl,
            human_gate_receipt=human_gate_receipt,
        )
        return cls(**{**authorization.__dict__, "authorization_digest": authorization.digest()})

    def _unsigned(self) -> dict[str, Any]:
        return {
            "schema": AUTHORIZATION_SCHEMA,
            "proposal_digest": self.proposal_digest,
            "effect_digest": self.effect_digest,
            "effect_id": self.effect_id,
            "plan_node_id": self.plan_node_id,
            "authority": self.authority,
            "capability": self.capability,
            "policy_revision": self.policy_revision,
            "attempt_id": self.attempt_id,
            "lease_id": self.lease_id,
            "fencing_token": self.fencing_token,
            "context_handle": self.context_handle,
            "issuer": self.issuer,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "human_gate_receipt": self.human_gate_receipt,
        }

    def digest(self) -> str:
        return canonical_hash(self._unsigned())

    def to_dict(self) -> dict[str, Any]:
        return {**self._unsigned(), "authorization_digest": self.authorization_digest}

    def verify(self, proposal: ChangeProposal, *, now: float | None = None) -> None:
        if self.proposal_digest != proposal.digest():
            raise AuthorizationError("AUTHORIZATION_PROPOSAL_MISMATCH", "proposal digest differs")
        for field in (
            "effect_digest",
            "effect_id",
            "plan_node_id",
            "capability",
            "policy_revision",
            "attempt_id",
            "lease_id",
            "fencing_token",
            "context_handle",
        ):
            if getattr(self, field) != getattr(proposal, field):
                raise AuthorizationError("AUTHORIZATION_BINDING_MISMATCH", field)
        for field in (
            "proposal_digest",
            "effect_digest",
            "effect_id",
            "plan_node_id",
            "authority",
            "capability",
            "policy_revision",
            "attempt_id",
            "lease_id",
            "fencing_token",
            "context_handle",
            "issuer",
            "authorization_digest",
        ):
            _reference(getattr(self, field), field=field)
        _finite_number(self.issued_at, field="issued_at")
        _finite_number(self.expires_at, field="expires_at")
        _reference(self.authority, field="authority")
        issuer = _reference(self.issuer, field="issuer")
        if issuer.lower() in {"llm", "model", "assistant", "language-model"}:
            raise AuthorizationError("LLM_CANNOT_AUTHORIZE", "authorization issuer must be a coordinator")
        if self.expires_at <= self.issued_at:
            raise AuthorizationError("AUTHORIZATION_WINDOW_INVALID", "expiry must follow issue time")
        current = time.time() if now is None else _finite_number(now, field="now")
        if current < self.issued_at or current >= self.expires_at:
            raise AuthorizationError("AUTHORIZATION_EXPIRED", "authorization is outside its validity window")
        if proposal.irreversible:
            _reference(self.human_gate_receipt, field="human_gate_receipt")
        if self.authorization_digest != self.digest():
            raise AuthorizationError(
                "AUTHORIZATION_DIGEST_INVALID", "authorization content does not match digest"
            )


__all__ = [
    "AUTHORIZATION_SCHEMA",
    "AuthorizationError",
    "ChangeProposal",
    "EffectAuthorization",
    "PROPOSAL_SCHEMA",
    "build_change_proposal",
]
