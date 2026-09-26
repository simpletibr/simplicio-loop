#!/usr/bin/env python3
"""Simplicio client-integration writer.

Durably register the Simplicio MCP server into a coding client's config so the client
can call Simplicio's tools. Stdlib only (json, os, sys, pathlib, tempfile).

Supported clients (idempotent, atomic, safe):
  codex     -> TOML text-block append into ~/.codex/config.toml, guarded by markers
  claude    -> JSON mcpServers.simplicio entry into ~/.claude/settings.json
  copilot   -> best-effort JSON entry if its config dir exists, else skipped
  openclaw  -> best-effort JSON entry if its config dir exists, else skipped

CLI:
  python3 simplicio_init.py <client> [--apply]

DEFAULT IS DRY-RUN: it prints the target path and exactly what WOULD change, without
writing anything. Only --apply writes. This is a safety requirement.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

# Repo root = simplicio-loop root = parents[1] of this file (engine/ -> repo).
REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_SERVER = str(REPO_ROOT / "engine" / "simplicio_tools_server.py")

# Stable across versions — used to detect an existing install for idempotent re-init. Do NOT
# rename (a changed marker makes an upgrade append a duplicate block instead of replacing).
MARK_BEGIN = "# --- simplicio mcp ---"
MARK_END = "# --- end simplicio mcp ---"

# The canonical server entry, reused by every JSON-based client.
SERVER_ENTRY = {
    "command": "python3",
    "args": [MCP_SERVER],
    "env": {"SIMPLICIO_HOME": "~/.simplicio"},
}


def _home() -> Path:
    """Resolve HOME freshly each call so tests can point it at a temp dir."""
    return Path(os.path.expanduser("~"))


def _atomic_write(path: Path, text: str) -> None:
    """Write text to path atomically (temp file in same dir + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".simplicio_init.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _codex_block() -> str:
    """The marker-guarded TOML block appended to ~/.codex/config.toml."""
    args_toml = ", ".join(json.dumps(a) for a in SERVER_ENTRY["args"])
    return (
        f"{MARK_BEGIN}\n"
        "[mcp_servers.simplicio]\n"
        'command = "python3"\n'
        f"args = [{args_toml}]\n"
        "\n"
        "[mcp_servers.simplicio.env]\n"
        'SIMPLICIO_HOME = "~/.simplicio"\n'
        f"{MARK_END}\n"
    )


# --- per-client planners: return (target_path, would_change, change_preview) ---

def plan_codex():
    target = _home() / ".codex" / "config.toml"
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    block = _codex_block()
    if MARK_BEGIN in existing:
        return target, False, block, existing  # already present
    sep = "" if (existing == "" or existing.endswith("\n")) else "\n"
    new_text = existing + sep + ("\n" if existing else "") + block
    return target, True, block, new_text


def _plan_json(target: Path):
    """Generic JSON planner: merge mcpServers.simplicio into a settings file."""
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8") or "{}")
        except (json.JSONDecodeError, ValueError):
            data = {}
    else:
        data = {}
    if not isinstance(data, dict):
        data = {}
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    already = servers.get("simplicio") == SERVER_ENTRY
    servers["simplicio"] = SERVER_ENTRY
    data["mcpServers"] = servers
    new_text = json.dumps(data, indent=2) + "\n"
    preview = json.dumps({"mcpServers": {"simplicio": SERVER_ENTRY}}, indent=2)
    return target, (not already), preview, new_text


def plan_claude():
    return _plan_json(_home() / ".claude" / "settings.json")


def plan_copilot():
    # Best-effort: only touch if the client's config dir already exists.
    cfg_dir = _home() / ".config" / "github-copilot"
    if not cfg_dir.exists():
        return None
    return _plan_json(cfg_dir / "mcp.json")


def plan_openclaw():
    cfg_dir = _home() / ".openclaw"
    if not cfg_dir.exists():
        return None
    return _plan_json(cfg_dir / "settings.json")


PLANNERS = {
    "codex": plan_codex,
    "claude": plan_claude,
    "copilot": plan_copilot,
    "openclaw": plan_openclaw,
}


def run(client: str, apply: bool) -> int:
    planner = PLANNERS.get(client)
    if planner is None:
        print(f"error: unknown client {client!r}. supported: {', '.join(PLANNERS)}")
        return 2

    plan = planner()
    if plan is None:
        print(f"{client}: skipped (not installed)")
        return 0

    target, would_change, preview, new_text = plan

    if not would_change:
        print(f"{client}: already registered at {target} (no change)")
        return 0

    if not apply:
        print(f"DRY-RUN {client}: would write to {target}")
        print("--- begin change preview ---")
        print(preview.rstrip("\n"))
        print("--- end change preview ---")
        print("re-run with --apply to write.")
        return 0

    _atomic_write(target, new_text)
    print(f"{client}: registered Simplicio MCP at {target}")
    return 0


def main(argv) -> int:
    args = [a for a in argv if a != "--apply"]
    apply = "--apply" in argv
    if not args:
        print(__doc__.strip())
        print("\nusage: python3 simplicio_init.py <client> [--apply]")
        print(f"clients: {', '.join(PLANNERS)}")
        return 1
    return run(args[0], apply)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
