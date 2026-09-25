"""Portable provenance receipts for Fast generations (no .sfast access required)."""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any, Mapping

SCHEMA = "simplicio.fast-generation-receipt/v1"
KINDS = {"build", "query", "context", "refresh", "overlay", "rollout"}


class GenerationReceiptError(ValueError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}")


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def seal_receipt(
    *,
    kind: str,
    repo: str,
    commit: str,
    snapshot_digest: str,
    generation: str,
    source_hashes: Mapping[str, str],
    backend: str,
    backend_artifact_hash: str | None = None,
    fallback_reason: str | None = None,
    ancestor_receipt_hash: str | None = None,
    ancestor_context_packet_hash: str | None = None,
    downstream_changeset_hash: str | None = None,
) -> dict[str, Any]:
    if kind not in KINDS:
        raise GenerationReceiptError("receipt_kind_invalid", kind)
    if backend not in {"python", "rust"}:
        raise GenerationReceiptError("backend_invalid", backend)
    if backend == "rust" and not backend_artifact_hash:
        raise GenerationReceiptError("native_artifact_unbound", backend)
    if backend == "python" and backend_artifact_hash is not None:
        raise GenerationReceiptError("python_artifact_invalid", backend_artifact_hash)
    required = (repo, commit, snapshot_digest, generation)
    if any(not value for value in required) or not source_hashes:
        raise GenerationReceiptError("receipt_binding_missing")
    body = {
        "schema": SCHEMA,
        "kind": kind,
        "repo": repo,
        "commit": commit,
        "snapshot_digest": snapshot_digest,
        "generation": generation,
        "source_hashes": dict(sorted(source_hashes.items())),
        "backend": backend,
        "backend_artifact_hash": backend_artifact_hash,
        "fallback_reason": fallback_reason,
        "ancestor_receipt_hash": ancestor_receipt_hash,
        "ancestor_context_packet_hash": ancestor_context_packet_hash,
        "downstream_changeset_hash": downstream_changeset_hash,
        "public_offsets": None,
        "public_offsets_null_reason": "FAST_INTERNAL_OFFSETS_NOT_PUBLIC",
    }
    body["idempotency_key"] = digest(
        {
            "kind": kind,
            "repo": repo,
            "commit": commit,
            "snapshot_digest": snapshot_digest,
            "generation": generation,
            "source_hashes": body["source_hashes"],
            "ancestor_receipt_hash": ancestor_receipt_hash,
            "ancestor_context_packet_hash": ancestor_context_packet_hash,
            "downstream_changeset_hash": downstream_changeset_hash,
        }
    )
    body["receipt_hash"] = digest(body)
    return body


def verify_receipt(
    receipt: Mapping[str, Any],
    *,
    expected_repo: str | None = None,
    expected_commit: str | None = None,
    expected_generation: str | None = None,
    expected_source_hashes: Mapping[str, str] | None = None,
    expected_ancestor_hash: str | None = None,
) -> dict[str, Any]:
    if receipt.get("schema") != SCHEMA:
        raise GenerationReceiptError("receipt_schema_invalid")
    unsigned = dict(receipt)
    supplied = unsigned.pop("receipt_hash", "")
    if supplied != digest(unsigned):
        raise GenerationReceiptError("receipt_corrupt", supplied)
    checks = (
        ("receipt_repo_mismatch", expected_repo, receipt.get("repo")),
        ("receipt_commit_stale", expected_commit, receipt.get("commit")),
        ("receipt_generation_stale", expected_generation, receipt.get("generation")),
        (
            "receipt_ancestor_mismatch",
            expected_ancestor_hash,
            receipt.get("ancestor_receipt_hash"),
        ),
    )
    for reason, expected, actual in checks:
        if expected is not None and expected != actual:
            raise GenerationReceiptError(reason, str(actual))
    if expected_source_hashes is not None and (
        dict(sorted(expected_source_hashes.items())) != receipt.get("source_hashes")
    ):
        raise GenerationReceiptError("receipt_source_stale")
    return dict(receipt)


def verify_chain(receipts: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    verified, previous = [], None
    for receipt in receipts:
        item = verify_receipt(receipt, expected_ancestor_hash=previous)
        verified.append(item)
        previous = item["receipt_hash"]
    return verified


class ReceiptJournal:
    """In-memory idempotent journal; retries return the original sealed receipt."""

    def __init__(self) -> None:
        self._receipts: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def append(self, receipt: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        item = verify_receipt(receipt)
        key = item["idempotency_key"]
        with self._lock:
            existing = self._receipts.get(key)
            if existing is not None:
                if existing != item:
                    raise GenerationReceiptError("idempotency_collision", key)
                return dict(existing), True
            self._receipts[key] = item
            return dict(item), False
