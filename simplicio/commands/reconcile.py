"""Safe Dev CLI wrapper for Runtime evidence-file reconciliation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..runtime_bridge import call_simplicio
from ..standalone_migration import clear_effect_unknown, load_effect_unknown_lock

SCHEMA = "simplicio.dev-cli.effect-reconciliation-result/v1"
_SAFE_VERDICTS = {"unchanged-before", "proven-after"}


def _result(status: str, *, code: str | None = None, **payload: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"schema": SCHEMA, "status": status, "safe_to_clear_pending": False}
    if code:
        result["error"] = {"code": code}
    result.update(payload)
    return result


def run(a: argparse.Namespace) -> int:
    root = Path(a.root).resolve()
    lock = load_effect_unknown_lock(str(root))
    if lock is None:
        result = _result("refused", code="EFFECT_UNKNOWN_LOCK_MISSING")
        return _emit(result, a)
    key = str(a.idempotency_key or lock.get("idempotency_key") or "")
    if not key or key == "unknown":
        result = _result("refused", code="EFFECT_UNKNOWN_LOCK_CAUSAL_ID_MISSING")
        return _emit(result, a)
    lock_repo = str(lock.get("repo") or "")
    if lock_repo and Path(lock_repo).resolve() != root:
        result = _result("refused", code="EFFECT_UNKNOWN_LOCK_REPO_MISMATCH")
        return _emit(result, a)
    if a.idempotency_key and a.idempotency_key != lock.get("idempotency_key"):
        result = _result("refused", code="EFFECT_UNKNOWN_LOCK_KEY_MISMATCH")
        return _emit(result, a)
    evidence = Path(a.evidence_file)
    if not evidence.is_absolute():
        evidence = root / evidence
    evidence = evidence.resolve()
    if not evidence.is_relative_to(root) or not evidence.is_file():
        result = _result("refused", code="EVIDENCE_FILE_MISSING_OR_OUTSIDE_REPO")
        return _emit(result, a)
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
        result = _result("blocked", code="RUNTIME_RECONCILIATION_UNAVAILABLE", detail=str(exc))
        return _emit(result, a)
    try:
        payload = json.loads(completed.stdout or "")
    except json.JSONDecodeError:
        result = _result(
            "blocked", code="RUNTIME_RECONCILIATION_MALFORMED", runtime_exit_code=completed.returncode
        )
        return _emit(result, a)
    if not isinstance(payload, dict):
        result = _result(
            "blocked", code="RUNTIME_RECONCILIATION_MALFORMED", runtime_exit_code=completed.returncode
        )
        return _emit(result, a)
    verdict = payload.get("verdict")
    safe = payload.get("safe_to_clear_pending") is True and verdict in _SAFE_VERDICTS
    if not safe:
        result = _result(
            "blocked",
            code="RUNTIME_RECONCILIATION_NOT_SAFE_TO_CLEAR",
            runtime=payload,
            runtime_exit_code=completed.returncode,
        )
        return _emit(result, a)
    clear_effect_unknown(str(root), runtime_reconciled=True)
    result = {
        "schema": SCHEMA,
        "status": "reconciled",
        "safe_to_clear_pending": True,
        "verdict": verdict,
        "runtime": payload,
        "runtime_exit_code": completed.returncode,
    }
    return _emit(result, a)


def _emit(result: dict[str, Any], a: argparse.Namespace) -> int:
    print(json.dumps(result, sort_keys=True) if a.json else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("safe_to_clear_pending") is True else 1
