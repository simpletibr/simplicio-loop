"""Standalone Map Service CLI with explicit fallback receipts.

The commands are usable before a Hub is available. A future Hub adapter can provide a
store object; the command surface and receipt schema remain unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .map_service_status import default_status_path, load_status_file

BUILD_RELATIVE = (".simplicio-loop/orchestrator", "map", "build.json")


def _repo_head(repo: str) -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except OSError:
        pass
    return "standalone-unknown-head"


def _path(repo: str) -> Path:
    return Path(repo).joinpath(*BUILD_RELATIVE)


def _emit(payload: Dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("map-service %s: %s" % (payload.get("command", "status"), payload.get("status", "UNKNOWN")))
        for key in ("mode", "tree_hash", "trace_id", "fallback", "removed"):
            if key in payload:
                print("  %s: %s" % (key, payload[key]))
    return 0 if payload.get("status") not in {"BLOCKED", "INVALID"} else 1


def session_status(repo: str, status_file: str = "", as_json: bool = False) -> int:
    """Report counters from a real map-service session without inventing state."""
    path = Path(status_file) if status_file else default_status_path(repo)
    try:
        payload = load_status_file(path)
    except (OSError, ValueError) as exc:
        payload = None
        error = str(exc)
    else:
        error = ""
    if payload is None:
        print(json.dumps({
            "schema": "simplicio.map-service-status/v1",
            "status": "UNAVAILABLE",
            "reason_code": "status_file_missing" if not error else "status_file_invalid",
            "path": str(path),
            "error": error,
        }, ensure_ascii=False, indent=2))
        return 1
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        counters = payload.get("counters", {})
        watchers = payload.get("watchers", {})
        print("\n".join([
            "map-service status (" + str(path) + ")",
            "  cache_hits:    " + str(counters.get("cache_hits", 0)),
            "  builds:        " + str(counters.get("builds", 0)),
            "  waits:         " + str(counters.get("waits", 0)),
            "  invalidations: " + str(counters.get("invalidations", 0)),
            "  watchers:      " + str(watchers.get("watchers", 0)),
            "  pending:       " + str(watchers.get("pending", 0)),
        ]))
    return 0


def run(command: str, *, repo: str = ".", mode: str = "canonical", tree_hash: str = "", files: Optional[list[str]] = None, trace_id: str = "", as_json: bool = False) -> int:
    target = _path(repo)
    if command == "status":
        if not target.exists():
            return _emit({"schema": "simplicio.map-service-cli/v1", "command": command, "status": "FALLBACK", "fallback": True, "reason_code": "hub_unavailable", "path": str(target)}, as_json)
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return _emit({"schema": "simplicio.map-service-cli/v1", "command": command, "status": "INVALID", "error": str(exc), "path": str(target)}, as_json)
        payload.update({"command": command, "fallback": True, "path": str(target)})
        return _emit(payload, as_json)
    if command == "build":
        tree_hash = str(tree_hash or _repo_head(repo))
        trace_id = str(trace_id or hashlib.sha256((tree_hash + mode).encode("utf-8")).hexdigest()[:16])
        payload = {
            "schema": "simplicio.map-service-cli/v1", "command": command, "status": "READY",
            "mode": mode, "tree_hash": tree_hash, "files": sorted(files or []), "trace_id": trace_id,
            "fallback": True, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(str(temporary), str(target))
        return _emit(payload, as_json)
    if command == "verify":
        if not target.exists():
            return _emit({"schema": "simplicio.map-service-cli/v1", "command": command, "status": "BLOCKED", "reason_code": "build_missing", "fallback": True}, as_json)
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
            ok = payload.get("schema") == "simplicio.map-service-cli/v1" and bool(payload.get("trace_id"))
        except (OSError, ValueError):
            ok = False
        return _emit({"schema": "simplicio.map-service-cli/v1", "command": command, "status": "READY" if ok else "INVALID", "fallback": True, "path": str(target)}, as_json)
    if command == "gc":
        # Without a Hub-owned snapshot store, standalone GC is deliberately a no-op and
        # reports that fact instead of deleting unknown files.
        return _emit({"schema": "simplicio.map-service-cli/v1", "command": command, "status": "READY", "removed": [], "fallback": True, "reason_code": "standalone_no_store"}, as_json)
    if command == "doctor":
        return _emit({"schema": "simplicio.map-service-cli/v1", "command": command, "status": "READY", "fallback": not target.exists(), "build_receipt": str(target) if target.exists() else None}, as_json)
    raise ValueError("unknown map command: %s" % command)


def configure_commands(subparsers: argparse._SubParsersAction) -> None:
    status = subparsers.add_parser(
        "status", help="report cache hit/build/wait/invalidate counters from a running session"
    )
    status.add_argument("--repo", default=".", help="repository root")
    status.add_argument(
        "--status-file", default="",
        help="explicit status file (default: <repo>/.simplicio-loop/orchestrator/map/status.json)",
    )
    status.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    for command in ("verify", "gc", "doctor"):
        child = subparsers.add_parser(command, help="map-service %s" % command)
        child.add_argument("--repo", default=".", help="repository root")
        child.add_argument("--json", action="store_true")
    build = subparsers.add_parser("build", help="build a canonical or worktree map receipt")
    build.add_argument("--repo", default=".")
    build.add_argument("--mode", choices=("canonical", "overlay"), default="canonical")
    build.add_argument("--tree-hash", default="")
    build.add_argument("--file", dest="files", action="append", default=[])
    build.add_argument("--trace-id", default="")
    build.add_argument("--json", action="store_true")


def dispatch(args: argparse.Namespace) -> int:
    if args.map_command == "status":
        return session_status(args.repo, args.status_file, args.json)
    return run(
        args.map_command, repo=args.repo, mode=getattr(args, "mode", "canonical"),
        tree_hash=getattr(args, "tree_hash", ""), files=getattr(args, "files", []),
        trace_id=getattr(args, "trace_id", ""), as_json=args.json,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="simplicio-loop map")
    sub = parser.add_subparsers(dest="command", required=True)
    command_help = {
        "status": "report map-service counters and watcher state",
        "verify": "verify the current map receipt",
        "gc": "garbage-collect standalone map artifacts",
        "doctor": "check map-service readiness and fallback state",
    }
    for command in ("status", "verify", "gc", "doctor"):
        child = sub.add_parser(command, help=command_help[command])
        child.add_argument("--repo", default=".")
        child.add_argument("--json", action="store_true")
    build = sub.add_parser("build", help="build a canonical or overlay map receipt")
    build.add_argument("--repo", default=".")
    build.add_argument("--mode", choices=("canonical", "overlay"), default="canonical")
    build.add_argument("--tree-hash", default="")
    build.add_argument("--file", dest="files", action="append", default=[])
    build.add_argument("--trace-id", default="")
    build.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    return run(args.command, repo=args.repo, mode=getattr(args, "mode", "canonical"), tree_hash=getattr(args, "tree_hash", ""), files=getattr(args, "files", []), trace_id=getattr(args, "trace_id", ""), as_json=args.json)
