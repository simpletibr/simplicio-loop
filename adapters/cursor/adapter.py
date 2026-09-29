"""Cursor adapter — T4/T3 mapping with honest Claude-parity gaps.

Native hooks this adapter ships: Session bootstrap (workspace), T4
beforeShellExecution, afterAgentResponse, stop. Cursor does not expose a
reliable T3 before-edit hook, so PreToolUse-edit is self-paced, never
reported as native enforcement.
"""
from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "simplicio.host-adapter/v1"
HOST = "cursor"
ADAPTER_VERSION = "3.45.1"

NATIVE_HOOKS = {
    "Stop": "hooks/stop.py",
    "PostToolUse": "hooks/after_agent_response.py",
    "PreToolUse.shell": "hooks/before_shell_execution.py",
}
SELF_PACED = {
    "SessionStart": "self_paced_workspace_open",
    "UserPromptSubmit": "self_paced_prompt",
    "PreToolUse.edit": "self_paced_t3_edit",
}
_MUTATING_SHELL = re.compile(
    r"(?i)\b(rm\s+-rf|git\s+push(\s+--force|\s+-f)|git\s+reset\s+--hard|"
    r"drop\s+table|terraform\s+destroy)\b"
)


class AdapterError(RuntimeError):
    """Claimed native hook is missing."""


def _root() -> Path:
    return Path(__file__).resolve().parent


def detect(env: Mapping[str, str] | None = None, root: str | Path | None = None) -> dict[str, Any]:
    environ = env if env is not None else os.environ
    workspace = Path(root).resolve() if root else Path.cwd()
    signals = []
    if environ.get("CURSOR_TRACE_ID") or environ.get("CURSOR"):
        signals.append("env:CURSOR")
    if (workspace / ".cursor-plugin" / "plugin.json").is_file():
        signals.append("file:.cursor-plugin/plugin.json")
    if (workspace / ".cursor").is_dir():
        signals.append("dir:.cursor")
    return {
        "schema": SCHEMA,
        "host": HOST,
        "detected": bool(signals),
        "signals": signals,
        "workspace": str(workspace),
    }


def verify_shipped_hooks(root: str | Path | None = None) -> dict[str, Any]:
    base = Path(root).resolve() if root else _root()
    missing = [
        stage for stage, rel in NATIVE_HOOKS.items() if not (base / rel).is_file()
    ]
    if missing:
        raise AdapterError("claimed Cursor hook missing: " + ", ".join(missing))
    return {"schema": SCHEMA, "host": HOST, "verified": True, "present": list(NATIVE_HOOKS)}


def capabilities() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "host": HOST,
        "version": ADAPTER_VERSION,
        "loop_drive": "stop+afterAgentResponse",
        "native_interception": True,
        "self_paced": True,
        "claude_parity": {
            "SessionStart": "self_paced",
            "UserPromptSubmit": "self_paced",
            "PreToolUse.shell": "native",
            "PreToolUse.edit": "unsupported_native",
            "PostToolUse": "native",
            "Stop": "native",
        },
        "stages": {
            "Stop": {"supported": True, "enforcement": "native_hook", "hook": NATIVE_HOOKS["Stop"]},
            "PostToolUse": {"supported": True, "enforcement": "native_hook", "hook": NATIVE_HOOKS["PostToolUse"]},
            "PreToolUse.shell": {
                "supported": True,
                "enforcement": "native_hook",
                "hook": NATIVE_HOOKS["PreToolUse.shell"],
            },
            "PreToolUse.edit": {
                "supported": False,
                "enforcement": "self_paced",
                "reason": "Cursor has no T3 before-edit hook in this adapter",
            },
            "SessionStart": {"supported": False, "enforcement": "self_paced"},
            "UserPromptSubmit": {"supported": False, "enforcement": "self_paced"},
        },
    }


def decide(event: Mapping[str, Any], *, timeout: bool = False) -> dict[str, Any]:
    stage = str(event.get("hook_event_name") or event.get("stage") or "").strip()
    receipt = {
        "schema": "simplicio.host-hook-decision/v1",
        "host": HOST,
        "stage": stage,
        "correlation_id": str(event.get("correlation_id") or uuid.uuid4()),
        "decided_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if timeout:
        receipt.update({"decision": "block", "reason": "hook_timeout_does_not_authorize"})
        return receipt
    if stage in {"beforeShellExecution", "PreToolUse.shell", "PreToolUse"}:
        command = str((event.get("tool_input") or {}).get("command") or event.get("command") or "")
        if _MUTATING_SHELL.search(command):
            receipt.update({"decision": "block", "reason": "mutating_shell_requires_effect"})
            return receipt
        receipt.update({"decision": "continue", "reason": "t4_shell_observed"})
        return receipt
    if stage in {"afterAgentResponse", "PostToolUse"}:
        receipt.update({"decision": "continue", "reason": "receipt_recorded", "apply_duplicated": False})
        return receipt
    if stage in {"stop", "Stop"}:
        receipt.update({
            "decision": "continue" if event.get("evidence_complete") else "refeed",
            "reason": "stop_converge" if event.get("evidence_complete") else "stop_refeed",
        })
        return receipt
    if stage in SELF_PACED or stage in {"SessionStart", "UserPromptSubmit", "beforeEdit", "PreToolUse.edit"}:
        receipt.update({
            "decision": "continue",
            "reason": "self_paced_fallback",
            "enforcement": "self_paced",
            "native": False,
        })
        return receipt
    receipt.update({"decision": "block", "reason": "unknown_lifecycle_stage"})
    return receipt
