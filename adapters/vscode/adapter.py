"""VS Code / Copilot adapter — extension/MCP bridge, no fake PreToolUse."""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "simplicio.host-adapter/v1"
HOST = "vscode"
ADAPTER_VERSION = "3.43.14"
PUBLIC_APIS = (
    "workspace_open",
    "mcp.json",
    "tasks.json",
    "copilot-instructions.md",
    "status_bar",
)
CLAIMED_NATIVE_HOOKS: dict[str, str] = {}


class AdapterError(RuntimeError):
    """Claimed hook missing or unmanaged mutation presented as enforced."""


def detect(env: Mapping[str, str] | None = None, root: str | Path | None = None) -> dict[str, Any]:
    environ = env if env is not None else os.environ
    workspace = Path(root).resolve() if root else Path.cwd()
    signals = []
    if environ.get("VSCODE_PID") or environ.get("TERM_PROGRAM") == "vscode":
        signals.append("env:VSCODE")
    if (workspace / ".vscode" / "mcp.json").is_file():
        signals.append("file:.vscode/mcp.json")
    if (workspace / ".github" / "copilot-instructions.md").is_file():
        signals.append("file:.github/copilot-instructions.md")
    return {
        "schema": SCHEMA,
        "host": HOST,
        "detected": bool(signals),
        "signals": signals,
        "workspace": str(workspace),
        "trusted": environ.get("VSCODE_WORKSPACE_TRUST") != "untrusted",
    }


def verify_shipped_hooks(root: str | Path | None = None) -> dict[str, Any]:
    if CLAIMED_NATIVE_HOOKS:
        raise AdapterError("vscode adapter claimed a native hook it does not ship")
    return {"schema": SCHEMA, "host": HOST, "verified": True, "present": [], "claimed_native": []}


def capabilities() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "host": HOST,
        "version": ADAPTER_VERSION,
        "loop_drive": "self_paced",
        "native_interception": False,
        "governed_effect_path": True,
        "mcp_required": True,
        "self_paced": True,
        "public_apis": list(PUBLIC_APIS),
        "stages": {
            "SessionStart": {"supported": True, "enforcement": "workspace_open"},
            "UserPromptSubmit": {"supported": True, "enforcement": "self_paced"},
            "PreToolUse": {
                "supported": False,
                "enforcement": "unenforceable_native",
                "reason": "VS Code/Copilot has no PreToolUse API in this adapter",
            },
            "PostToolUse": {"supported": True, "enforcement": "mcp_receipt"},
            "Stop": {"supported": True, "enforcement": "self_paced"},
        },
        "residual_unmanaged_mutation": True,
        "status_bar_states": ["bound", "unbound", "blocked"],
    }


def decide(event: Mapping[str, Any], *, timeout: bool = False) -> dict[str, Any]:
    stage = str(event.get("hook_event_name") or event.get("stage") or "").strip()
    receipt = {
        "schema": "simplicio.host-hook-decision/v1",
        "host": HOST,
        "stage": stage,
        "correlation_id": str(event.get("correlation_id") or uuid.uuid4()),
        "decided_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "native_interception": False,
    }
    if timeout:
        receipt.update({"decision": "block", "reason": "hook_timeout_does_not_authorize"})
        return receipt
    if event.get("unmanaged_mutation"):
        receipt.update({
            "decision": "block",
            "reason": "residual_unmanaged_mutation",
            "residual": True,
            "false_pass": False,
        })
        return receipt
    if not event.get("via_mcp") and str(event.get("kind") or "") in {"Write", "Edit", "shell"}:
        receipt.update({"decision": "block", "reason": "mutation_requires_runtime_mcp", "residual": True})
        return receipt
    if stage == "PreToolUse":
        receipt.update({"decision": "block", "reason": "native_pretooluse_absent", "enforcement": "unenforceable_native"})
        return receipt
    if stage in {"SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"}:
        receipt.update({"decision": "continue", "reason": "self_paced_" + stage.lower()})
        return receipt
    receipt.update({"decision": "block", "reason": "unknown_lifecycle_stage"})
    return receipt


def doctor(root: str | Path | None = None) -> dict[str, Any]:
    workspace = Path(root).resolve() if root else Path.cwd()
    mcp = (workspace / ".vscode" / "mcp.json").is_file()
    return {
        "schema": "simplicio.vscode-host-doctor/v1",
        "plugin_bound": mcp,
        "state": "bound" if mcp else "unbound",
        "native_interception": False,
        "residual_unmanaged_mutation": True,
    }
