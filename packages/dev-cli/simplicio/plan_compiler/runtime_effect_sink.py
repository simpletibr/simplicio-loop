"""Real Runtime EffectTransaction client with durable intent and receipts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

import httpx

from simplicio.observability import emit_event
from simplicio.plan_compiler.authority import AuthorizationError, build_change_proposal
from simplicio.plan_compiler.canonical_hash import canonical_hash
from simplicio.plan_compiler.effect_sink import (
    EFFECT_STATES,
    EffectDispatchContext,
    EffectOutcome,
    IntegratedModeRequiresSinkError,
)
from simplicio.plan_compiler.models import EffectPlan, PlanValidationError

TRANSACTION_SCHEMA = "simplicio.effect-transaction/v1"
RECEIPT_SCHEMA = "simplicio.effect-receipt/v1"
SUPPORTED_MAJOR = 1
MAX_PAYLOAD_BYTES = 1_048_576


class RuntimeEffectError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class RuntimeTransport(Protocol):
    name: str

    def capabilities(self) -> dict[str, Any]: ...

    def submit(self, transaction: dict[str, Any]) -> dict[str, Any]: ...

    def query(self, idempotency_key: str) -> dict[str, Any]: ...


class OfflineRuntimeTransport:
    """Durable local EffectTransaction executor for offline installations.

    This is deliberately a transport, not a second pipeline: the caller still
    builds the exact Runtime transaction, the sink still verifies the receipt,
    and idempotency is keyed by the transaction id.  The optional
    ``artifact_ref`` points at a repository-local mechanical-edit plan.  A
    transaction without an artifact is denied rather than silently falling
    back to the legacy standalone writer.

    ``failure="after_apply"`` is a deterministic fault-injection hook used by
    the migration tests.  It simulates a lost response after the effect was
    committed; the persisted receipt makes the subsequent reconciliation
    return the original result without applying the effect twice.
    """

    name = "offline-local"
    test_only = False

    def __init__(self, *, root: str | Path, failure: str | None = None) -> None:
        self.root = Path(root)
        self.store = self.root / ".simplicio" / "runtime-effects"
        self.failure = failure
        self.apply_count = 0

    def capabilities(self) -> dict[str, Any]:
        return {
            "runtime_version": "1.0.0",
            "effect_transaction_schemas": [TRANSACTION_SCHEMA],
            "transports": [self.name],
            "mode": "offline",
        }

    def _receipt_path(self, idempotency_key: str) -> Path:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return self.store / f"{digest}.offline-receipt.json"

    def _load_receipt(self, idempotency_key: str) -> dict[str, Any] | None:
        path = self._receipt_path(idempotency_key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _persist_receipt(self, receipt: dict[str, Any]) -> None:
        path = self._receipt_path(str(receipt["idempotency_key"]))
        self.store.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)

    def _artifact_path(self, artifact_ref: object) -> Path:
        if not isinstance(artifact_ref, str) or not artifact_ref.strip():
            raise RuntimeEffectError("OFFLINE_EFFECT_ARTIFACT_REQUIRED", "write effect has no artifact_ref")
        reference = artifact_ref.strip()
        if reference.startswith("file://"):
            reference = reference[7:]
        candidate = Path(reference)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (self.root / candidate).resolve()
        try:
            resolved.relative_to(self.root.resolve())
        except ValueError as exc:
            raise RuntimeEffectError(
                "OFFLINE_ARTIFACT_ESCAPE", "artifact_ref must remain inside root"
            ) from exc
        return resolved

    def _apply_artifact(
        self, transaction: dict[str, Any]
    ) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
        effect = transaction.get("effect")
        if not isinstance(effect, dict):
            raise RuntimeEffectError("OFFLINE_EFFECT_INVALID", "transaction effect must be an object")
        artifact_path = self._artifact_path(effect.get("artifact_ref"))
        try:
            plan = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeEffectError(
                "OFFLINE_EFFECT_ARTIFACT_INVALID", "artifact_ref is not valid JSON"
            ) from exc
        if not isinstance(plan, dict) or not isinstance(plan.get("operations"), list):
            raise RuntimeEffectError(
                "OFFLINE_EFFECT_ARTIFACT_INVALID", "artifact must be a mechanical edit plan"
            )
        from simplicio.mechanical_edit import execute_plan

        self.apply_count += 1
        result = execute_plan(plan, root=self.root, apply=True)
        validation_rows = result.get("validation", [])
        validation = {
            "executor": self.name,
            "artifact_ref": artifact_path.relative_to(self.root).as_posix(),
            "status": result.get("status"),
            "applied": bool(result.get("applied")),
            "noop": bool(result.get("noop")),
            "operation_count": result.get("operation_count", 0),
            "checks": [
                {"passed": bool(row.get("passed")), "advisory": bool(row.get("advisory"))}
                for row in validation_rows
                if isinstance(row, dict)
            ],
        }
        errors = result.get("errors", [])
        error_codes = [str(row.get("code")) for row in errors if isinstance(row, dict) and row.get("code")]
        failed = bool(error_codes) or result.get("status") not in {"ok", "applied"}
        if failed:
            state = "validation_failed" if "validation_failed" in error_codes else "denied"
            rollback = {"status": "restored", "performed": True} if state == "validation_failed" else None
            return state, validation, rollback
        return "completed", validation, None

    def _build_receipt(
        self,
        transaction: dict[str, Any],
        *,
        state: str,
        validation: dict[str, Any],
        rollback: dict[str, Any] | None,
        reason_codes: list[str],
    ) -> dict[str, Any]:
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "state": state,
            "idempotency_key": transaction["idempotency_key"],
            "effect_digest": transaction["effect_digest"],
            "proposal_digest": transaction["proposal_digest"],
            "authorization_digest": transaction["authorization_digest"],
            "effect_id": transaction["causal"]["effect_id"],
            "plan_node_id": transaction["causal"]["plan_node_id"],
            "causal": transaction["causal"],
            "acceptance_criteria_refs": transaction["acceptance_criteria_refs"],
            "gate_decision": "allow" if state == "completed" else "deny",
            "base_hash": transaction["base_hash"],
            "source_hash": transaction["source_hash"],
            "validation": validation,
            "rollback": rollback,
            "reason_codes": reason_codes,
            "latency_ms": 0.0,
            "executor": self.name,
        }
        receipt["receipt_digest"] = canonical_hash(receipt)
        return receipt

    def submit(self, transaction: dict[str, Any]) -> dict[str, Any]:
        key = str(transaction.get("idempotency_key", ""))
        if not re.fullmatch(r"[0-9a-f]{16,128}", key):
            raise RuntimeEffectError("OFFLINE_IDEMPOTENCY_KEY_INVALID", "idempotency key is not safe")
        existing = self._load_receipt(key)
        if existing is not None:
            return existing
        if transaction.get("schema") != TRANSACTION_SCHEMA:
            raise RuntimeEffectError("OFFLINE_TRANSACTION_SCHEMA_INVALID", "unsupported transaction schema")
        started = time.perf_counter()
        try:
            state, validation, rollback = self._apply_artifact(transaction)
            reason_codes = ["OFFLINE_EFFECT_APPLIED"] if state == "completed" else ["OFFLINE_EFFECT_REJECTED"]
        except RuntimeEffectError as exc:
            state = "denied"
            validation = {"executor": self.name, "status": "denied"}
            rollback = None
            reason_codes = [exc.code]
        receipt = self._build_receipt(
            transaction, state=state, validation=validation, rollback=rollback, reason_codes=reason_codes
        )
        receipt["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        receipt["receipt_digest"] = canonical_hash(_without_digest(receipt))
        self._persist_receipt(receipt)
        if self.failure == "after_apply" and state == "completed":
            self.failure = None
            raise RuntimeEffectError("RUNTIME_TRANSPORT_ERROR", "offline response lost after apply")
        return receipt

    def query(self, idempotency_key: str) -> dict[str, Any]:
        receipt = self._load_receipt(idempotency_key)
        if receipt is None:
            raise RuntimeEffectError("OFFLINE_RECEIPT_NOT_FOUND", idempotency_key)
        return receipt


class HttpRuntimeTransport:
    """Public JSON/HTTP transport; endpoint selection comes from capabilities."""

    name = "http-json"

    def __init__(self, base_url: str, *, timeout_s: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = httpx.request(method, self.base_url + path, json=payload, timeout=self.timeout_s)
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip().replace("\n", " ")[:512]
            suffix = f": {detail}" if detail else ""
            raise RuntimeEffectError("RUNTIME_TRANSPORT_ERROR", f"{exc}{suffix}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeEffectError("RUNTIME_TRANSPORT_ERROR", str(exc)) from exc
        if not isinstance(result, dict):
            raise RuntimeEffectError("RUNTIME_RESPONSE_INVALID", "response must be a JSON object")
        return result

    def capabilities(self) -> dict[str, Any]:
        return self._request("GET", "/v1/capabilities")

    def submit(self, transaction: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/effect-transactions", transaction)

    def query(self, idempotency_key: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/effect-transactions/{idempotency_key}")


@dataclass
class _CircuitBreaker:
    threshold: int = 3
    cooldown_s: float = 30.0
    failures: int = 0
    opened_at: float | None = None

    def before_call(self) -> None:
        if self.opened_at is None:
            return
        if time.monotonic() - self.opened_at < self.cooldown_s:
            raise RuntimeEffectError("RUNTIME_CIRCUIT_OPEN", "Runtime calls temporarily disabled")
        self.failures = 0
        self.opened_at = None

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.monotonic()


def _safe_write_set(paths: list[str]) -> None:
    for value in paths:
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeEffectError("WRITE_SET_ESCAPE", f"unsafe write path: {value}")


def _without_digest(receipt: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in receipt.items() if key != "receipt_digest"}


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in {"prompt", "secret", "password", "access_token", "api_key"}:
                return True
            if _contains_sensitive_key(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


class RuntimeEffectSink:
    """Maps plans to Runtime transactions and verifies durable outcomes.

    A transport error after submission is ambiguous, so it returns
    ``effect_unknown`` without retry. Call :meth:`reconcile` explicitly.
    """

    test_only = False

    def __init__(
        self, transport: RuntimeTransport, *, root: str | Path, max_payload_bytes: int = MAX_PAYLOAD_BYTES
    ) -> None:
        self.transport = transport
        self.root = Path(root)
        self.store = self.root / ".simplicio" / "runtime-effects"
        self.max_payload_bytes = max_payload_bytes
        self.breaker = _CircuitBreaker()
        self._negotiated = False
        self._runtime_version: str | None = None

    @classmethod
    def from_environment(cls, *, root: str | Path) -> RuntimeEffectSink:
        if os.environ.get("SIMPLICIO_RUNTIME_OFFLINE", "").strip().lower() in {"1", "true", "yes", "on"}:
            return cls(OfflineRuntimeTransport(root=root), root=root)
        url = os.environ.get("SIMPLICIO_RUNTIME_URL", "").strip()
        if not url:
            raise IntegratedModeRequiresSinkError(
                "RUNTIME_NOT_CONFIGURED: set SIMPLICIO_RUNTIME_URL or "
                "SIMPLICIO_RUNTIME_OFFLINE=1 for mode='integrated'"
            )
        return cls(HttpRuntimeTransport(url), root=root)

    def _negotiate(self) -> None:
        if self._negotiated:
            return
        capabilities = self.transport.capabilities()
        if not isinstance(capabilities, dict):
            raise RuntimeEffectError("RUNTIME_CAPABILITY_INVALID", "capability response must be an object")
        schemas = capabilities.get("effect_transaction_schemas", [])
        transports = capabilities.get("transports", [])
        if not isinstance(schemas, list) or not all(isinstance(item, str) for item in schemas):
            raise RuntimeEffectError(
                "RUNTIME_CAPABILITY_INVALID", "effect_transaction_schemas must be a list of strings"
            )
        if not isinstance(transports, list) or not all(isinstance(item, str) for item in transports):
            raise RuntimeEffectError("RUNTIME_CAPABILITY_INVALID", "transports must be a list of strings")
        if TRANSACTION_SCHEMA not in schemas or self.transport.name not in transports:
            raise RuntimeEffectError(
                "RUNTIME_CAPABILITY_INCOMPATIBLE", "EffectTransaction/v1 or transport absent"
            )
        version = str(capabilities.get("runtime_version", "0"))
        try:
            major = int(version.split(".", 1)[0])
        except ValueError as exc:
            raise RuntimeEffectError("RUNTIME_VERSION_INVALID", version) from exc
        if major != SUPPORTED_MAJOR:
            raise RuntimeEffectError("RUNTIME_VERSION_INCOMPATIBLE", version)
        self._runtime_version = version
        self._negotiated = True

    def capability_handshake(self) -> dict[str, Any]:
        """Return the sink's versioned capability result for mode negotiation.

        This is the public bridge between the coordinator-facing execution
        profile and the exact transport contract that will submit effects.
        It never raises for an unavailable or incompatible Runtime: callers
        receive a fail-closed handshake with a stable reason code.
        """
        try:
            self._negotiate()
        except RuntimeEffectError as exc:
            return {
                "verified": False,
                "version": None,
                "capabilities": [],
                "reason": exc.code,
                "transport": self.transport.name,
            }
        return {
            "verified": True,
            "version": self._runtime_version,
            "capabilities": [TRANSACTION_SCHEMA],
            "reason": "ok",
            "transport": self.transport.name,
        }

    def _transaction(self, effect: EffectPlan, context: EffectDispatchContext) -> dict[str, Any]:
        if effect.context_handle != context.context_handle:
            raise RuntimeEffectError("CONTEXT_HANDLE_MISMATCH", "EffectPlan and dispatch context differ")
        node = context.plan_node
        _safe_write_set(node.write_set)
        if context.authorization is None:
            raise RuntimeEffectError(
                "EFFECT_AUTHORIZATION_REQUIRED", "effect requires coordinator authorization"
            )
        try:
            proposal = build_change_proposal(effect, context)
            context.authorization.verify(proposal)
        except AuthorizationError as exc:
            raise RuntimeEffectError(exc.code, str(exc)) from exc
        effect_body = effect.to_dict()
        effect_digest = canonical_hash(effect_body)
        plan_body = None
        plan_digest = None
        if context.plan is not None:
            if context.plan.plan_id != context.plan_id or context.plan.goal_id != context.goal_id:
                raise RuntimeEffectError(
                    "PLAN_CONTEXT_MISMATCH", "PlanDAG identity differs from dispatch context"
                )
            try:
                context.plan.validate(effects=[effect])
            except PlanValidationError as exc:
                raise RuntimeEffectError("PLAN_CONTRACT_INVALID", str(exc)) from exc
            plan_body = context.plan.to_dict()
            plan_digest = canonical_hash(plan_body)
        causal = {
            "coordinator_kind": context.coordinator_kind,
            "coordinator_id": context.coordinator_id,
            "session_id": context.session_id,
            "turn_id": context.turn_id,
            "attempt": context.attempt,
            "subworkflow_id": context.subworkflow_id,
            "plan_id": context.plan_id,
            "goal_id": context.goal_id,
            "plan_node_id": effect.plan_node_id,
            "effect_id": effect.effect_id,
        }
        if context.context_handle:
            causal["context_handle"] = context.context_handle
        key = hashlib.sha256(
            json.dumps([causal, effect_digest, plan_digest], sort_keys=True).encode()
        ).hexdigest()
        return {
            "schema": TRANSACTION_SCHEMA,
            "idempotency_key": key,
            "effect_digest": effect_digest,
            "proposal": proposal.to_dict(),
            "proposal_digest": proposal.digest(),
            "authorization": context.authorization.to_dict(),
            "authorization_digest": context.authorization.authorization_digest,
            "causal": causal,
            "plan": plan_body,
            "plan_digest": plan_digest,
            "effect": effect_body,
            "authority_required": effect.authority_required,
            "deadline": context.deadline,
            "risk": node.risk,
            "policy_revision": context.policy_revision,
            "preconditions": effect.preconditions,
            "base_hash": context.base_hash,
            "source_hash": context.source_hash,
            "read_set": node.read_set,
            "write_set": node.write_set,
            "validation_plan": [item.to_dict() for item in context.verifications],
            "acceptance_criteria_refs": node.acceptance_criteria_refs,
            "rollback_policy": node.rollback_strategy,
        }

    def _path(self, key: str, suffix: str) -> Path:
        return self.store / f"{key}.{suffix}.json"

    def _persist(self, key: str, suffix: str, payload: dict[str, Any]) -> None:
        self.store.mkdir(parents=True, exist_ok=True)
        path = self._path(key, suffix)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)

    def _validate_receipt(self, receipt: Any, transaction: dict[str, Any]) -> EffectOutcome:
        if not isinstance(receipt, dict):
            raise RuntimeEffectError("RUNTIME_RESPONSE_INVALID", "receipt must be a JSON object")
        if receipt.get("schema") != RECEIPT_SCHEMA:
            raise RuntimeEffectError("RECEIPT_SCHEMA_INVALID", str(receipt.get("schema")))
        state = str(receipt.get("state", ""))
        if state not in EFFECT_STATES:
            raise RuntimeEffectError("RECEIPT_STATE_INVALID", state)
        expected = {
            "idempotency_key": transaction["idempotency_key"],
            "effect_digest": transaction["effect_digest"],
            "effect_id": transaction["causal"]["effect_id"],
            "plan_node_id": transaction["causal"]["plan_node_id"],
            "proposal_digest": transaction["proposal_digest"],
            "authorization_digest": transaction["authorization_digest"],
        }
        for field, value in expected.items():
            if receipt.get(field) != value:
                raise RuntimeEffectError("RECEIPT_CORRELATION_MISMATCH", field)
        if receipt.get("causal") != transaction["causal"]:
            raise RuntimeEffectError("RECEIPT_CORRELATION_MISMATCH", "causal")
        digest = canonical_hash(_without_digest(receipt))
        if receipt.get("receipt_digest") != digest:
            raise RuntimeEffectError("RECEIPT_DIGEST_INVALID", "receipt content does not match digest")
        if receipt.get("acceptance_criteria_refs", []) != transaction["acceptance_criteria_refs"]:
            raise RuntimeEffectError("RECEIPT_CORRELATION_MISMATCH", "acceptance_criteria_refs")
        if receipt.get("gate_decision") not in {"allow", "deny"}:
            raise RuntimeEffectError("RECEIPT_GATE_DECISION_INVALID", str(receipt.get("gate_decision")))
        for field in ("base_hash", "source_hash"):
            if receipt.get(field) != transaction[field]:
                raise RuntimeEffectError("RECEIPT_HASH_MISMATCH", field)
        if _contains_sensitive_key(receipt):
            raise RuntimeEffectError("RECEIPT_REDACTION_INVALID", "sensitive field present")
        if state in {"completed", "validation_failed", "rolled_back"} and not isinstance(
            receipt.get("validation"), dict
        ):
            raise RuntimeEffectError("RECEIPT_VALIDATION_MISSING", state)
        return EffectOutcome(
            effect_id=expected["effect_id"],
            state=state,
            idempotency_key=expected["idempotency_key"],
            receipt=receipt,
            reason_codes=list(receipt.get("reason_codes", [])),
            validation=receipt.get("validation"),
            rollback=receipt.get("rollback"),
            latency_ms=receipt.get("latency_ms"),
            transport=self.transport.name,
        )

    def _safe_outcome(
        self,
        *,
        effect_id: str,
        idempotency_key: str,
        state: str,
        reason_code: str,
        started: float,
    ) -> EffectOutcome:
        """Persist a non-terminal result without storing an unsafe receipt."""
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        outcome = EffectOutcome(
            effect_id,
            state,
            idempotency_key,
            reason_codes=[reason_code],
            latency_ms=latency_ms,
            transport=self.transport.name,
        )
        self._persist(idempotency_key, "outcome", outcome.to_dict())
        emit_event(
            "effect_outcome",
            {
                "effect_id": effect_id,
                "state": outcome.state,
                "transport": self.transport.name,
                "latency_ms": latency_ms,
                "reason_codes": [reason_code],
            },
            level="warning",
            root=str(self.root),
        )
        return outcome

    def submit(self, effect: EffectPlan, context: EffectDispatchContext) -> EffectOutcome:
        transaction = self._transaction(effect, context)
        key = transaction["idempotency_key"]
        encoded = json.dumps(transaction, sort_keys=True).encode()
        if len(encoded) > self.max_payload_bytes:
            raise RuntimeEffectError("EFFECT_PAYLOAD_OVERSIZED", str(len(encoded)))
        existing = self._path(key, "intent")
        if existing.exists():
            prior = json.loads(existing.read_text(encoding="utf-8"))
            if prior.get("effect_digest") != transaction["effect_digest"]:
                raise RuntimeEffectError("IDEMPOTENCY_DIGEST_CONFLICT", key)
            return self.reconcile(transaction)
        self._persist(key, "intent", transaction)
        started = time.perf_counter()
        try:
            self.breaker.before_call()
            self._negotiate()
        except RuntimeEffectError as exc:
            if exc.code != "RUNTIME_CIRCUIT_OPEN":
                self.breaker.failure()
            if exc.code in {
                "RUNTIME_CIRCUIT_OPEN",
                "RUNTIME_TRANSPORT_ERROR",
                "RUNTIME_RESPONSE_INVALID",
            }:
                return self._safe_outcome(
                    effect_id=effect.effect_id,
                    idempotency_key=key,
                    state="not_started",
                    reason_code=exc.code,
                    started=started,
                )
            raise
        try:
            receipt = self.transport.submit(transaction)
        except RuntimeEffectError as exc:
            self.breaker.failure()
            if exc.code in {"RUNTIME_TRANSPORT_ERROR", "RUNTIME_RESPONSE_INVALID"}:
                return self._safe_outcome(
                    effect_id=effect.effect_id,
                    idempotency_key=key,
                    state="effect_unknown",
                    reason_code=exc.code,
                    started=started,
                )
            raise
        try:
            outcome = self._validate_receipt(receipt, transaction)
        except RuntimeEffectError as exc:
            self.breaker.failure()
            return self._safe_outcome(
                effect_id=effect.effect_id,
                idempotency_key=key,
                state="effect_unknown",
                reason_code=exc.code,
                started=started,
            )
        self.breaker.success()
        self._persist(key, "receipt", receipt)
        self._persist(key, "outcome", outcome.to_dict())
        emit_event(
            "effect_outcome",
            {
                "effect_id": effect.effect_id,
                "state": outcome.state,
                "transport": self.transport.name,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            },
            root=str(self.root),
        )
        return outcome

    def reconcile(self, transaction_or_key: dict[str, Any] | str) -> EffectOutcome:
        if isinstance(transaction_or_key, str):
            key = transaction_or_key
            path = self._path(key, "intent")
            if not path.exists():
                raise RuntimeEffectError("INTENT_NOT_FOUND", key)
            transaction = json.loads(path.read_text(encoding="utf-8"))
        else:
            transaction = transaction_or_key
            key = transaction["idempotency_key"]
        started = time.perf_counter()
        try:
            self.breaker.before_call()
            self._negotiate()
            receipt = self.transport.query(key)
        except RuntimeEffectError as exc:
            if exc.code != "RUNTIME_CIRCUIT_OPEN":
                self.breaker.failure()
            return self._safe_outcome(
                effect_id=transaction["causal"]["effect_id"],
                idempotency_key=key,
                state="effect_unknown",
                reason_code=exc.code,
                started=started,
            )
        try:
            outcome = self._validate_receipt(receipt, transaction)
        except RuntimeEffectError as exc:
            self.breaker.failure()
            return self._safe_outcome(
                effect_id=transaction["causal"]["effect_id"],
                idempotency_key=key,
                state="effect_unknown",
                reason_code=exc.code,
                started=started,
            )
        self.breaker.success()
        self._persist(key, "receipt", receipt)
        self._persist(key, "outcome", outcome.to_dict())
        return outcome

    def status(self) -> dict[str, Any]:
        try:
            self.breaker.before_call()
            self._negotiate()
            return {"healthy": True, "transport": self.transport.name, "reason_codes": []}
        except RuntimeEffectError as exc:
            return {"healthy": False, "transport": self.transport.name, "reason_codes": [exc.code]}
