#!/usr/bin/env python3
"""Simplicio native MCP server — stdio, JSON-RPC 2.0, stdlib only.

A Model Context Protocol server that clients connect to over stdin/stdout, one
JSON message per line (newline-delimited JSON-RPC 2.0). It exposes three tools:

  - simplicio_compress  deterministic, fail-open text compression
  - simplicio_retrieve  read a key from ~/.simplicio/memory.json
  - simplicio_stats     read the lifetime totals from ~/.simplicio/proxy_savings.json

Run it as the command a stdio MCP client launches:

    python3 engine/simplicio_mcp.py

Everything is deterministic and offline. No network, no third-party deps.
"""
import json
import os
import re
import sys
from pathlib import Path

__version__ = "1.0.0"

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "simplicio"

DATA_DIR = Path(os.environ.get("SIMPLICIO_HOME", Path(os.path.expanduser("~")) / ".simplicio"))
MEMORY_FILE = DATA_DIR / "memory.json"
SAVINGS_FILE = DATA_DIR / "proxy_savings.json"


def _runner_action(args):
    """Run one explicit action through the persisted local runner state machine."""
    from simplicio_loop import runner
    action = str(args.get("action", "")).strip().lower()
    repo = str(args.get("repo", "."))
    run_id = str(args.get("run_id", "")).strip()
    if action == "arm":
        task = str(args.get("task", "")).strip()
        if not task:
            raise ValueError("task is required for action=arm")
        payload = runner.arm_run(repo, task, str(args.get("delivery", "verified")), int(args.get("max_iterations", 12)))
    elif action == "status":
        payload = runner.read_status(repo, run_id or None)
    elif action == "resume":
        if not run_id: raise ValueError("run_id is required for action=resume")
        payload = runner.change_phase(repo, run_id, "awaiting_decision", "resume requested via MCP")
    elif action == "tick":
        if not run_id: raise ValueError("run_id is required for action=tick")
        payload = runner.execute_operator(repo, run_id, task_index=int(args.get("task_index", 1)))
    elif action == "batch":
        if not run_id: raise ValueError("run_id is required for action=batch")
        values = args.get("task_indices")
        if values is not None and (not isinstance(values, list) or not all(isinstance(v, int) for v in values)):
            raise ValueError("task_indices must be an array of integers")
        payload = runner.execute_operator_batch(repo, run_id, values,
            max_workers=int(args.get("max_workers", 0)) or None,
            retry_budget=int(args.get("retry_budget", 3)),
            auto_fan_out=bool(args.get("auto_fan_out", True)))
    elif action == "cancel":
        if not run_id: raise ValueError("run_id is required for action=cancel")
        payload = runner.change_phase(repo, run_id, "cancelled", "cancel requested via MCP")
    else:
        raise ValueError("action must be one of: arm, status, resume, tick, batch, cancel")
    return json.dumps(payload, ensure_ascii=False)

_TRAILING_WS = re.compile(r"[ \t]+(?=\n)")
_MANY_BLANKS = re.compile(r"\n{3,}")


# --- deterministic compression (mirrors engine/simplicio_engine.py, fail-open) ---

def _algo_whitespace(t):
    """Strip trailing whitespace on each line; collapse 3+ blank lines to one."""
    return _MANY_BLANKS.sub("\n\n", _TRAILING_WS.sub("", t))


def _algo_dedup_lines(t):
    """Replace runs of consecutive identical (non-empty) lines with a marker."""
    out, prev, marked = [], None, False
    for line in t.split("\n"):
        if line == prev and line.strip():
            if not marked:
                out.append("[x2+ repeated]")
                marked = True
            continue
        prev, marked = line, False
        out.append(line)
    return "\n".join(out)


def _algo_minify_json(t):
    """If the whole text is a standalone JSON object/array, minify it."""
    s = t.strip()
    if (s[:1], s[-1:]) in (("{", "}"), ("[", "]")) and len(s) > 40:
        try:
            return json.dumps(json.loads(s), separators=(",", ":"), ensure_ascii=False)
        except (ValueError, TypeError):
            return t
    return t


_PIPELINE = [_algo_whitespace, _algo_dedup_lines, _algo_minify_json]


def _compress_text(text):
    """Run the deterministic pipeline; keep the result only if it actually shrank."""
    if not text:
        return text
    out = text
    for algo in _PIPELINE:
        try:
            out = algo(out)
        except (ValueError, TypeError, re.error):
            pass
    return out if len(out) <= len(text) else text


# --- tool implementations -------------------------------------------------------

def _tokens(n_chars):
    """Cheap token estimate: ~4 chars per token."""
    return n_chars // 4


def tool_compress(args):
    text = args.get("text", "")
    if not isinstance(text, str):
        text = str(text)
    try:
        compressed = _compress_text(text)
    except Exception:
        compressed = text  # fail-open
    saved = _tokens(len(text)) - _tokens(len(compressed))
    if saved < 0:
        saved = 0
    note = "[simplicio_compress] {} -> {} chars (~{} tokens saved)".format(
        len(text), len(compressed), saved
    )
    return compressed + "\n\n" + note


def tool_retrieve(args):
    key = args.get("key", "")
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as fh:
            store = json.load(fh)
        if isinstance(store, dict) and key in store:
            value = store[key]
            if not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False)
            return value
    except (OSError, ValueError):
        pass
    return "not found: no value stored under key {!r}".format(key)


def tool_stats(_args):
    zeros = {"tokens_saved": 0, "requests": 0, "compression_savings_usd": 0}
    try:
        with open(SAVINGS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        lifetime = data.get("lifetime")
        if isinstance(lifetime, dict):
            return json.dumps({
                "tokens_saved": lifetime.get("tokens_saved", 0),
                "requests": lifetime.get("requests", 0),
                "compression_savings_usd": lifetime.get("compression_savings_usd", 0),
            }, ensure_ascii=False)
    except (OSError, ValueError):
        pass
    return json.dumps(zeros, ensure_ascii=False)


TOOLS = [
    {
        "name": "simplicio_compress",
        "description": "Deterministically compress text (collapse trailing whitespace, fold "
                       "3+ blank lines, mark consecutive duplicate lines, minify standalone "
                       "JSON). Fail-open: returns the original text on any error. Appends a note "
                       "with the estimated tokens saved.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to compress."}
            },
            "required": ["text"],
        },
    },
    {
        "name": "simplicio_retrieve",
        "description": "Retrieve the value stored under a key in ~/.simplicio/memory.json "
                       "(a JSON object of key -> value). Returns a not-found message if the key "
                       "or the file is absent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Memory key to look up."}
            },
            "required": ["key"],
        },
    },
    {
        "name": "simplicio_stats",
        "description": "Return the lifetime savings totals (tokens_saved, requests, "
                       "compression_savings_usd) from ~/.simplicio/proxy_savings.json, or zeros "
                       "if the file is absent.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "simplicio_runner",
        "description": "Drive an explicit local runner action: arm, status, resume, tick, batch, or cancel.",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["arm", "status", "resume", "tick", "batch", "cancel"]},
            "repo": {"type": "string"}, "task": {"type": "string"}, "run_id": {"type": "string"},
            "delivery": {"type": "string"}, "max_iterations": {"type": "integer", "minimum": 1},
            "task_index": {"type": "integer", "minimum": 1},
            "task_indices": {"type": "array", "items": {"type": "integer", "minimum": 1}},
            "max_workers": {"type": "integer", "minimum": 1}, "retry_budget": {"type": "integer", "minimum": 0},
            "auto_fan_out": {"type": "boolean"},
        }, "required": ["action"]},
    },
]

def _typed_runner_action(name, args):
    """Typed MCP aliases share the persisted CLI runner implementation."""
    from simplicio_loop import runner
    repo = str(args.get("repo", "."))
    if name == "task.compile":
        from simplicio_loop.task_contract import compile_many
        task = str(args.get("task", "")).strip()
        if not task:
            raise ValueError("task is required")
        return compile_many(task, source_path="mcp://task")
    if name == "run.start":
        task = str(args.get("task", "")).strip()
        if not task:
            raise ValueError("task is required")
        path = Path(task)
        if not path.is_file():
            root = Path(repo).resolve() / ".simplicio/orchestrator" / "mcp-tasks"
            root.mkdir(parents=True, exist_ok=True)
            path = root / ("task-" + __import__("hashlib").sha256(task.encode()).hexdigest()[:16] + ".md")
            path.write_text(task, encoding="utf-8")
        return runner.conduct_run(repo, str(path), str(args.get("delivery", "verified")), int(args.get("max_iterations", 12)))
    if name == "run.status":
        return runner.read_status(repo, str(args.get("run_id", "")))
    if name == "run.tick":
        return runner.execute_operator(repo, str(args["run_id"]), int(args.get("task_index", 1)))
    if name == "run.verify":
        return runner.verify_run(repo, str(args["run_id"]))
    if name == "run.resume":
        return runner.change_phase(repo, str(args["run_id"]), "awaiting_decision", "resume requested via MCP")
    if name == "run.cancel":
        return runner.change_phase(repo, str(args["run_id"]), "cancelled", "cancel requested via MCP")
    raise ValueError("unknown typed runner tool")


_TYPED_TOOLS = {
    "task.compile": {"description": "Compile raw task markdown into a task contract.", "required": ["task"]},
    "run.start": {"description": "Arm, execute, and independently verify a task.", "required": ["task"]},
    "run.status": {"description": "Read persisted runner state.", "required": ["run_id"]},
    "run.tick": {"description": "Execute one planned task.", "required": ["run_id"]},
    "run.verify": {"description": "Run independent watcher and delivery verification.", "required": ["run_id"]},
    "run.resume": {"description": "Resume a non-terminal run.", "required": ["run_id"]},
    "run.cancel": {"description": "Cancel a non-terminal run.", "required": ["run_id"]},
}
for _name, _spec in _TYPED_TOOLS.items():
    TOOLS.append({"name": _name, "description": _spec["description"], "inputSchema": {"type": "object", "properties": {"repo": {"type": "string"}, "task": {"type": "string"}, "run_id": {"type": "string"}, "delivery": {"type": "string"}, "max_iterations": {"type": "integer"}, "task_index": {"type": "integer"}}, "required": _spec["required"]}})


_DISPATCH = {
    "simplicio_compress": tool_compress,
    "simplicio_retrieve": tool_retrieve,
    "simplicio_stats": tool_stats,
    "simplicio_runner": _runner_action,
}


# --- JSON-RPC plumbing ----------------------------------------------------------

def _result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle(msg):
    """Dispatch one JSON-RPC request. Returns a response dict, or None for notifications."""
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    # Notifications (no id) get no response.
    if req_id is None and method != "initialize":
        return None

    if method == "initialize":
        return _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "capabilities": {"tools": {}},
        })

    if method == "tools/list":
        return _result(req_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name in _TYPED_TOOLS:
            try:
                text = json.dumps(_typed_runner_action(name, args), ensure_ascii=False)
            except Exception as exc:
                text = "tool error: {}".format(exc)
            return _result(req_id, {"content": [{"type": "text", "text": text}]})
        fn = _DISPATCH.get(name)
        if fn is None:
            return _error(req_id, -32602, "unknown tool: {}".format(name))
        try:
            text = fn(args)
        except Exception as exc:  # fail-open: never crash the server on a tool
            text = "tool error: {}".format(exc)
        return _result(req_id, {"content": [{"type": "text", "text": text}]})

    if method == "ping":
        return _result(req_id, {})

    if req_id is None:
        return None
    return _error(req_id, -32601, "method not found: {}".format(method))


def serve():
    """Read newline-delimited JSON-RPC from stdin, write responses to stdout."""
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except (ValueError, TypeError):
            continue  # skip malformed input
        if not isinstance(msg, dict):
            continue
        try:
            resp = handle(msg)
        except Exception as exc:
            resp = _error(msg.get("id"), -32603, "internal error: {}".format(exc))
        if resp is not None:
            out.write(json.dumps(resp, ensure_ascii=False) + "\n")
            out.flush()


if __name__ == "__main__":
    serve()
