"""Passthrough prompt boundary.

Issue #1284: Loop does not import simplicio-prompt, does not shell out to
Runtime, and does not inject skill bodies. The host already has the Mapper
handoff; enrichment is skipped with an auditable receipt.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .route_decision import AUTHORITY_LOCKED, ROUTE_SCHEMA

RECEIPT_SCHEMA = "simplicio.prompt-enrichment-receipt/v1"
REASON_CODE = "prompt_enrichment_removed"


class RuntimeResult(Protocol):
    returncode: int
    stdout: str
    stderr: str


RuntimeRunner = Callable[[list[str], float, Mapping[str, str]], RuntimeResult]
BodyLoader = Callable[[str], str | None]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _receipt_block(receipt: Mapping[str, Any]) -> str:
    return f"<!-- {RECEIPT_SCHEMA}\n{_canonical_json(receipt)}\n-->"


def enrich_user_prompt(
    prompt: str,
    *,
    session_id: str = "",
    repo: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    runner: RuntimeRunner | None = None,
    body_loader: BodyLoader | None = None,
) -> dict[str, Any]:
    """Return the original user prompt unchanged. Enrichment is skipped."""
    del session_id, repo, env, runner, body_loader
    original = prompt
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "status": "skipped",
        "reason_code": REASON_CODE,
        "fallback": {
            "used": False,
            "reason_code": REASON_CODE,
            "visible": True,
            "profile": "removed",
        },
        "authority": dict(AUTHORITY_LOCKED),
        "injection": {"detected": False, "elevated": False},
        "materialized_handles": [],
        "selected_handles": [],
        "context_truncated": False,
        "context_bytes": 0,
    }
    route = {
        "schema": ROUTE_SCHEMA,
        "decision_id": "loop-route/prompt-enrichment-removed",
        "lane": "interactive",
        "reason": REASON_CODE,
        "capability": "none",
        "intent": "passthrough",
        "selected_handles": [],
        "max_skills": 0,
        "max_bytes": 0,
        "runtime_status": "unavailable",
        "authority": dict(AUTHORITY_LOCKED),
        "policy_version": "simplicio-loop-route-policy/v1",
        "provenance": {"producer": "simplicio-loop", "source": "passthrough"},
    }
    return {
        "prompt": original,
        "route": route,
        "route_decision": route,
        "portable_route": {},
        "receipt": receipt,
        "additional_context": _receipt_block(receipt),
    }


def reset_cache() -> None:
    """Kept for adapter/test imports. Enrichment no longer caches skill bodies."""
    return None


__all__ = [
    "AUTHORITY_LOCKED",
    "RECEIPT_SCHEMA",
    "REASON_CODE",
    "ROUTE_SCHEMA",
    "enrich_user_prompt",
    "reset_cache",
]
