"""Codex adapter — MCP required, no invented PreToolUse.

`.codex/hooks.json` is empty. This adapter never reports native interception as
equivalent enforcement. Writes go through a governed MCP/effect path; lifecycle
is a durable self-paced watcher.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "simplicio.host-adapter/v1"
HOST = "codex"
ADAPTER_VERSION = "3.44.2"
CLAIMED_NATIVE_HOOKS: dict[str, str] = {}  # none — do not invent PreToolUse


class AdapterError(RuntimeError):
    """Claimed native hook is missing or a write is unenforceable."""


def _root() -> Path:
    return Path(__file__).resolve().parent


def detect(env: Mapping[str, str] | None = None, root: str | Path | None = None) -> dict[str, Any]:
    environ = env if env is not None else os.environ
    workspace = Path(root).resolve() if root else Path.cwd()
    signals = []
    if environ.get("CODEX_HOME") or environ.get("CODEX"):
        signals.append("env:CODEX")
    if (workspace / ".codex" / "config.toml").is_file():
        signals.append("file:.codex/config.toml")
    if (workspace / "AGENTS.md").is_file():
        signals.append("file:AGENTS.md")
    return {
        "schema": SCHEMA,
        "host": HOST,
        "detected": bool(signals),
        "signals": signals,
        "workspace": str(workspace),
    }


def inspect_hooks(root: str | Path | None = None) -> dict[str, Any]:
    workspace = Path(root).resolve() if root else Path.cwd()
    path = workspace / ".codex" / "hooks.json"
    payload = {}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"malformed": True}
    hooks = payload.get("hooks") if isinstance(payload.get("hooks"), dict) else {}
    return {
        "path": str(path),
        "exists": path.is_file(),
        "hook_names": sorted(hooks),
        "empty": not hooks,
        "malformed": bool(payload.get("malformed")),
    }


def verify_shipped_hooks(root: str | Path | None = None) -> dict[str, Any]:
    if CLAIMED_NATIVE_HOOKS:
        base = Path(root).resolve() if root else _root()
        missing = [name for name, rel in CLAIMED_NATIVE_HOOKS.items() if not (base / rel).is_file()]
        if missing:
            raise AdapterError("claimed Codex hook missing: " + ", ".join(missing))
    return {"schema": SCHEMA, "host": HOST, "verified": True, "present": [], "claimed_native": []}


def capabilities(root: str | Path | None = None) -> dict[str, Any]:
    hooks = inspect_hooks(root)
    native = bool(hooks["hook_names"]) and not hooks["empty"]
    return {
        "schema": SCHEMA,
        "host": HOST,
        "version": ADAPTER_VERSION,
        "loop_drive": "self_paced",
        "native_interception": False,
        "governed_effect_path": True,
        "mcp_required": True,
        "self_paced": True,
        "hooks_inventory": hooks,
        "stages": {
            "SessionStart": {"supported": True, "enforcement": "bootstrap_wrapper"},
            "UserPromptSubmit": {"supported": True, "enforcement": "self_paced"},
            "PreToolUse": {
                "supported": False,
                "enforcement": "unenforceable_native",
                "reason": ".codex/hooks.json has no PreToolUse; do not report as native",
            },
            "PostToolUse": {"supported": True, "enforcement": "mcp_receipt"},
            "Stop": {"supported": True, "enforcement": "self_paced_watcher"},
        },
        "raw_shell_write": "unenforceable" if not native else "hooked",
    }


def diagnose(root: str | Path | None = None) -> dict[str, Any]:
    caps = capabilities(root)
    return {
        "schema": "simplicio.codex-host-diagnosis/v1",
        "native_interception": False,
        "governed_effect_path": True,
        "mcp_required": True,
        "hooks_empty": caps["hooks_inventory"]["empty"],
        "unenforceable_surface": ["raw_shell", "raw_write_tool"],
        "status": "UNVERIFIED" if not caps["hooks_inventory"]["exists"] else "MEASURED_HOOKS_EMPTY",
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
    kind = str(event.get("kind") or event.get("tool") or "")
    if kind in {"shell", "write", "Bash", "Write", "Edit"} and not event.get("via_mcp"):
        receipt.update({
            "decision": "block",
            "reason": "raw_write_unenforceable_without_mcp",
            "governed_effect_path": True,
        })
        return receipt
    if stage in {"SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"}:
        receipt.update({"decision": "continue", "reason": "self_paced_" + stage.lower(), "enforcement": "self_paced"})
        return receipt
    if stage == "PreToolUse":
        receipt.update({
            "decision": "block",
            "reason": "native_pretooluse_absent",
            "enforcement": "unenforceable_native",
        })
        return receipt
    receipt.update({"decision": "block", "reason": "unknown_lifecycle_stage"})
    return receipt


def watcher_state(path: str | Path, event: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Durable self-paced watcher — survives turn end; not fire-and-forget."""
    store = Path(path)
    store.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    if store.is_file():
        try:
            current = json.loads(store.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    queue = list(current.get("queue") or [])
    if event:
        queue.append(dict(event))
    payload = {
        "schema": "simplicio.codex-self-paced-watcher/v1",
        "durable": True,
        "fire_and_forget": False,
        "queue": queue,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    store.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload
