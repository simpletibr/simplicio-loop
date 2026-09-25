"""Read-only bounded projection of versioned operational receipts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from typing import Any, Iterable


RECEIPT_SCHEMA = "simplicio.fast.operations-receipt/v1"
PROJECTION_SCHEMA = "simplicio.fast.operations-projection/v1"
MAX_QUERY_RESULTS = 100_000


class OperationsProjectionError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class OperationReceipt:
    handle: str
    kind: str
    status: str
    generation: str
    sequence: int
    source_schema: str
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (self.handle, self.kind, self.status, self.generation, self.source_schema)):
            raise OperationsProjectionError("receipt_identity_invalid")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 0:
            raise OperationsProjectionError("receipt_sequence_invalid")
        if not isinstance(self.payload, dict):
            raise OperationsProjectionError("receipt_payload_invalid")
        try:
            payload = deepcopy(self.payload)
        except (TypeError, ValueError) as error:
            raise OperationsProjectionError("receipt_payload_invalid") from error
        object.__setattr__(self, "payload", payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RECEIPT_SCHEMA,
            "handle": self.handle,
            "kind": self.kind,
            "status": self.status,
            "generation": self.generation,
            "sequence": self.sequence,
            "source_schema": self.source_schema,
            "payload": dict(self.payload),
        }


class OperationsProjection:
    """Derived view fed by explicit exports; it does not own operational state."""

    def __init__(self, repository: str, generation: str) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (repository, generation)):
            raise OperationsProjectionError("projection_scope_invalid")
        self.repository = repository
        self.generation = generation
        self._receipts: dict[str, OperationReceipt] = {}
        self._last_sequences: dict[str, int] = {}
        self._tombstones: dict[str, OperationReceipt] = {}
        self._causal_gaps: set[str] = set()
        self._forks: set[str] = set()
        self._lock = RLock()

    def _refresh_consistency(self) -> None:
        gaps: set[str] = set()
        for receipt in self._receipts.values():
            parent = receipt.payload.get("causal_parent")
            if parent is None:
                continue
            if not isinstance(parent, str) or not parent.strip():
                gaps.add(receipt.handle)
                continue
            predecessor = self._receipts.get(parent)
            if predecessor is None or predecessor.sequence >= receipt.sequence:
                gaps.add(receipt.handle)
        self._causal_gaps = gaps

    def _item(self, receipt: OperationReceipt) -> dict[str, Any]:
        item = receipt.to_dict()
        if receipt.handle in self._forks:
            item["consistency"] = "fork"
        elif receipt.handle in self._causal_gaps:
            item["consistency"] = "causal_gap"
        else:
            item["consistency"] = "consistent"
        return item

    def ingest(self, receipts: Iterable[OperationReceipt]) -> dict[str, Any]:
        try:
            receipts = tuple(receipts)
        except TypeError as error:
            raise OperationsProjectionError("receipt_input_invalid") from error
        if any(not isinstance(receipt, OperationReceipt) for receipt in receipts):
            raise OperationsProjectionError("receipt_type_invalid")
        with self._lock:
            changed: list[str] = []
            for receipt in receipts:
                if receipt.generation != self.generation:
                    raise OperationsProjectionError("receipt_generation_mismatch")
                previous = self._receipts.get(receipt.handle) or self._tombstones.get(receipt.handle)
                last_sequence = self._last_sequences.get(receipt.handle)
                if last_sequence is not None and receipt.sequence < last_sequence:
                    raise OperationsProjectionError("receipt_sequence_regression")
                if previous is not None and receipt.sequence == last_sequence:
                    if receipt.to_dict() == previous.to_dict():
                        continue
                    self._forks.add(receipt.handle)
                    raise OperationsProjectionError("receipt_fork_detected")
                self._last_sequences[receipt.handle] = receipt.sequence
                if receipt.payload.get("tombstone") is True:
                    self._receipts.pop(receipt.handle, None)
                    self._tombstones[receipt.handle] = receipt
                else:
                    self._tombstones.pop(receipt.handle, None)
                    self._receipts[receipt.handle] = receipt
                changed.append(receipt.handle)
            self._refresh_consistency()
            return {
                "schema": "simplicio.fast.operations-delta/v1",
                "repository": self.repository,
                "generation": self.generation,
                "changed_handles": sorted(set(changed)),
                "tombstones": sorted(handle for handle in changed if handle in self._tombstones),
            }

    @staticmethod
    def _validate_query_budget(max_results: int, as_of_sequence: int | None) -> None:
        if isinstance(max_results, bool) or not isinstance(max_results, int) or not 0 < max_results <= MAX_QUERY_RESULTS:
            raise OperationsProjectionError("query_budget_invalid")
        if as_of_sequence is not None and (isinstance(as_of_sequence, bool) or not isinstance(as_of_sequence, int) or as_of_sequence < 0):
            raise OperationsProjectionError("query_as_of_invalid")

    def query(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        max_results: int = 1000,
        as_of_sequence: int | None = None,
    ) -> list[dict[str, Any]]:
        self._validate_query_budget(max_results, as_of_sequence)
        self._validate_status_filter(status)
        self._validate_kind_filter(kind)
        with self._lock:
            values = [
                item for item in self._receipts.values()
                if (status is None or item.status == status)
                and (kind is None or item.kind == kind)
                and (as_of_sequence is None or item.sequence <= as_of_sequence)
                and not (status == "complete" and item.handle in self._causal_gaps)
            ]
            return [self._item(item) for item in sorted(values, key=lambda item: (item.sequence, item.handle), reverse=True)[:max_results]]

    @staticmethod
    def _validate_status_filter(status: str | None) -> None:
        if status is not None and (not isinstance(status, str) or not status.strip()):
            raise OperationsProjectionError("query_filter_invalid")

    @staticmethod
    def _validate_kind_filter(kind: str | None) -> None:
        if kind is not None and (not isinstance(kind, str) or not kind.strip()):
            raise OperationsProjectionError("query_filter_invalid")

    def query_slots(self, *, status: str | None = None, max_results: int = 1000) -> list[dict[str, Any]]:
        """Read slot/attempt facts without accepting or mutating leases."""
        self._validate_query_budget(max_results, None)
        self._validate_status_filter(status)
        with self._lock:
            values = [
                item for item in self._receipts.values()
                if item.kind in {"slot", "attempt", "lease"}
                and (status is None or item.status == status)
            ]
            return [self._item(item) for item in sorted(values, key=lambda item: (item.sequence, item.handle), reverse=True)[:max_results]]

    def query_leases(self, observed_at: int, *, max_results: int = 1000) -> list[dict[str, Any]]:
        """Return producer-reported lease facts with derived temporal status."""
        if (
            isinstance(observed_at, bool)
            or not isinstance(observed_at, int)
            or observed_at < 0
            or isinstance(max_results, bool)
            or not isinstance(max_results, int)
            or not 0 < max_results <= MAX_QUERY_RESULTS
        ):
            raise OperationsProjectionError("lease_query_invalid")
        with self._lock:
            result: list[dict[str, Any]] = []
            for receipt in sorted(self._receipts.values(), key=lambda item: (item.sequence, item.handle), reverse=True):
                lease = receipt.payload.get("lease")
                if receipt.kind != "lease" and not isinstance(lease, dict):
                    continue
                lease = lease if isinstance(lease, dict) else receipt.payload
                expires_at = lease.get("expires_at")
                if isinstance(expires_at, bool) or not isinstance(expires_at, int) or expires_at < 0:
                    raise OperationsProjectionError("lease_expiry_invalid")
                item = self._item(receipt)
                item["lease"] = {
                    "owner": lease.get("owner"),
                    "fence": lease.get("fence"),
                    "expires_at": expires_at,
                    "active": observed_at < expires_at,
                    "authority": "producer",
                }
                result.append(item)
                if len(result) >= max_results:
                    break
            return result

    def stats(self) -> dict[str, Any]:
        with self._lock:
            statuses: dict[str, int] = {}
            kinds: dict[str, int] = {}
            for receipt in self._receipts.values():
                statuses[receipt.status] = statuses.get(receipt.status, 0) + 1
                kinds[receipt.kind] = kinds.get(receipt.kind, 0) + 1
            return {"schema": "simplicio.fast.operations-stats/v1", "repository": self.repository, "generation": self.generation, "receipts": len(self._receipts), "tombstones": len(self._tombstones), "statuses": dict(sorted(statuses.items())), "kinds": dict(sorted(kinds.items())), "consistency": {"causal_gaps": len(self._causal_gaps), "forks": len(self._forks)}, "authority": "derived_read_only"}

    def snapshot(self, *, observed_sequence: int | None = None, as_of_sequence: int | None = None) -> dict[str, Any]:
        self._validate_query_budget(MAX_QUERY_RESULTS, as_of_sequence)
        if observed_sequence is not None and (isinstance(observed_sequence, bool) or not isinstance(observed_sequence, int) or observed_sequence < 0):
            raise OperationsProjectionError("snapshot_sequence_invalid")
        with self._lock:
            latest_by_producer: dict[str, int] = {}
            for receipt in self._receipts.values():
                producer = receipt.payload.get("producer")
                if isinstance(producer, str) and producer.strip():
                    latest_by_producer[producer] = max(latest_by_producer.get(producer, -1), receipt.sequence)
            freshness = {
                producer: {
                    "latest_sequence": sequence,
                    "lag": None if observed_sequence is None else max(0, observed_sequence - sequence),
                }
                for producer, sequence in sorted(latest_by_producer.items())
            }
            return {
                "schema": PROJECTION_SCHEMA,
                "repository": self.repository,
                "generation": self.generation,
                "consistency": {"causal_gaps": sorted(self._causal_gaps), "forks": sorted(self._forks)},
                "tombstones": sorted(self._tombstones),
                "freshness": freshness,
                "receipts": self.query(as_of_sequence=as_of_sequence),
            }


__all__ = ["MAX_QUERY_RESULTS", "OperationReceipt", "OperationsProjection", "OperationsProjectionError", "PROJECTION_SCHEMA", "RECEIPT_SCHEMA"]
