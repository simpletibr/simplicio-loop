"""mcp_server.py — simplicio-dev-cli as an MCP stdio server (issue #89 P0).

Ports the `ai-memory` (JesseBrown1980/ai-memory) pattern of exposing an
agent-CLI's capabilities as native Model Context Protocol tools, so any MCP
client (Claude Code, Codex, Cursor, VS Code) can call `dev_cli_edit`,
`dev_cli_validate`, and `dev_cli_memory` directly instead of shelling out.

This is a **stdlib-only** JSON-RPC 2.0 dispatcher — no `mcp` SDK dependency.
Per this repo's "no new dependency without confirmation" rule (AGENTS.md),
adding the official `mcp` PyPI package needs a human decision; a minimal
hand-rolled server over the documented stdio transport (newline-delimited
JSON-RPC 2.0 messages, see https://modelcontextprotocol.io) gets the real
P0 capability without that dependency. If/when the `mcp` package is
approved, this module is the natural place to swap the transport for the
SDK's `mcp.server.stdio` — the tool handlers below do not change.

Transport: one JSON object per line on stdin, one JSON object per line on
stdout (matching stdio framing used by simple MCP servers). `handle_message`
is the pure, directly-testable core; `serve_stdio` is the thin I/O loop
around it.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

from .observability import emit_event

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "simplicio-dev-cli"


def _server_version() -> str:
    try:
        from . import __version__

        return __version__
    except ImportError:  # pragma: no cover - defensive
        return "0.0.0"


# --------------------------------------------------------------------------- #
# Tool handlers
# --------------------------------------------------------------------------- #


def _tool_dev_cli_edit(args: dict[str, Any]) -> dict[str, Any]:
    from .mechanical_edit import execute_plan_json

    plan = args.get("plan")
    if isinstance(plan, dict):
        plan_text = json.dumps(plan)
    else:
        plan_text = str(plan or "")
    root = args.get("root", ".")
    apply = bool(args.get("apply", False))
    return execute_plan_json(plan_text, root=root, apply=apply)


def _tool_dev_cli_validate(args: dict[str, Any]) -> dict[str, Any]:
    from .pipeline import validate_generated_output

    output = str(args.get("output", ""))
    bound_paths = args.get("bound_paths")
    mode = args.get("mode")
    result = validate_generated_output(output, bound_paths=bound_paths, mode=mode)
    return {"ok": result.ok, "reason": result.reason, "hints": result.hints}


def _tool_dev_cli_memory(args: dict[str, Any]) -> dict[str, Any]:
    from .memory_store import init_memory, recall_memory, store_memory

    action = args.get("action")
    root = args.get("dir")
    if action == "init":
        return init_memory(root=root)
    if action == "store":
        return store_memory(
            str(args.get("topic", "")),
            str(args.get("content", "")),
            tags=args.get("tags"),
            root=root,
            actor=args.get("actor"),
        )
    if action == "recall":
        limit = int(args.get("limit", 5))
        return {"results": recall_memory(str(args.get("query", "")), limit=limit, root=root)}
    raise ValueError(f"unknown memory action: {action!r} (expected init|store|recall)")


TOOLS: dict[str, dict[str, Any]] = {
    "dev_cli_edit": {
        "description": (
            "Apply (or dry-run) a simplicio.mechanical-edit/v1 plan against a "
            "repo — deterministic, zero-LLM file editing."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "description": "repo root", "default": "."},
                "plan": {"description": "mechanical-edit plan, JSON object or string"},
                "apply": {"type": "boolean", "default": False},
            },
            "required": ["plan"],
        },
        "handler": _tool_dev_cli_edit,
    },
    "dev_cli_validate": {
        "description": "Validate a generated diff/output against the pipeline's contract checks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "output": {"type": "string"},
                "bound_paths": {"type": "array", "items": {"type": "string"}},
                "mode": {"type": "string", "enum": ["strict", "diff"]},
            },
            "required": ["output"],
        },
        "handler": _tool_dev_cli_validate,
    },
    "dev_cli_memory": {
        "description": (
            "Cross-vendor memory handoff (markdown + git under ~/.simplicio/memory): "
            "init the store, store a note, or recall notes by keyword."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["init", "store", "recall"]},
                "dir": {"type": "string", "description": "override memory dir"},
                "topic": {"type": "string"},
                "content": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["action"],
        },
        "handler": _tool_dev_cli_memory,
    },
}


# --------------------------------------------------------------------------- #
# JSON-RPC 2.0 dispatch
# --------------------------------------------------------------------------- #


def _rpc_result(msg_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _rpc_error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one parsed JSON-RPC 2.0 request/notification.

    Returns the response dict to write back, or None for notifications
    (no `id`) and for methods that intentionally produce no reply. Never
    raises — protocol/tool errors become JSON-RPC error responses or
    `isError` tool results, matching MCP's error-reporting contract.
    """
    msg_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    if method == "initialize":
        return _rpc_result(
            msg_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": _server_version()},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _rpc_result(
            msg_id,
            {
                "tools": [
                    {
                        "name": name,
                        "description": spec["description"],
                        "inputSchema": spec["inputSchema"],
                    }
                    for name, spec in TOOLS.items()
                ]
            },
        )
    if method == "tools/call":
        return _handle_tool_call(msg_id, params)

    if msg_id is None:
        return None  # unknown notification: ignore, don't error a one-way message
    return _rpc_error(msg_id, -32601, f"method not found: {method}")


def _handle_tool_call(msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    args = params.get("arguments") or {}
    spec = TOOLS.get(name)
    if spec is None:
        return _rpc_error(msg_id, -32602, f"unknown tool: {name!r}")
    handler: Callable[[dict[str, Any]], dict[str, Any]] = spec["handler"]
    # Issue #107: structured event for the unified evidence flow. Routes
    # through observability.emit_event, which is stderr/JSONL-only by
    # design (see #106) — never stdout, so this cannot corrupt the MCP
    # frame stream. `root` is only passed through when the tool call
    # itself carried one (dev_cli_edit/dev_cli_memory), so a stray call
    # against a root-less tool still gets its stderr line without trying
    # to write a bogus `.simplicio/events.jsonl` path.
    event_root = args.get("root") or args.get("dir")
    try:
        payload = handler(args)
        emit_event("edit_applied" if name == "dev_cli_edit" else "handoff", {"tool": name}, root=event_root)
        return _rpc_result(
            msg_id,
            {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False},
        )
    except Exception as exc:  # tool-level failure -> isError result, not a transport error
        emit_event(
            "validation_fail",
            {"tool": name, "error": str(exc)},
            level="warning",
            root=event_root,
        )
        return _rpc_result(
            msg_id,
            {"content": [{"type": "text", "text": str(exc)}], "isError": True},
        )


def serve_stdio(*, stdin=None, stdout=None) -> None:
    """Blocking newline-delimited JSON-RPC loop over stdin/stdout.

    Runs until stdin closes (EOF) or is interrupted. Malformed JSON on a
    line is answered with a JSON-RPC parse error (id null) rather than
    crashing the server.
    """
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response = _rpc_error(None, -32700, "parse error: invalid JSON")
        else:
            response = handle_message(message)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
