"""Grok / xAI adapter — tool-calling harness, no default API or credentials."""
from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "simplicio.host-adapter/v1"
HOST = "grok"
ADAPTER_VERSION = "3.44.2"
ALLOWED_TOOLS = frozenset({
    "simplicio_map",
    "simplicio_search",
    "simplicio_memory",
    "simplicio_gate",
    "simplicio_edit",
    "simplicio_validate",
    "simplicio_exec",
})
_SECRET_RE = re.compile(r"(?i)(api[_-]?key|xai[_-]?key|authorization|secret|token)\s*[:=]\s*\S+")
CLAIMED_NATIVE_HOOKS: dict[str, str] = {}


class AdapterError(RuntimeError):
    """Unknown tool or credential leakage."""


def detect(env: Mapping[str, str] | None = None, root: str | Path | None = None) -> dict[str, Any]:
    environ = env if env is not None else os.environ
    workspace = Path(root).resolve() if root else Path.cwd()
    signals = []
    if environ.get("GROK") or environ.get("XAI_PROFILE"):
        signals.append("env:GROK")
    if (workspace / ".grok").is_dir() or (Path.home() / ".grok").is_dir():
        signals.append("dir:.grok")
    if (workspace / "AGENTS.md").is_file():
        signals.append("file:AGENTS.md")
    return {
        "schema": SCHEMA,
        "host": HOST,
        "detected": bool(signals),
        "signals": signals,
        "workspace": str(workspace),
        "live_api": environ.get("SIMPLICIO_GROK_LIVE") == "1",
    }


def verify_shipped_hooks(root: str | Path | None = None) -> dict[str, Any]:
    if CLAIMED_NATIVE_HOOKS:
        raise AdapterError("grok adapter claimed a native hook it does not ship")
    return {"schema": SCHEMA, "host": HOST, "verified": True, "claimed_native": []}


def capabilities() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "host": HOST,
        "version": ADAPTER_VERSION,
        "loop_drive": "self_paced",
        "native_interception": False,
        "self_paced": True,
        "mcp_optional": True,
        "stores_credentials": False,
        "default_live_api": False,
        "profiles": ["xai_native", "openai_compatible", "offline_fixture"],
        "allowed_tools": sorted(ALLOWED_TOOLS),
        "stages": {
            "SessionStart": {"supported": True, "enforcement": "self_paced"},
            "UserPromptSubmit": {"supported": True, "enforcement": "self_paced"},
            "PreToolUse": {"supported": True, "enforcement": "tool_schema_gate"},
            "PostToolUse": {"supported": True, "enforcement": "receipt"},
            "Stop": {"supported": True, "enforcement": "self_paced"},
        },
        "live_status": "UNVERIFIED",
    }


def redact(value: str) -> str:
    return _SECRET_RE.sub(lambda m: m.group(1) + "=***", value or "")


def normalize_tool_calls(calls: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    normalized = []
    rejected = []
    for index, raw in enumerate(calls):
        name = str(raw.get("name") or raw.get("tool") or "").strip()
        call_id = str(raw.get("id") or raw.get("tool_call_id") or f"call-{index}")
        if name not in ALLOWED_TOOLS:
            rejected.append({
                "id": call_id,
                "name": name,
                "reason": "unknown_tool",
                "repair": "use a Simplicio tool from the bounded catalog; never fall back to shell",
            })
            continue
        if name in {"simplicio_edit", "simplicio_exec"} and not raw.get("via_runtime", True):
            rejected.append({
                "id": call_id,
                "name": name,
                "reason": "mutation_requires_runtime",
            })
            continue
        normalized.append({
            "id": call_id,
            "name": name,
            "arguments": raw.get("arguments") or raw.get("args") or {},
        })
    return {
        "schema": "simplicio.grok-tool-bundle/v1",
        "accepted": normalized,
        "rejected": rejected,
        "shell_fallback": False,
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
        "tokens": event.get("provider_tokens"),
        "tokens_reason": None if event.get("provider_tokens") is not None else "provider_tokens_absent",
    }
    if timeout:
        receipt.update({"decision": "block", "reason": "hook_timeout_does_not_authorize"})
        return receipt
    blob = redact(str(event.get("prompt") or "") + str(event.get("arguments") or ""))
    if "***" in blob and _SECRET_RE.search(str(event.get("prompt") or "")):
        receipt.update({"decision": "block", "reason": "credential_redacted"})
        return receipt
    if stage == "PreToolUse":
        bundle = normalize_tool_calls(event.get("tool_calls") or [event])
        if bundle["rejected"] and not bundle["accepted"]:
            receipt.update({"decision": "block", "reason": "unknown_or_ungoverned_tool", "bundle": bundle})
            return receipt
        receipt.update({"decision": "continue", "reason": "bounded_tool_bundle", "bundle": bundle})
        return receipt
    if stage in {"SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"}:
        receipt.update({"decision": "continue", "reason": "self_paced_" + stage.lower()})
        return receipt
    receipt.update({"decision": "block", "reason": "unknown_lifecycle_stage"})
    return receipt
