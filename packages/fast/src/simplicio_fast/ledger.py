"""Reference delivery ledger with deterministic chained event receipts."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass, replace
from typing import Any, Iterable


SCHEMA = "simplicio.fast.delivery-ledger/v1"
ZERO_HASH = "0" * 64
EVENT_TYPES = {
    "TASK_ACCEPTED",
    "ENGINE_SELECTED",
    "MAPPER_CONTEXT_PINNED",
    "FAST_CONTEXT_RESOLVED",
    "UNDERSTANDING_COMPILED",
    "PLAN_COMPILED",
    "CHANGESET_ACCEPTED",
    "EFFECT_AUTHORIZED",
    "LOCAL_GUARD_ACCEPTED",
    "EDIT_APPLIED",
    "TEST_EVIDENCE",
    "INVALIDATION_APPLIED",
    "SNAPSHOT_REFRESHED",
    "CANDIDATE_REJECTED",
    "WINNER_PROMOTED",
    "DELIVERY_SEALED",
    "HELD",
    "ROLLBACK",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SECRET_KEY = re.compile(r"(?i)(password|secret|token|api[_-]?key|private[_-]?key)")


class LedgerError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    sequence: int
    event_type: str
    event_id: str
    task_id: str
    attempt_id: str
    candidate_id: str | None
    repository: str
    source_commit: str | None
    base_generation: str | None
    overlay_generation: str | None
    producer: str
    artifact_handles: tuple[str, ...]
    artifact_digests: tuple[str, ...]
    payload_digest: str | None
    prev_event_hash: str
    event_hash: str
    metadata: dict[str, Any]

    def material(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "event_id": self.event_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "candidate_id": self.candidate_id,
            "repository": self.repository,
            "source_commit": self.source_commit,
            "base_generation": self.base_generation,
            "overlay_generation": self.overlay_generation,
            "producer": self.producer,
            "artifact_handles": list(self.artifact_handles),
            "artifact_digests": list(self.artifact_digests),
            "payload_digest": self.payload_digest,
            "prev_event_hash": self.prev_event_hash,
            "metadata": self.metadata,
        }

    def record(self) -> dict[str, Any]:
        return {**self.material(), "event_hash": self.event_hash}


class DeliveryLedger:
    """Thread-safe append-only chain; external HBP/HBI remains an adapter boundary."""

    def __init__(self, repository: str) -> None:
        if not repository:
            raise ValueError("repository is required")
        self.repository = repository
        self._events: list[LedgerEvent] = []
        self._by_id: dict[str, LedgerEvent] = {}
        self._winner: dict[tuple[str, str], str] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _validate_hash(value: str, field: str) -> None:
        if _SHA256.fullmatch(value) is None:
            raise LedgerError(
                "invalid_digest", f"{field} must be a lowercase SHA-256 digest"
            )

    @staticmethod
    def _canonical(value: object) -> bytes:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

    def _check_metadata(self, metadata: dict[str, Any]) -> None:
        def walk(value: Any, key: str = "") -> None:
            if _SECRET_KEY.search(key):
                raise LedgerError(
                    "secret_redaction", "secret-like metadata keys are not allowed"
                )
            if isinstance(value, dict):
                for child_key, child_value in value.items():
                    walk(child_value, str(child_key))
            elif isinstance(value, list):
                for child_value in value:
                    walk(child_value, key)
            elif isinstance(value, str) and _SECRET_KEY.search(value):
                raise LedgerError(
                    "secret_redaction", "secret-like metadata values are not allowed"
                )

        walk(metadata)

    def _event_id(
        self,
        event_type: str,
        task_id: str,
        attempt_id: str,
        candidate_id: str | None,
        metadata: dict[str, Any],
    ) -> str:
        return hashlib.sha256(
            self._canonical(
                {
                    "schema": SCHEMA,
                    "event_type": event_type,
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "candidate_id": candidate_id,
                    "metadata": metadata,
                }
            )
        ).hexdigest()

    def _event_hash(self, material: dict[str, Any]) -> str:
        return hashlib.sha256(
            b"simplicio.fast.delivery-ledger:event:v1\0" + self._canonical(material)
        ).hexdigest()

    def append_event(
        self,
        event_type: str,
        *,
        task_id: str,
        attempt_id: str,
        producer: str,
        candidate_id: str | None = None,
        source_commit: str | None = None,
        base_generation: str | None = None,
        overlay_generation: str | None = None,
        artifact_handles: Iterable[str] = (),
        artifact_digests: Iterable[str] = (),
        payload_digest: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LedgerEvent:
        if event_type not in EVENT_TYPES:
            raise LedgerError(
                "unknown_event_type", f"unsupported event type: {event_type}"
            )
        if not task_id or not attempt_id or not producer:
            raise ValueError("task_id, attempt_id and producer are required")
        metadata = dict(metadata or {})
        self._check_metadata(metadata)
        artifact_handles = tuple(artifact_handles)
        artifact_digests = tuple(artifact_digests)
        for digest in artifact_digests:
            self._validate_hash(digest, "artifact_digest")
        if payload_digest is not None:
            self._validate_hash(payload_digest, "payload_digest")
        event_id = self._event_id(
            event_type, task_id, attempt_id, candidate_id, metadata
        )
        with self._lock:
            existing = self._by_id.get(event_id)
            if existing is not None:
                if (
                    existing.material()["event_type"] != event_type
                    or existing.metadata != metadata
                ):
                    raise LedgerError(
                        "idempotency_conflict",
                        "event id was reused with different event data",
                    )
                return existing
            previous = self._events[-1].event_hash if self._events else ZERO_HASH
            event = LedgerEvent(
                sequence=len(self._events),
                event_type=event_type,
                event_id=event_id,
                task_id=task_id,
                attempt_id=attempt_id,
                candidate_id=candidate_id,
                repository=self.repository,
                source_commit=source_commit,
                base_generation=base_generation,
                overlay_generation=overlay_generation,
                producer=producer,
                artifact_handles=artifact_handles,
                artifact_digests=artifact_digests,
                payload_digest=payload_digest,
                prev_event_hash=previous,
                event_hash="",
                metadata=metadata,
            )
            event = replace(event, event_hash=self._event_hash(event.material()))
            self._events.append(event)
            self._by_id[event_id] = event
            return event

    def promote_winner(
        self, task_id: str, attempt_id: str, candidate_id: str, *, producer: str
    ) -> LedgerEvent:
        key = (task_id, attempt_id)
        with self._lock:
            winner = self._winner.get(key)
            if winner is not None and winner != candidate_id:
                raise LedgerError(
                    "winner_fence", "a different candidate is already promoted"
                )
            self._winner[key] = candidate_id
        return self.append_event(
            "WINNER_PROMOTED",
            task_id=task_id,
            attempt_id=attempt_id,
            candidate_id=candidate_id,
            producer=producer,
        )

    def seal_delivery(
        self, task_id: str, attempt_id: str, *, producer: str
    ) -> LedgerEvent:
        with self._lock:
            if (task_id, attempt_id) not in self._winner:
                raise LedgerError(
                    "winner_required", "delivery requires a promoted winner"
                )
        return self.append_event(
            "DELIVERY_SEALED",
            task_id=task_id,
            attempt_id=attempt_id,
            candidate_id=self._winner[(task_id, attempt_id)],
            producer=producer,
        )

    def verify_incremental(self, event: LedgerEvent | None = None) -> dict[str, Any]:
        with self._lock:
            target = event or (self._events[-1] if self._events else None)
            if target is None:
                return {"schema": SCHEMA, "status": "valid", "events": 0, "checked": 0}
            expected_previous = (
                ZERO_HASH
                if target.sequence == 0
                else self._events[target.sequence - 1].event_hash
            )
            valid = (
                target.prev_event_hash == expected_previous
                and target.event_hash == self._event_hash(target.material())
            )
            return {
                "schema": SCHEMA,
                "status": "valid" if valid else "invalid",
                "events": len(self._events),
                "checked": target.sequence + 1,
                "event_hash": target.event_hash,
            }

    def verify_all(self) -> dict[str, Any]:
        with self._lock:
            invalid: list[int] = []
            previous = ZERO_HASH
            for sequence, event in enumerate(self._events):
                if (
                    event.sequence != sequence
                    or event.prev_event_hash != previous
                    or event.event_hash != self._event_hash(event.material())
                ):
                    invalid.append(sequence)
                previous = event.event_hash
            return {
                "schema": SCHEMA,
                "status": "valid" if not invalid else "invalid",
                "events": len(self._events),
                "invalid_sequences": invalid,
                "head": previous,
            }

    def lookup_attempt(self, task_id: str, attempt_id: str) -> list[LedgerEvent]:
        with self._lock:
            return [
                event
                for event in self._events
                if event.task_id == task_id and event.attempt_id == attempt_id
            ]

    def project_json(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema": SCHEMA,
                "repository": self.repository,
                "events": [event.record() for event in self._events],
                "verification": self.verify_all(),
            }
