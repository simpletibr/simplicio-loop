"""Best-effort Orca Dev worktree-card lifecycle projection (**client opt-in only**).

Not part of the default loop path. The runner only enters this module when the
client requested the ``orca`` integration (see ``client_integrations.py``):

* ``SIMPLICIO_LOOP_CLIENT_INTEGRATIONS=orca``
* ``.simplicio-loop/client-integrations.json`` listing ``"orca"``
* legacy ``SIMPLICIO_LOOP_ORCA_LIFECYCLE_SYNC=1``

When enabled, uses the public ``orca worktree`` CLI and scopes writes to the
active worktree after ``worktree current``. Outside Orca: explicit no-op.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Callable, Dict, Mapping, Sequence

from .client_integrations import integration_enabled


ORCA_STATUS_BY_LIFECYCLE = {
    "DISCOVERED": "todo",
    "CLAIMED": "in-progress",
    "PLANNED": "in-progress",
    "IN_PROGRESS": "in-progress",
    "VERIFYING": "in-progress",
    "BLOCKED": "in-progress",
    "PAUSED_NETWORK": "in-progress",
    "AWAITING_DECISION": "in-progress",
    "PR_OPEN": "in-review",
    "MERGE_READY": "in-review",
    "MERGED": "completed",
    "CLOSING": "completed",
    "CLOSE_PENDING_RECONCILIATION": "in-progress",
    "CLOSED": "completed",
    "RELEASED": "completed",
}
CLEANUP_RECEIPT_SCHEMA = "simplicio.worktree-cleanup-receipt/v1"


def cleanup_receipt(state: Mapping[str, Any] | None = None,
                    event: Mapping[str, Any] | None = None,
                    context: Mapping[str, Any] | None = None,
                    decision: str = "skip", reason: str = "") -> Dict[str, Any]:
    """Build a secret-free cleanup/activity receipt for the active Orca worktree."""
    state, event, context = dict(state or {}), dict(event or {}), dict(context or {})
    return {
        "schema": CLEANUP_RECEIPT_SCHEMA,
        "worktree_id": str(context.get("id") or state.get("worktree_id") or event.get("worktree_id") or ""),
        "terminal_handle": str(context.get("terminal_handle") or state.get("terminal_handle") or event.get("terminal_handle") or ""),
        "lease_owner": str(context.get("lease_owner") or state.get("lease_owner") or event.get("lease_owner") or ""),
        "cleanup_decision": str(decision or "skip"),
        "reason": str(reason or ""),
    }


def lifecycle_to_orca_status(state: str) -> str:
    return ORCA_STATUS_BY_LIFECYCLE.get(str(state or "").upper(), "in-progress")


# Canonical 8-state Orca projection per the loop protocol (#loop-canonical-states):
#   intake/mapping -> Todo, planning -> Planning, executing -> In progress,
#   validating/watching -> Validating, delivering -> In review, done -> Done,
#   blocked -> Blocked, repeated terminal failures -> Quarantined.
# This is the source-of-truth mapping the Orca card projection MUST use; the
# legacy `lifecycle_to_orca_status` above is kept for backward compatibility.
ORCA_CANONICAL_STATUS_BY_LIFECYCLE = {
    "DISCOVERED": "Todo",
    "CLAIMED": "Todo",
    "MAPPING": "Todo",
    "INTAKE": "Todo",
    "PLANNED": "Planning",
    "IN_PROGRESS": "In progress",
    "VERIFYING": "Validating",
    "WATCHING": "Validating",
    "PR_OPEN": "In review",
    "MERGE_READY": "In review",
    "DELIVERING": "In review",
    "MERGED": "Done",
    "CLOSING": "Done",
    "CLOSED": "Done",
    "RELEASED": "Done",
    "BLOCKED": "Blocked",
    "PAUSED_NETWORK": "Blocked",
    "AWAITING_DECISION": "Blocked",
    "QUARANTINED": "Quarantined",
}


def lifecycle_to_orca_canonical_status(state: str) -> str:
    """Map a loop lifecycle state to its canonical Orca card status (8 states)."""
    return ORCA_CANONICAL_STATUS_BY_LIFECYCLE.get(str(state or "").upper(), "In progress")


def _disabled() -> bool:
    """True unless the client explicitly requested the Orca integration."""
    return not integration_enabled("orca")


def _command() -> str:
    return str(os.environ.get("SIMPLICIO_LOOP_ORCA_COMMAND") or "orca").strip() or "orca"


def _run_default(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([_command(), *args], capture_output=True, text=True, timeout=20)


def sync_orca_status(state: Mapping[str, Any], event: Mapping[str, Any], *,
                     runner: Callable[..., subprocess.CompletedProcess[str]] = _run_default,
                     canonical: bool = False) -> Dict[str, Any]:
    """Update only the current Orca worktree card, or return an explicit skip.

    When ``canonical`` is True (or ``SIMPLICIO_LOOP_ORCA_CANONICAL=1``), the
    card status uses the loop protocol's 8-state projection
    (``lifecycle_to_orca_canonical_status``) instead of the legacy generic
    mapping. Defaults to the legacy mapping for backward compatibility.
    """
    if _disabled():
        receipt = cleanup_receipt(state, event, decision="skip", reason="disabled")
        return {"status": "skipped", "reason": "disabled", "cleanup_receipt": receipt, **receipt}
    current = runner(["worktree", "current", "--json"])
    if current.returncode != 0:
        reason = "not_in_orca"
        receipt = cleanup_receipt(state, event, decision="skip", reason=reason)
        return {"status": "skipped", "reason": reason, "detail": (current.stderr or "").strip()[:240],
                "cleanup_receipt": receipt, **receipt}
    try:
        context = json.loads(current.stdout or "{}")
    except (TypeError, ValueError):
        receipt = cleanup_receipt(state, event, decision="skip", reason="invalid_orca_context")
        return {"status": "skipped", "reason": "invalid_orca_context", "cleanup_receipt": receipt, **receipt}
    if not isinstance(context, dict) or not context.get("id"):
        receipt = cleanup_receipt(state, event, context if isinstance(context, dict) else {},
                                  decision="skip", reason="no_active_worktree")
        return {"status": "skipped", "reason": "no_active_worktree", "cleanup_receipt": receipt, **receipt}

    lifecycle = str(event.get("lifecycle_state") or event.get("state") or state.get("phase") or "IN_PROGRESS").upper()
    use_canonical = canonical or str(os.environ.get("SIMPLICIO_LOOP_ORCA_CANONICAL") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    status = lifecycle_to_orca_canonical_status(lifecycle) if use_canonical else lifecycle_to_orca_status(lifecycle)
    run_id = str(state.get("run_id") or "")
    message = str(event.get("message") or event.get("reason") or "").strip().replace("\n", " ")
    comment = f"Simplicio Loop — {lifecycle}"
    if run_id:
        comment += f" · run {run_id}"
    if message:
        comment += f" · {message[:180]}"
    updated = runner([
        "worktree", "set", "--worktree", "active", "--comment", comment,
        "--workspace-status", status, "--json",
    ])
    if updated.returncode != 0:
        receipt = cleanup_receipt(state, event, context, decision="skip", reason="orca_update_failed")
        return {"status": "failed", "reason": "orca_update_failed", "detail": (updated.stderr or "").strip()[:240],
                "cleanup_receipt": receipt, **receipt}
    decision = str(event.get("cleanup_decision") or "skip")
    reason = str(event.get("reason") or event.get("cleanup_reason") or "synced")
    receipt = cleanup_receipt(state, event, context, decision=decision, reason=reason)
    return {
        "status": "synced", "worktree_id": str(context.get("id")),
        "lifecycle_state": lifecycle, "workspace_status": status, "comment": comment,
        "terminal_handle": receipt["terminal_handle"], "lease_owner": receipt["lease_owner"],
        "cleanup_decision": receipt["cleanup_decision"], "reason": receipt["reason"],
        "cleanup_receipt": receipt,
    }
