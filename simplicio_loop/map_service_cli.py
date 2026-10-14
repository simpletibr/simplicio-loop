"""Standalone Map Service CLI with explicit fallback receipts.

The commands are standalone. A future adapter can provide a
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

from .map_service_gc import DEFAULT_KEEP, STALE_AFTER_SECONDS, apply_gc, plan_gc, startup_gc
from .map_service_git import GitIdentityError
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


def _gc(repo: str, *, dry_run: bool, keep: int, max_age: float, as_json: bool) -> int:
    """List (``dry_run``) or remove what is safe to remove from the repository-central stores."""
    schema = "simplicio.map-gc/v1"
    try:
        plan = plan_gc(repo, keep=keep, max_age=max_age)
    except (GitIdentityError, OSError, subprocess.SubprocessError):
        return _emit({
            "schema": "simplicio.map-service-cli/v1", "command": "gc", "status": "READY",
            "removed": [], "fallback": True, "reason_code": "standalone_no_store",
        }, as_json)
    result = apply_gc(plan) if not dry_run else None
    items = [item.to_dict() for item in plan.items]
    payload = {
        "schema": schema, "command": "gc", "status": "READY", "dry_run": dry_run,
        "keep": plan.keep, "max_age_seconds": plan.max_age, "items": items,
        "would_free_bytes": plan.would_free_bytes,
        "removed": result.removed if result else [],
        "freed_bytes": result.removed_bytes if result else 0,
        "errors": plan.errors + (result.errors if result else []),
    }
    if as_json:
        return _emit(payload, True)
    print("map-service gc%s: %d item(s), %s bytes %s" % (
        " (dry run)" if dry_run else "", len(items),
        payload["would_free_bytes"] if dry_run else payload["freed_bytes"],
        "would be freed" if dry_run else "freed",
    ))
    for item in items:
        if item["action"] == "remove":
            print("  %s %s %s (%d bytes, %s)" % (
                "would remove" if dry_run else "remove", item["kind"], item["path"],
                item["bytes"], item["reason"],
            ))
    return 0


def run(command: str, *, repo: str = ".", mode: str = "canonical", tree_hash: str = "", files: Optional[list[str]] = None, trace_id: str = "", as_json: bool = False, dry_run: bool = False, keep: int = DEFAULT_KEEP, max_age: float = STALE_AFTER_SECONDS) -> int:
    if command == "gc":
        return _gc(repo, dry_run=dry_run, keep=keep, max_age=max_age, as_json=as_json)
    startup_gc(repo)
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
    for command in ("verify", "doctor"):
        child = subparsers.add_parser(command, help="map-service %s" % command)
        child.add_argument("--repo", default=".", help="repository root")
        child.add_argument("--json", action="store_true")
    gc = subparsers.add_parser(
        "gc", help="remove stale map scratch, orphan locks and old bases (--dry-run lists them)"
    )
    gc.add_argument("--repo", default=".", help="repository root")
    gc.add_argument("--dry-run", action="store_true", help="list what would be removed, remove nothing")
    gc.add_argument(
        "--keep", type=int, default=DEFAULT_KEEP,
        help="newest bases to keep besides those a live worktree references (default %d)" % DEFAULT_KEEP,
    )
    gc.add_argument(
        "--max-age", type=float, default=STALE_AFTER_SECONDS,
        help="seconds without a write before scratch or a lock is stale (default %d)" % STALE_AFTER_SECONDS,
    )
    gc.add_argument("--json", action="store_true")
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
        dry_run=getattr(args, "dry_run", False), keep=getattr(args, "keep", DEFAULT_KEEP),
        max_age=getattr(args, "max_age", STALE_AFTER_SECONDS),
    )
