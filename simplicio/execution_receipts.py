"""Actionable fail-closed receipts for execution-mode negotiation."""

from __future__ import annotations

from typing import Any


def execution_mode_blocker(profile: Any) -> dict[str, Any]:
    code = profile.reason_code
    blocker: dict[str, Any] = {
        "code": code,
        "message": "execution-mode negotiation failed closed",
        "retryable": False,
        "next_action": None,
    }
    if code == "INCOMPATIBLE_RUNTIME":
        runtime = profile.runtime
        reason = runtime.get("reason")
        blocker.update(
            {
                "message": f"compatible Runtime capability handshake required ({reason or 'unknown'})",
                "retryable": True,
                "missing_capabilities": (
                    [runtime["capability"]] if not runtime.get("capability_available") else []
                ),
                "runtime_version": runtime.get("version"),
                "compatible_dev_cli_version": ">=0.18.1",
                "next_action": "run `simplicio-py runtime verify --json`, then retry",
            }
        )
    elif code == "CONTEXT_REQUIRED":
        blocker.update(
            {
                "message": "canonical Mapper context snapshot required",
                "retryable": True,
                "next_action": "provide --context-snapshot and retry",
            }
        )
    elif code == "COORDINATOR_CONTEXT_REQUIRED":
        from .execution_mode import ACQUIRE_COORDINATOR_CONTEXT_COMMAND, COORDINATOR_CONTEXT_LIFECYCLE

        blocker.update(
            {
                "message": "coordinator attempt, lease, fence, and context handle are required",
                "retryable": True,
                "next_action": f"run `{ACQUIRE_COORDINATOR_CONTEXT_COMMAND}`",
                "lifecycle": list(COORDINATOR_CONTEXT_LIFECYCLE),
            }
        )
    elif code == "RUNTIME_SINK_REQUIRED":
        blocker.update(
            {
                "message": "Runtime effect sink required for integrated mutation",
                "retryable": True,
                "next_action": "configure the Runtime effect sink and retry",
            }
        )
    return blocker
