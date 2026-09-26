"""Standalone effect boundary (#695).

There is no Runtime/MCP backend in this stack: every effect is dispatched
locally and every receipt records ``executor: "standalone"``. This module
keeps the transaction/receipt shape (idempotency, leases, fencing) that the
loop's own hookwall dispatch relies on -- that bookkeeping is not a Runtime
concept, only the (removed) remote-dispatch branch was.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .canonical_plan import CanonicalPlan, canonical_plan_metadata

SCHEMA = "simplicio.runtime-effect-adapter/v1"
PROFILES = frozenset(("standalone",))
TRANSACTION_SCHEMA = "simplicio.effect-transaction/v1"
UNAVAILABLE = "UNAVAILABLE"
STANDALONE = "STANDALONE"
_EXPLICIT_TOOLS = {
    "map": "simplicio_map",
    "read": "simplicio_read",
    "edit": "simplicio_edit",
    "validate": "simplicio_validate",
    "checkpoint": "simplicio_checkpoint",
    "evidence": "simplicio_evidence",
}


class RuntimeEffectError(RuntimeError):
    """An effect was malformed, unauthorized or unavailable."""


@dataclass(frozen=True)
class EffectRequest:
    workspace: str
    idempotency_key: str
    write_set: tuple[str, ...]
    lease_id: str
    fencing_token: int | str
    cwd: str = "."
    timeout_ms: int = 120_000
    attempt: int = 1
    deadline: Optional[Any] = None
    cancellation_boundary: str = "safe_boundary_only"
    gate_id: Optional[str] = None
    runtime_generation: Optional[str] = None
    transaction_id: Optional[str] = None
    authorization_digest: Optional[str] = None
    canonical_plan: Optional[CanonicalPlan] = None
    attempt_id: Optional[str] = None

    def __post_init__(self) -> None:
        if (
            not self.workspace
            or not self.idempotency_key
            or not self.write_set
            or not self.lease_id
            or (
                isinstance(self.fencing_token, int)
                and (isinstance(self.fencing_token, bool) or self.fencing_token < 1)
            )
            or (isinstance(self.fencing_token, str) and not self.fencing_token.strip())
            or not isinstance(self.fencing_token, (int, str))
        ):
            raise RuntimeEffectError("workspace, idempotency, write set and lease/fence are required")
        if any(not isinstance(item, str) or not item.strip() for item in self.write_set):
            raise RuntimeEffectError("write_set must contain non-empty strings")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 1:
            raise RuntimeEffectError("attempt must be a positive integer")
        if self.deadline is not None:
            if isinstance(self.deadline, bool) or not isinstance(self.deadline, (int, float, str)):
                raise RuntimeEffectError("deadline must be a non-empty string or positive number")
            if isinstance(self.deadline, str) and not self.deadline.strip():
                raise RuntimeEffectError("deadline must be a non-empty string or positive number")
            if isinstance(self.deadline, (int, float)) and self.deadline <= 0:
                raise RuntimeEffectError("deadline must be a non-empty string or positive number")
        if not isinstance(self.cancellation_boundary, str) or not self.cancellation_boundary.strip():
            raise RuntimeEffectError("cancellation_boundary must be a non-empty string")
        for name in ("gate_id", "runtime_generation", "transaction_id", "authorization_digest"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise RuntimeEffectError(f"{name} must be a non-empty string when supplied")
        if self.authorization_digest is not None:
            digest = self.authorization_digest.removeprefix("sha256:")
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise RuntimeEffectError("authorization_digest must be a sha256 digest")
        if self.canonical_plan is not None and not isinstance(self.canonical_plan, CanonicalPlan):
            raise RuntimeEffectError("canonical_plan must be a validated CanonicalPlan")
        if Path(self.cwd).is_absolute() or ".." in Path(self.cwd).parts:
            raise RuntimeEffectError("effect cwd must stay workspace-relative")


class RuntimeEffectAdapter:
    """One authoritative effect adapter. Always standalone."""

    def __init__(self, *, profile: str = "standalone") -> None:
        if profile not in PROFILES:
            raise RuntimeEffectError("unsupported execution profile")
        self.profile = profile
        self._latency_ms: list[float] = []

    def _metrics(self, result: Mapping[str, Any]) -> Dict[str, Any]:
        samples = sorted(self._latency_ms)
        p50 = samples[len(samples) // 2] if samples else None
        p95 = samples[min(len(samples) - 1, int((len(samples) - 1) * 0.95))] if samples else None
        return {
            "latency": {
                "p50_ms": round(p50, 3) if p50 is not None else None,
                "p95_ms": round(p95, 3) if p95 is not None else None,
                "reason": "measured" if samples else "no_samples",
            },
            "process_count": result.get("process_count"),
            "process_count_reason": None if result.get("process_count") is not None else "runtime_not_reported",
            "tokens": result.get("tokens"),
            "tokens_reason": None if result.get("tokens") is not None else "runtime_not_reported",
            "rss_bytes": result.get("rss_bytes"),
            "rss_reason": None if result.get("rss_bytes") is not None else "runtime_not_reported",
        }

    @staticmethod
    def _json_digest(value: Mapping[str, Any]) -> str:
        try:
            encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise RuntimeEffectError("effect transaction data must be JSON-compatible") from exc
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def _transaction(self, request: EffectRequest, *, kind: str, action: Mapping[str, Any]) -> Dict[str, Any]:
        action_digest = self._json_digest({"kind": kind, "action": dict(action)})
        transaction_id = request.transaction_id or request.idempotency_key
        gate = request.gate_id or UNAVAILABLE
        deadline = request.deadline if request.deadline is not None else UNAVAILABLE
        identity = {
            "workspace": request.workspace,
            "attempt": request.attempt,
            "lease_id": request.lease_id,
            "fencing_token": request.fencing_token,
            "deadline": deadline,
            "cancellation_boundary": request.cancellation_boundary,
            "gate_id": gate,
            "runtime_generation": request.runtime_generation or UNAVAILABLE,
            "authorization_digest": request.authorization_digest or UNAVAILABLE,
            "transaction_id": transaction_id,
        }
        transaction = {
            "schema": TRANSACTION_SCHEMA,
            "version": "1",
            "executor": STANDALONE,
            "work_item": {"workspace": request.workspace},
            "work_item_identity": identity,
            "attempt": request.attempt,
            "lease": {"id": request.lease_id, "fence": request.fencing_token},
            "deadline": deadline,
            "cancellation": {"boundary": request.cancellation_boundary},
            "write_set": list(request.write_set),
            "gate": {"id": gate},
            "runtime_generation": request.runtime_generation or UNAVAILABLE,
            "idempotency": {
                "key": request.idempotency_key,
                "transaction_id": transaction_id,
                "action_digest": action_digest,
            },
            "request": identity,
            "authorization_digest": request.authorization_digest or UNAVAILABLE,
        }
        if request.canonical_plan is not None:
            transaction["canonical_plan"] = canonical_plan_metadata(request.canonical_plan)
        return transaction

    def _receipt(self, request: EffectRequest, *, kind: str, action: Mapping[str, Any],
                 result: Mapping[str, Any], status: str = "MEASURED",
                 delivery: Optional[str] = None) -> Dict[str, Any]:
        transaction = self._transaction(request, kind=kind, action=action)
        runtime_generation = request.runtime_generation or UNAVAILABLE
        gate_id = request.gate_id or UNAVAILABLE
        receipt = {
            "schema": SCHEMA, "profile": self.profile,
            "executor_profile": self.profile,
            "executor": "standalone",
            "status": status, "kind": kind, "workspace": request.workspace,
            "idempotency_key": request.idempotency_key, "lease_id": request.lease_id,
            "fencing_token": request.fencing_token, "write_set": list(request.write_set),
            "attempt": request.attempt, "deadline": request.deadline or UNAVAILABLE,
            "cancellation_boundary": request.cancellation_boundary,
            "runtime_generation": runtime_generation, "gate_id": gate_id,
            "transaction_id": transaction["idempotency"]["transaction_id"],
            "authorization_digest": request.authorization_digest or UNAVAILABLE,
            "transaction_correlation": transaction["idempotency"]["transaction_id"],
            "correlation_id": transaction["idempotency"]["transaction_id"],
            "delivery": delivery or STANDALONE,
            "transaction": transaction, "result": dict(result),
            "metrics": self._metrics(result),
        }
        if request.canonical_plan is not None:
            receipt["canonical_plan"] = canonical_plan_metadata(request.canonical_plan)
        return receipt

    def _standalone(self, request: EffectRequest, *, kind: str, action: Mapping[str, Any]) -> Dict[str, Any]:
        return self._receipt(
            request, kind=kind, action=action,
            result={"status": UNAVAILABLE, "reason": "standalone_profile", "delivery": STANDALONE},
            status=UNAVAILABLE, delivery=STANDALONE,
        )

    @staticmethod
    def _validate_tool(tool: str, *, explicit: bool = False) -> str:
        if not isinstance(tool, str) or not tool.startswith("simplicio_"):
            raise RuntimeEffectError("effect tool must be an allowlisted simplicio_ tool")
        if any(not (char.isalnum() or char in "_.-") for char in tool):
            raise RuntimeEffectError("effect tool must be an allowlisted simplicio_ tool")
        if explicit and tool not in _EXPLICIT_TOOLS.values():
            raise RuntimeEffectError("effect tool is not allowlisted for this adapter operation")
        return tool

    def _runtime_call(self, request: EffectRequest, *, kind: str, tool: str,
                      arguments: Mapping[str, Any]) -> Dict[str, Any]:
        self._validate_tool(tool, explicit=kind in _EXPLICIT_TOOLS)
        if not isinstance(arguments, Mapping):
            raise RuntimeEffectError("effect arguments must be an object")
        action = {"tool": tool, "arguments": dict(arguments)}
        return self._standalone(request, kind=kind, action=action)

    def execute(self, request: EffectRequest, argv: list[str], *, env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
        if not argv:
            raise RuntimeEffectError("effect argv is required")
        action = {"argv": list(argv), "env": dict(env or {})}
        return self._standalone(request, kind="execute", action=action)

    def call(self, request: EffectRequest, tool: str, arguments: Mapping[str, Any]) -> Dict[str, Any]:
        return self._runtime_call(request, kind="call", tool=tool, arguments=arguments)

    def map(self, request: EffectRequest, arguments: Mapping[str, Any]) -> Dict[str, Any]:
        return self._runtime_call(request, kind="map", tool=_EXPLICIT_TOOLS["map"], arguments=arguments)

    def read(self, request: EffectRequest, arguments: Mapping[str, Any]) -> Dict[str, Any]:
        return self._runtime_call(request, kind="read", tool=_EXPLICIT_TOOLS["read"], arguments=arguments)

    def edit(self, request: EffectRequest, arguments: Mapping[str, Any]) -> Dict[str, Any]:
        return self._runtime_call(request, kind="edit", tool=_EXPLICIT_TOOLS["edit"], arguments=arguments)

    def validate(self, request: EffectRequest, arguments: Mapping[str, Any]) -> Dict[str, Any]:
        return self._runtime_call(request, kind="validate", tool=_EXPLICIT_TOOLS["validate"], arguments=arguments)

    def checkpoint(self, request: EffectRequest, arguments: Mapping[str, Any]) -> Dict[str, Any]:
        return self._runtime_call(request, kind="checkpoint", tool=_EXPLICIT_TOOLS["checkpoint"], arguments=arguments)

    def evidence(self, request: EffectRequest, arguments: Mapping[str, Any]) -> Dict[str, Any]:
        return self._runtime_call(request, kind="evidence", tool=_EXPLICIT_TOOLS["evidence"], arguments=arguments)


__all__ = ["EffectRequest", "PROFILES", "RuntimeEffectAdapter", "RuntimeEffectError", "SCHEMA", "TRANSACTION_SCHEMA"]
