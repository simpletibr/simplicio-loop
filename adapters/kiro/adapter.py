"""Kiro adapter — steering/specs + honest hook fallback."""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "simplicio.host-adapter/v1"
HOST = "kiro"
ADAPTER_VERSION = "3.48.1"
CLAIMED_NATIVE_HOOKS: dict[str, str] = {}


class AdapterError(RuntimeError):
    """Claimed hook missing, or spec close attempted without evidence."""


def detect(env: Mapping[str, str] | None = None, root: str | Path | None = None) -> dict[str, Any]:
    environ = env if env is not None else os.environ
    workspace = Path(root).resolve() if root else Path.cwd()
    signals = []
    if environ.get("KIRO") or environ.get("KIRO_HOME"):
        signals.append("env:KIRO")
    if (workspace / ".kiro" / "steering").is_dir():
        signals.append("dir:.kiro/steering")
    if (workspace / ".kiro" / "settings" / "mcp.json").is_file():
        signals.append("file:.kiro/settings/mcp.json")
    return {
        "schema": SCHEMA,
        "host": HOST,
        "detected": bool(signals),
        "signals": signals,
        "workspace": str(workspace),
    }


def inspect_hooks(root: str | Path | None = None) -> dict[str, Any]:
    workspace = Path(root).resolve() if root else Path.cwd()
    hooks_dir = workspace / ".kiro" / "hooks"
    files = sorted(p.name for p in hooks_dir.glob("*") if p.is_file()) if hooks_dir.is_dir() else []
    return {"path": str(hooks_dir), "present": files, "empty": not files}


def verify_shipped_hooks(root: str | Path | None = None) -> dict[str, Any]:
    if CLAIMED_NATIVE_HOOKS:
        raise AdapterError("kiro adapter claimed a native hook it does not ship")
    return {"schema": SCHEMA, "host": HOST, "verified": True, "claimed_native": []}


def capabilities(root: str | Path | None = None) -> dict[str, Any]:
    hooks = inspect_hooks(root)
    native = bool(hooks["present"])
    return {
        "schema": SCHEMA,
        "host": HOST,
        "version": ADAPTER_VERSION,
        "loop_drive": "self_paced",
        "native_interception": native,
        "self_paced": True,
        "mcp_optional": True,
        "hooks_inventory": hooks,
        "stages": {
            "SessionStart": {"supported": True, "enforcement": "workspace_config"},
            "UserPromptSubmit": {"supported": True, "enforcement": "spec_task"},
            "PreToolUse": {
                "supported": native,
                "enforcement": "native_hook" if native else "self_paced",
                "reason": None if native else "no Kiro hook files shipped",
            },
            "PostToolUse": {"supported": True, "enforcement": "mcp_receipt"},
            "Stop": {"supported": True, "enforcement": "self_paced"},
        },
        "spec_is_not_sot": True,
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
    if event.get("close_spec") and event.get("runtime_receipt") != "MEASURED":
        receipt.update({
            "decision": "block",
            "reason": "spec_cannot_close_without_runtime_receipt",
            "spec_is_not_sot": True,
        })
        return receipt
    if stage == "PreToolUse" and not event.get("native_hook_present"):
        receipt.update({"decision": "continue", "reason": "self_paced_fallback", "native": False})
        return receipt
    if stage in {"SessionStart", "UserPromptSubmit", "PostToolUse", "Stop", "PreToolUse"}:
        receipt.update({"decision": "continue", "reason": "kiro_" + (stage or "event").lower()})
        return receipt
    receipt.update({"decision": "block", "reason": "unknown_lifecycle_stage"})
    return receipt


def drift(root: str | Path | None = None) -> dict[str, Any]:
    workspace = Path(root).resolve() if root else Path.cwd()
    steering = workspace / ".kiro" / "steering"
    present = steering.is_dir() and any(steering.glob("*.md"))
    return {
        "schema": "simplicio.kiro-config-drift/v1",
        "steering_present": present,
        "repair": "scripts/install.sh kiro" if not present else None,
        "status": "ok" if present else "drift",
    }
