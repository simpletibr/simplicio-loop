"""Persistent Hookwall-gated host for coverage custodian dispatches."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable, Mapping

from .coverage_custodians import validate_receipt
from .hookwall_gate import (
    DECISION_SCHEMA, ENVELOPE_SCHEMA, RECEIPT_SCHEMA,
    HookwallBlocked, validate_pre_decision, verify_post_receipt,
)

HOST_SCHEMA = "simplicio.coverage-custodian-host/v1"
JOURNAL_SCHEMA = "simplicio.coverage-custodian-journal/v1"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class CustodianHost:
    """Materialize one worker only after a valid Hookwall pre-decision."""

    def __init__(self, journal: str | Path, *, max_inflight: int = 4) -> None:
        if max_inflight <= 0:
            raise ValueError("max_inflight must be positive")
        self.path = Path(journal)
        self.max_inflight = max_inflight
        self._lock = threading.RLock()
        self._inflight = 0

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema": JOURNAL_SCHEMA, "entries": {}, "metrics": {
                "addresses_seen": 0, "envelopes_seen": 0, "workers_materialized": 0,
                "workers_avoided": 0, "executions": 0, "completion_decisions": 0,
            }}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HookwallBlocked("custodian_journal_corrupt", str(exc)) from exc
        if value.get("schema") != JOURNAL_SCHEMA or not isinstance(value.get("entries"), dict):
            raise HookwallBlocked("custodian_journal_invalid", "journal schema/entries invalid")
        return value

    def _save(self, value: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(_canonical(value) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    @staticmethod
    def hookwall_envelope(
        envelope: Mapping[str, Any], *, workspace: str, policy_hash: str,
    ) -> dict[str, Any]:
        result = {
            "schema": ENVELOPE_SCHEMA,
            "envelope_id": envelope["envelope_digest"],
            "run_id": envelope["run_id"],
            "plan_id": str(envelope["plan_revision"]),
            "source_hash": envelope["gap_id"],
            "policy_hash": policy_hash,
            "idempotency_key": envelope["idempotency_key"],
            "workspace": workspace,
            "fence": envelope["fence"],
            "effect_set": ["process", "write"],
            "write_set": [".simplicio-loop/custodian/" + str(envelope["gap_id"]).replace(":", "_") + ".json"],
            "command": ["simplicio-dev-cli", "task", "--json"],
        }
        # validate_envelope seals the canonical hash.
        from .hookwall_gate import validate_envelope
        return validate_envelope(result)

    @staticmethod
    def mutation_receipt(hook_envelope: Mapping[str, Any], fast_receipt: Mapping[str, Any]) -> dict[str, Any]:
        result = {
            "schema": RECEIPT_SCHEMA,
            "envelope_id": hook_envelope["envelope_id"],
            "source_hash": hook_envelope["source_hash"],
            "policy_hash": hook_envelope["policy_hash"],
            "idempotency_key": hook_envelope["idempotency_key"],
            "fence": hook_envelope["fence"],
            "status": "verified",
            "effect_digest": fast_receipt["receipt_digest"],
        }
        result["receipt_hash"] = _hash(result)
        return result

    def dispatch(
        self,
        envelope: Mapping[str, Any],
        *,
        workspace: str,
        policy_hash: str,
        pre_hook: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        worker: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        post_hook: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
        cancelled: Callable[[], bool] = lambda: False,
        ttl_seconds: float = 120.0,
    ) -> dict[str, Any]:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        key = str(envelope["idempotency_key"])
        with self._lock:
            journal = self._load()
            journal["metrics"]["envelopes_seen"] += 1
            previous = journal["entries"].get(key)
            if previous and previous.get("state") == "VERIFIED":
                journal["metrics"]["workers_avoided"] += 1
                self._save(journal)
                return previous["host_receipt"]
            if self._inflight >= self.max_inflight:
                raise HookwallBlocked("custodian_backpressure", "max inflight reached")
            if cancelled():
                raise HookwallBlocked("custodian_cancelled", "cancelled before Hookwall")

        hook_envelope = self.hookwall_envelope(
            envelope, workspace=workspace, policy_hash=policy_hash,
        )
        pre_decision = dict(pre_hook(hook_envelope))
        validate_pre_decision(hook_envelope, pre_decision)
        started = time.monotonic()
        with self._lock:
            self._inflight += 1
            journal = self._load()
            journal["metrics"]["workers_materialized"] += 1
            journal["entries"][key] = {"state": "MATERIALIZED", "envelope": dict(envelope)}
            self._save(journal)
        try:
            if cancelled():
                raise HookwallBlocked("custodian_cancelled", "cancelled before worker execution")
            fast_receipt = dict(worker(envelope))
            if time.monotonic() - started > ttl_seconds:
                raise HookwallBlocked("custodian_ttl_expired", "worker exceeded dispatch TTL")
            valid, reason = validate_receipt(fast_receipt, envelope)
            if not valid:
                raise HookwallBlocked("fast_receipt_invalid", reason)
            mutation = self.mutation_receipt(hook_envelope, fast_receipt)
            post_decision = dict(post_hook(hook_envelope, mutation))
            evidence = verify_post_receipt(
                hook_envelope, pre_decision, mutation, post_decision,
            )
            host_receipt = {
                "schema": HOST_SCHEMA,
                "gap_id": envelope["gap_id"],
                "idempotency_key": key,
                "envelope_digest": envelope["envelope_digest"],
                "fast_receipt_digest": fast_receipt["receipt_digest"],
                "hookwall_evidence": evidence,
                "worker_state": "STOPPED",
                "completion_authority": "LOOP_ONLY",
            }
            host_receipt["host_receipt_digest"] = _hash(host_receipt)
            with self._lock:
                journal = self._load()
                journal["metrics"]["executions"] += 1
                journal["entries"][key] = {
                    "state": "VERIFIED", "host_receipt": host_receipt,
                    "fast_receipt": fast_receipt,
                }
                self._save(journal)
            return host_receipt
        except BaseException:
            with self._lock:
                journal = self._load()
                journal["entries"][key] = {
                    "state": "BLOCKED", "reason": "dispatch_failed",
                    "envelope": dict(envelope),
                }
                self._save(journal)
            raise
        finally:
            with self._lock:
                self._inflight -= 1

    def metrics(self) -> dict[str, int]:
        with self._lock:
            return dict(self._load()["metrics"])


def proceed_decision(envelope: Mapping[str, Any], *, phase: str, receipt_hash: str | None = None) -> dict[str, Any]:
    """Build deterministic test/reference Hookwall decisions."""
    result = {
        "schema": DECISION_SCHEMA, "phase": phase, "verdict": "proceed",
        "reason_code": "policy_authorized",
        "envelope_id": envelope["envelope_id"],
        "source_hash": envelope["source_hash"],
        "policy_hash": envelope["policy_hash"],
        "fence": envelope["fence"],
        "envelope_hash": envelope["envelope_hash"],
        "idempotency_key": envelope["idempotency_key"],
    }
    if receipt_hash:
        result["receipt_hash"] = receipt_hash
    return result


__all__ = ["CustodianHost", "HOST_SCHEMA", "JOURNAL_SCHEMA", "proceed_decision"]
