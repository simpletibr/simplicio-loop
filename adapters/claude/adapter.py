"""Claude Code adapter — lifecycle translation, no business rules.

The adapter converts native Claude hook payloads into Plugin v1 events, calls
the Loop/Runtime facade, and returns allow/block/continue. Missing claimed
hooks fail closed. Runtime absence is explicit degraded mode, never silent
fail-open.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from simplicio_loop.prompt_bridge import enrich_user_prompt

SCHEMA = "simplicio.host-adapter/v1"
HOST = "claude"
ADAPTER_VERSION = "3.43.14"
PLUGIN_NAME = "simplicio-loop"

LIFECYCLE_STAGES = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
)

SHIPPED_HOOKS = {
    "SessionStart": "hooks/session_start.py",
    "UserPromptSubmit": "hooks/user_prompt_submit.py",
    "PreToolUse": "hooks/pre_tool_use.py",
    "PostToolUse": "hooks/post_tool_use.py",
    "Stop": "hooks/stop.py",
}

READ_TOOLS = frozenset({
    "Read", "Grep", "Glob", "LS", "NotebookRead", "WebFetch", "WebSearch",
})
WRITE_TOOLS = frozenset({
    "Edit", "Write", "StrReplace", "ApplyPatch", "NotebookEdit",
})
SHELL_TOOLS = frozenset({"Bash", "Shell", "BashTool"})
_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|authorization:\s*bearer)\s*[:=]\s*\S+"
)
_INJECTION_RE = re.compile(
    r"(?i)(ignore (all )?(previous|prior) (instructions|rules)|"
    r"disregard (the )?(system|safety)|"
    r"<promise>\s*HACK)"
)
_MUTATING_SHELL = re.compile(
    r"(?i)\b(rm\s+-rf|git\s+push(\s+--force|\s+-f)|git\s+reset\s+--hard|"
    r"drop\s+table|terraform\s+destroy)\b"
)


class AdapterError(RuntimeError):
    """Claimed hook or descriptor is missing; fail closed."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _adapter_root() -> Path:
    return Path(__file__).resolve().parent


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def detect(env: Mapping[str, str] | None = None, root: str | Path | None = None) -> dict[str, Any]:
    """Detect Claude Code from environment and workspace files."""
    environ = env if env is not None else os.environ
    workspace = Path(root).resolve() if root else Path.cwd()
    signals = []
    if environ.get("CLAUDECODE") or environ.get("CLAUDE_CODE"):
        signals.append("env:CLAUDECODE")
    if environ.get("CLAUDE_PLUGIN_ROOT"):
        signals.append("env:CLAUDE_PLUGIN_ROOT")
    settings = workspace / ".claude" / "settings.json"
    if settings.is_file():
        signals.append("file:.claude/settings.json")
    plugin = workspace / ".claude-plugin" / "marketplace.json"
    if plugin.is_file():
        signals.append("file:.claude-plugin/marketplace.json")
    return {
        "schema": SCHEMA,
        "host": HOST,
        "detected": bool(signals),
        "signals": signals,
        "workspace": str(workspace),
    }


def verify_shipped_hooks(root: str | Path | None = None) -> dict[str, Any]:
    """Fail closed when a claimed lifecycle hook file is missing."""
    base = Path(root).resolve() if root else _adapter_root()
    missing = []
    present = []
    for stage, relative in SHIPPED_HOOKS.items():
        path = base / relative
        if path.is_file():
            present.append(stage)
        else:
            missing.append({"stage": stage, "path": str(path)})
    if missing:
        raise AdapterError(
            "claimed Claude hook missing: "
            + ", ".join(item["stage"] + "=" + item["path"] for item in missing)
        )
    return {
        "schema": SCHEMA,
        "host": HOST,
        "verified": True,
        "stages": list(LIFECYCLE_STAGES),
        "present": present,
    }


def descriptor(root: str | Path | None = None) -> dict[str, Any]:
    """Version + digest for the plugin package; must match plugin/.claude-plugin."""
    base = Path(root).resolve() if root else _adapter_root()
    payload = {
        "schema": "simplicio.plugin-descriptor/v1",
        "name": PLUGIN_NAME,
        "host": HOST,
        "version": ADAPTER_VERSION,
        "entrypoint": "simplicio-loop=simplicio_loop.cli:main",
        "lifecycle": list(LIFECYCLE_STAGES),
        "hooks": dict(SHIPPED_HOOKS),
    }
    digest_source = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["digest"] = "sha256:" + hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    on_disk = _read_json(base / "descriptor.json")
    if on_disk and (on_disk.get("version") != payload["version"] or on_disk.get("digest") != payload["digest"]):
        raise AdapterError(
            "plugin descriptor version/digest drift: "
            f"adapter={payload['version']} disk={on_disk.get('version')}"
        )
    return payload


def capabilities() -> dict[str, Any]:
    """Honest capability matrix — only claim hooks this adapter ships."""
    return {
        "schema": SCHEMA,
        "host": HOST,
        "version": ADAPTER_VERSION,
        "loop_drive": "Stop",
        "native_interception": True,
        "self_paced": False,
        "mcp_optional": True,
        "prompt_enrichment": {
            "schema": "simplicio.prompt-enrichment-receipt/v1",
            "runtime_route": "passthrough",
            "status": "skipped",
            "reason_code": "prompt_enrichment_removed",
            "bounded": True,
        },
        "stages": {
            stage: {
                "supported": True,
                "enforcement": "native_hook",
                "hook": SHIPPED_HOOKS[stage],
            }
            for stage in LIFECYCLE_STAGES
        },
        "read_fast_path": sorted(READ_TOOLS),
        "governed_writes": sorted(WRITE_TOOLS | SHELL_TOOLS),
    }


def _env_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def handshake(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """SessionStart handshake. Runtime missing is degraded, not fail-open."""
    environ = env if env is not None else os.environ
    runtime = environ.get("SIMPLICIO_RUNTIME_BIN") or "simplicio"
    available = _env_truthy(environ.get("SIMPLICIO_RUNTIME_AVAILABLE"))
    if not available:
        # Presence on PATH is a hint only; never pretend MCP ran.
        path = environ.get("PATH", "")
        available = any(
            (Path(part) / runtime).exists() or (Path(part) / f"{runtime}.exe").exists()
            for part in path.split(os.pathsep) if part
        )
    desc = descriptor()
    status = "ready" if available else "degraded"
    return {
        "schema": "simplicio.host-handshake/v1",
        "host": HOST,
        "status": status,
        "runtime_available": available,
        "runtime_mode": "runtime-backed" if available else "standalone",
        "fail_open": False,
        "manifest_digest": desc["digest"],
        "version": ADAPTER_VERSION,
        "correlation_id": str(uuid.uuid4()),
        "checked_at": _now(),
    }


def _tool_name(event: Mapping[str, Any]) -> str:
    return str(event.get("tool_name") or event.get("tool") or "").strip()


def _command(event: Mapping[str, Any]) -> str:
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), Mapping) else {}
    return str(tool_input.get("command") or event.get("command") or "")


def _text_blob(event: Mapping[str, Any]) -> str:
    parts = [
        str(event.get("prompt") or ""),
        str(event.get("user_prompt") or ""),
        _command(event),
        json.dumps(event.get("tool_input") or {}, ensure_ascii=False),
    ]
    return "\n".join(parts)


def decide(event: Mapping[str, Any], *, timeout: bool = False) -> dict[str, Any]:
    """Translate one Claude hook event into allow/block/continue."""
    stage = str(event.get("hook_event_name") or event.get("stage") or "").strip()
    correlation = str(event.get("correlation_id") or uuid.uuid4())
    receipt = {
        "schema": "simplicio.host-hook-decision/v1",
        "host": HOST,
        "stage": stage,
        "correlation_id": correlation,
        "decided_at": _now(),
    }
    if stage not in LIFECYCLE_STAGES:
        receipt.update({"decision": "block", "reason": "unknown_lifecycle_stage"})
        return receipt
    if timeout:
        receipt.update({
            "decision": "block",
            "reason": "hook_timeout_does_not_authorize",
        })
        return receipt

    blob = _text_blob(event)
    if _INJECTION_RE.search(blob) or _SECRET_RE.search(blob):
        receipt.update({"decision": "block", "reason": "secret_or_injection"})
        return receipt

    if stage == "SessionStart":
        shake = handshake(event.get("env") if isinstance(event.get("env"), Mapping) else None)
        receipt.update({
            "decision": "continue",
            "reason": "handshake_" + shake["status"],
            "handshake": shake,
        })
        return receipt

    if stage == "UserPromptSubmit":
        prompt = str(event.get("prompt") or event.get("user_prompt") or "")
        event_env = event.get("env") if isinstance(event.get("env"), Mapping) else None
        enrichment = enrich_user_prompt(
            prompt,
            session_id=str(event.get("session_id") or event.get("sessionId") or ""),
            repo=event.get("cwd") or event.get("workspace"),
            env=event_env,
        )
        prompt_receipt = enrichment["receipt"]
        receipt.update({
            "decision": "continue",
            "reason": "prompt_passthrough",
            "route": enrichment["route"],
            "route_decision": enrichment["route_decision"],
            "portable_route": enrichment["portable_route"],
            "prompt": prompt,
            "prompt_enrichment": prompt_receipt,
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": enrichment["additional_context"],
            },
        })
        return receipt

    if stage == "PreToolUse":
        tool = _tool_name(event)
        if not tool:
            receipt.update({"decision": "block", "reason": "unknown_tool"})
            return receipt
        if tool in READ_TOOLS:
            receipt.update({"decision": "allow", "reason": "read_fast_path", "tool": tool})
            return receipt
        command = _command(event)
        if tool in SHELL_TOOLS and _MUTATING_SHELL.search(command):
            receipt.update({"decision": "block", "reason": "mutating_shell_requires_effect", "tool": tool})
            return receipt
        if tool in WRITE_TOOLS or tool in SHELL_TOOLS:
            receipt.update({
                "decision": "continue",
                "reason": "effect_intent",
                "tool": tool,
                "effect": {"schema": "simplicio.effect-intent/v1", "tool": tool, "authorized": False},
            })
            return receipt
        receipt.update({"decision": "block", "reason": "unknown_tool", "tool": tool})
        return receipt

    if stage == "PostToolUse":
        receipt.update({
            "decision": "continue",
            "reason": "receipt_recorded",
            "apply_duplicated": False,
        })
        return receipt

    # Stop
    complete = bool(event.get("evidence_complete"))
    receipt.update({
        "decision": "continue" if complete else "refeed",
        "reason": "stop_converge" if complete else "stop_refeed",
    })
    return receipt
