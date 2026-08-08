"""Deterministic, idempotent reconciliation for uncertain Runtime effects."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from ..runtime_bridge import call_simplicio
from ..standalone_migration import clear_effect_unknown, load_effect_unknown_lock
from ..store_adapter import MapperStoreAdapter, StoreAdapterError

SCHEMA = "simplicio.dev-cli.effect-reconciliation-result/v1"
RECEIPT_SCHEMA = "simplicio.dev-cli.effect-reconciliation-receipt/v1"
_RUNTIME_SCHEMA = "simplicio.effect-reconciliation/v1"
_SAFE_VERDICTS = {"unchanged-before", "proven-after"}
_STORE_DOMAIN = "effect-transactions"
_STORE_PREFIX = "effect-reconciliation:"
_LOCK_RETRY_ATTEMPTS = 200
_LOCK_RETRY_DELAY_SECONDS = 0.01


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _result(status: str, *, code: str | None = None, **payload: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"schema": SCHEMA, "status": status, "safe_to_clear_pending": False}
    if code:
        result["error"] = {"code": code}
    result.update(payload)
    return result


def _record_key(key: str) -> str:
    return f"{_STORE_PREFIX}{key}"


def _acquire_store_lock(store: MapperStoreAdapter, key: str):
    for attempt in range(_LOCK_RETRY_ATTEMPTS):
        try:
            return store.acquire(_record_key(key), operation="effect-reconciliation")
        except StoreAdapterError as exc:
            if str(exc) != "STORE_LOCKED" or attempt == _LOCK_RETRY_ATTEMPTS - 1:
                raise
            time.sleep(_LOCK_RETRY_DELAY_SECONDS)
    raise StoreAdapterError("STORE_LOCKED")


def _relative_locator(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _resolve_evidence(root: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    return resolved if resolved.is_relative_to(root) else None


def _receipt_locator(root: Path, store: MapperStoreAdapter, key: str) -> str:
    return _relative_locator(root, store.record_path(_record_key(key)))


def _receipt_digest(receipt: dict[str, Any]) -> str:
    unsigned = {name: value for name, value in receipt.items() if name != "receipt_sha256"}
    return hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest()


def _attach_durable_receipt(
    result: dict[str, Any],
    *,
    locator: str,
    digest: str,
    replayed: bool,
) -> dict[str, Any]:
    return {
        **result,
        "replayed": replayed,
        "durable_receipt": {
            "schema": RECEIPT_SCHEMA,
            "locator": locator,
            "sha256": f"sha256:{digest}",
            "durability": "fsync+atomic-replace",
            "verification": "verified_read_back",
        },
    }


def _load_receipt(
    root: Path,
    store: MapperStoreAdapter,
    key: str,
) -> tuple[dict[str, Any], str, str] | None:
    receipt = store.read(_record_key(key))
    if receipt is None:
        return None
    digest = str(receipt.get("receipt_sha256") or "")
    result = receipt.get("result")
    evidence_locator = str(receipt.get("evidence_locator") or "")
    if (
        receipt.get("schema") != RECEIPT_SCHEMA
        or receipt.get("idempotency_key") != key
        or not isinstance(result, dict)
        or not evidence_locator
        or digest != _receipt_digest(receipt)
    ):
        raise StoreAdapterError("STORE_CORRUPT")
    locator = _receipt_locator(root, store, key)
    return dict(result), locator, digest


def _persist_receipt(
    root: Path,
    store: MapperStoreAdapter,
    key: str,
    evidence_locator: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "idempotency_key": key,
        "evidence_locator": evidence_locator,
        "result": result,
    }
    receipt["receipt_sha256"] = _receipt_digest(receipt)
    store.write(_record_key(key), receipt)
    read_back = store.read(_record_key(key))
    if read_back != receipt:
        raise StoreAdapterError("STORE_WRITE_FAILED")
    return _attach_durable_receipt(
        result,
        locator=_receipt_locator(root, store, key),
        digest=str(receipt["receipt_sha256"]),
        replayed=False,
    )


def _is_partial(payload: dict[str, Any]) -> bool:
    evidence = payload.get("evidence")
    observed = payload.get("observed_files")
    if not isinstance(evidence, dict) or not isinstance(observed, list):
        return False
    files = evidence.get("files")
    if not isinstance(files, list) or not files:
        return False
    expected: dict[str, tuple[str, str]] = {}
    for item in files:
        if not isinstance(item, dict):
            return False
        path = item.get("path")
        before = item.get("before_sha256")
        after = item.get("after_sha256")
        if not all(isinstance(value, str) and value for value in (path, before, after)):
            return False
        expected[str(path)] = (str(before).lower(), str(after).lower())
    observations: dict[str, str] = {}
    for item in observed:
        if not isinstance(item, dict):
            return False
        path = item.get("path")
        digest = item.get("observed_sha256")
        if isinstance(path, str) and isinstance(digest, str):
            observations[path] = digest.lower()
    if set(observations) != set(expected):
        return False
    before_matches = sum(observations[path] == hashes[0] for path, hashes in expected.items())
    after_matches = sum(observations[path] == hashes[1] for path, hashes in expected.items())
    total = len(expected)
    return (0 < before_matches < total) or (0 < after_matches < total)


def _classify(payload: dict[str, Any], *, runtime_exit_code: int) -> tuple[str, bool]:
    verdict = payload.get("verdict")
    runtime_safe = payload.get("safe_to_clear_pending") is True and runtime_exit_code == 0
    if runtime_safe and verdict == "proven-after":
        return "applied", True
    if runtime_safe and verdict == "unchanged-before":
        return "not-applied", True
    if payload.get("status") == "not-found":
        return "not-found", False
    if verdict == "ambiguous-or-diverged" and _is_partial(payload):
        return "partial", False
    return "blocked", False


def _runtime_payload_error(payload: dict[str, Any], key: str, runtime_exit_code: int) -> str | None:
    if payload.get("schema") != _RUNTIME_SCHEMA or payload.get("idempotency_key") != key:
        return "RUNTIME_RECONCILIATION_MALFORMED"
    if payload.get("fail_closed") is not True:
        return "RUNTIME_RECONCILIATION_MALFORMED"
    durability = payload.get("durability")
    if (
        not isinstance(durability, dict)
        or durability.get("status") != "durable"
        or durability.get("verification") != "verified_read_back"
    ):
        return "RUNTIME_RECONCILIATION_NOT_DURABLE"
    verdict = payload.get("verdict")
    if payload.get("safe_to_clear_pending") is True and (
        runtime_exit_code != 0 or verdict not in _SAFE_VERDICTS
    ):
        return "RUNTIME_RECONCILIATION_NOT_SAFE_TO_CLEAR"
    return None


def _requested_evidence_matches(root: Path, requested: object, locator: str) -> bool:
    requested_path = _resolve_evidence(root, requested)
    locator_path = _resolve_evidence(root, locator)
    return requested_path is not None and locator_path is not None and requested_path == locator_path


def _replay_prior(
    root: Path,
    lock: dict[str, Any] | None,
    result: dict[str, Any],
    locator: str,
    digest: str,
) -> dict[str, Any]:
    if result.get("safe_to_clear_pending") is True and lock is not None:
        clear_effect_unknown(str(root), runtime_reconciled=True)
    return _attach_durable_receipt(result, locator=locator, digest=digest, replayed=True)


def run(a: argparse.Namespace) -> int:
    root = Path(a.root).resolve()
    lock = load_effect_unknown_lock(str(root))
    explicit_key = str(a.idempotency_key or "")
    lock_key = str(lock.get("idempotency_key") or "") if lock else ""
    if explicit_key and lock_key and explicit_key != lock_key:
        return _emit(_result("refused", code="EFFECT_UNKNOWN_LOCK_KEY_MISMATCH"), a)
    key = explicit_key or lock_key
    if not key or key == "unknown":
        status = "not-found" if lock is None else "refused"
        code = "EFFECT_RECONCILIATION_NOT_FOUND" if lock is None else "EFFECT_UNKNOWN_LOCK_CAUSAL_ID_MISSING"
        return _emit(_result(status, code=code, outcome="not-found"), a)
    if lock:
        lock_repo = str(lock.get("repo") or "")
        if lock_repo and Path(lock_repo).resolve() != root:
            return _emit(_result("refused", code="EFFECT_UNKNOWN_LOCK_REPO_MISMATCH"), a)

    try:
        store = MapperStoreAdapter(root, _STORE_DOMAIN)
        store_lock = _acquire_store_lock(store, key)
    except StoreAdapterError as exc:
        return _emit(_result("blocked", code="RECONCILIATION_STORE_UNAVAILABLE", detail=str(exc)), a)

    try:
        try:
            prior = _load_receipt(root, store, key)
        except StoreAdapterError as exc:
            return _emit(_result("blocked", code="RECONCILIATION_RECEIPT_CORRUPT", detail=str(exc)), a)
        if prior is not None:
            prior_result, receipt_locator, receipt_digest = prior
            prior_evidence = str(prior_result.get("evidence_locator") or "")
            if not _requested_evidence_matches(root, a.evidence_file, prior_evidence):
                return _emit(_result("refused", code="EVIDENCE_LOCATOR_MISMATCH"), a)
            return _emit(_replay_prior(root, lock, prior_result, receipt_locator, receipt_digest), a)

        if lock is None:
            return _emit(
                _result(
                    "not-found",
                    code="EFFECT_RECONCILIATION_NOT_FOUND",
                    outcome="not-found",
                    idempotency_key=key,
                ),
                a,
            )
        evidence = _resolve_evidence(root, lock.get("evidence_file"))
        requested = _resolve_evidence(root, a.evidence_file)
        if evidence is None or requested is None or evidence != requested:
            return _emit(_result("refused", code="EVIDENCE_LOCATOR_MISMATCH"), a)
        if not evidence.is_file():
            return _emit(_result("refused", code="EVIDENCE_FILE_MISSING_OR_OUTSIDE_REPO"), a)
        evidence_locator = _relative_locator(root, evidence)

        try:
            completed = call_simplicio(
                [
                    "effect",
                    "reconcile",
                    "--idempotency-key",
                    key,
                    "--repo",
                    str(root),
                    "--evidence-file",
                    str(evidence),
                    "--json",
                ],
                capture_output=True,
                timeout=30,
            )
        except Exception as exc:
            return _emit(_result("blocked", code="RUNTIME_RECONCILIATION_UNAVAILABLE", detail=str(exc)), a)
        try:
            payload = json.loads(completed.stdout or "")
        except json.JSONDecodeError:
            return _emit(
                _result(
                    "blocked",
                    code="RUNTIME_RECONCILIATION_MALFORMED",
                    runtime_exit_code=completed.returncode,
                ),
                a,
            )
        if not isinstance(payload, dict):
            return _emit(
                _result(
                    "blocked",
                    code="RUNTIME_RECONCILIATION_MALFORMED",
                    runtime_exit_code=completed.returncode,
                ),
                a,
            )
        invalid = _runtime_payload_error(payload, key, completed.returncode)
        if invalid:
            return _emit(
                _result("blocked", code=invalid, runtime=payload, runtime_exit_code=completed.returncode),
                a,
            )
        outcome, safe = _classify(payload, runtime_exit_code=completed.returncode)
        result = {
            "schema": SCHEMA,
            "status": "reconciled" if safe else ("not-found" if outcome == "not-found" else "unresolved"),
            "outcome": outcome,
            "safe_to_clear_pending": safe,
            "idempotency_key": key,
            "evidence_locator": evidence_locator,
            "verdict": payload.get("verdict"),
            "runtime": payload,
            "runtime_exit_code": completed.returncode,
        }
        try:
            durable = _persist_receipt(root, store, key, evidence_locator, result)
        except StoreAdapterError as exc:
            return _emit(
                _result(
                    "blocked",
                    code="RECONCILIATION_RECEIPT_PERSISTENCE_FAILED",
                    detail=str(exc),
                    outcome="blocked",
                ),
                a,
            )
        if safe:
            clear_effect_unknown(str(root), runtime_reconciled=True)
        return _emit(durable, a)
    finally:
        store.release(store_lock)


def _emit(result: dict[str, Any], a: argparse.Namespace) -> int:
    print(json.dumps(result, sort_keys=True) if a.json else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("safe_to_clear_pending") is True else 1
