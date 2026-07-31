"""Authorized Git/GitHub delivery effects with observed re-query (#367)."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from simplicio.plan_compiler.canonical_hash import canonical_hash

DELIVERY_AUTH_SCHEMA = "simplicio.delivery-authorization/v1"
DELIVERY_RECEIPT_SCHEMA = "simplicio.delivery-receipt/v1"
_EFFECTS = frozenset({"commit", "push", "open_pr", "merge", "close_issue", "comment"})


class DeliveryError(RuntimeError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


@dataclass(frozen=True)
class DeliveryAuthorization:
    authorization_id: str
    repo: str
    branch: str
    base: str
    actor: str
    permitted_effects: tuple[str, ...]
    idempotency_key: str
    expires_at_ns: int
    extensions: dict[str, Any] = field(default_factory=dict)

    def validate(self, *, now_ns: int | None = None) -> None:
        now = time.time_ns() if now_ns is None else now_ns
        if not self.authorization_id or not self.repo or not self.branch or not self.actor:
            raise DeliveryError("AUTH_INCOMPLETE")
        if not self.idempotency_key:
            raise DeliveryError("IDEMPOTENCY_REQUIRED")
        if self.expires_at_ns <= now:
            raise DeliveryError("AUTH_EXPIRED")
        unknown = set(self.permitted_effects) - _EFFECTS
        if unknown:
            raise DeliveryError("UNKNOWN_EFFECT", ",".join(sorted(unknown)))
        if not self.permitted_effects:
            raise DeliveryError("NO_PERMITTED_EFFECTS")

    def allows(self, effect: str) -> bool:
        return effect in self.permitted_effects

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": DELIVERY_AUTH_SCHEMA,
            "authorization_id": self.authorization_id,
            "repo": self.repo,
            "branch": self.branch,
            "base": self.base,
            "actor": self.actor,
            "permitted_effects": list(self.permitted_effects),
            "idempotency_key": self.idempotency_key,
            "expires_at_ns": self.expires_at_ns,
        }
        payload.update(self.extensions)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> DeliveryAuthorization:
        if payload.get("schema") != DELIVERY_AUTH_SCHEMA:
            raise DeliveryError("SCHEMA_INVALID", str(payload.get("schema")))
        return cls(
            authorization_id=str(payload.get("authorization_id", "")),
            repo=str(payload.get("repo", "")),
            branch=str(payload.get("branch", "")),
            base=str(payload.get("base", "")),
            actor=str(payload.get("actor", "")),
            permitted_effects=tuple(payload.get("permitted_effects", ())),
            idempotency_key=str(payload.get("idempotency_key", "")),
            expires_at_ns=int(payload.get("expires_at_ns", 0)),
            extensions={
                key: value
                for key, value in payload.items()
                if key
                not in {
                    "schema",
                    "authorization_id",
                    "repo",
                    "branch",
                    "base",
                    "actor",
                    "permitted_effects",
                    "idempotency_key",
                    "expires_at_ns",
                }
            },
        )


class DeliveryExecutor:
    """Apply permitted effects with local idempotency and observed re-query."""

    def __init__(self) -> None:
        self._seen: dict[str, dict[str, Any]] = {}

    def execute(
        self,
        authorization: DeliveryAuthorization,
        effect: str,
        *,
        apply: Callable[[], Mapping[str, Any]],
        observe: Callable[[], Mapping[str, Any]],
        now_ns: int | None = None,
    ) -> dict[str, Any]:
        authorization.validate(now_ns=now_ns)
        if effect not in _EFFECTS:
            raise DeliveryError("UNKNOWN_EFFECT", effect)
        if not authorization.allows(effect):
            raise DeliveryError("EFFECT_NOT_AUTHORIZED", effect)
        key = f"{authorization.idempotency_key}:{effect}"
        if key in self._seen:
            return dict(self._seen[key])
        requested = {"effect": effect, "status": "requested"}
        try:
            applied = dict(apply())
        except TimeoutError as exc:
            observed = dict(observe())
            receipt = self._receipt(
                authorization,
                effect,
                requested=requested,
                observed=observed,
                status="reconciliation_required",
                reason_code="TIMEOUT_AFTER_REQUEST",
            )
            self._seen[key] = receipt
            raise DeliveryError("TIMEOUT_AFTER_REQUEST") from exc
        observed = dict(observe())
        receipt = self._receipt(
            authorization,
            effect,
            requested={**requested, **applied},
            observed=observed,
            status="completed",
            reason_code=None,
        )
        self._seen[key] = receipt
        return receipt

    def _receipt(
        self,
        authorization: DeliveryAuthorization,
        effect: str,
        *,
        requested: Mapping[str, Any],
        observed: Mapping[str, Any],
        status: str,
        reason_code: str | None,
    ) -> dict[str, Any]:
        body = {
            "schema": DELIVERY_RECEIPT_SCHEMA,
            "authorization_id": authorization.authorization_id,
            "idempotency_key": authorization.idempotency_key,
            "effect": effect,
            "repo": authorization.repo,
            "branch": authorization.branch,
            "actor": authorization.actor,
            "requested": dict(requested),
            "observed": dict(observed),
            "status": status,
            "reason_code": reason_code,
            # never embed secrets
            "redacted_fields": ["token", "password", "authorization"],
        }
        body["receipt_hash"] = canonical_hash(body)
        return body
