"""Loop agent-slot facade with MapperStore as the only persistence authority.

The former local registry is intentionally gone.  This module keeps the public
Loop API and CLI stable while routing lifecycle operations through the
MapperStore operations adapter; the old local route fails closed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

from .mapper_agent_slots import MapperAgentSlotRegistry


SCHEMA = "simplicio.loop-agent-slots/v1"
RECEIPT_SCHEMA = "simplicio.loop-agent-slot-receipt/v1"
TERMINAL_STATES = frozenset(("completed", "shutdown"))


class AgentSlotError(RuntimeError):
    """Base error for invalid or unavailable slot operations."""


class AgentSlotValidationError(AgentSlotError):
    """The requested slot record is invalid."""


class AgentSlotRegistry(MapperAgentSlotRegistry):
    """Compatibility name for the MapperStore-backed slot registry."""

    def __init__(
        self,
        path: Path,
        *,
        capacity: int = 6,
        retry_limit: int = 1,
        adapter: Any | None = None,
    ) -> None:
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
            raise AgentSlotValidationError("capacity must be a positive integer")
        if not isinstance(retry_limit, int) or isinstance(retry_limit, bool) or retry_limit < 0:
            raise AgentSlotValidationError("retry_limit must be a non-negative integer")
        self.retry_limit = retry_limit
        super().__init__(path, capacity=capacity, auto_create=True, adapter=adapter)

    def spawn_batch(
        self,
        agent_ids: Iterable[str],
        spawn: Callable[[str, Mapping[str, Any]], Any],
    ) -> dict[str, Any]:
        """Run bounded spawn attempts without introducing another state store."""
        results = []
        for agent_id in agent_ids:
            attempts = 0
            item: dict[str, Any] = {"agent_id": agent_id, "attempts": 0, "receipts": []}
            while attempts <= self.retry_limit:
                attempts += 1
                item["attempts"] = attempts
                admission = self.acquire(agent_id)
                item["receipts"].append(admission)
                if not admission.get("accepted"):
                    item.update({"success": False, "reason_code": admission.get("reason_code")})
                    break
                record = {**admission, "agent_id": agent_id, "attempt": attempts}
                try:
                    outcome = spawn(agent_id, record)
                    if outcome is False:
                        raise RuntimeError("spawn adapter rejected admission")
                    started = self.start(agent_id)
                    item.update({"success": True, "receipt": started})
                    item["receipts"].append(started)
                    break
                except Exception as error:  # noqa: BLE001 - receipt must record adapter failures
                    item["error"] = str(error)
                    terminal = attempts > self.retry_limit
                    if terminal:
                        item.update({"success": False, "reason_code": "spawn_failed_retry_exhausted"})
                        self.close_agent(agent_id, status="shutdown", reason=str(error))
                        break
                    self.close_agent(agent_id, status="shutdown", reason=str(error))
                    self.reclaim(agent_id)
            results.append(item)
        return {
            "schema": SCHEMA,
            "operation": "spawn_batch",
            "retry_limit": self.retry_limit,
            "results": results,
            "status": self.status(),
            "local_llm": False,
        }


__all__ = ["AgentSlotError", "AgentSlotRegistry", "AgentSlotValidationError", "SCHEMA", "RECEIPT_SCHEMA"]


def cli_main(argv: Optional[Iterable[str]] = None) -> int:
    """Run the JSON-first slot lifecycle CLI; legacy storage is fail-closed."""
    parser = argparse.ArgumentParser(prog="simplicio-loop agent-slots")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--repo", default=".", help="Loop Git worktree used to resolve MapperStore")
        command_parser.add_argument("--db", default=".simplicio-loop/orchestrator/agent-slots.sqlite")
        command_parser.add_argument(
            "--route", choices=("legacy", "mapper"), default="mapper",
            help="storage route (default: mapper; legacy is retired and fails closed)",
        )
        command_parser.add_argument("--mapper-db", default=None)
        command_parser.add_argument("--mapper-init", action="store_true")
        command_parser.add_argument("--capacity", type=int, default=6)
        command_parser.add_argument("--retry-limit", type=int, default=1)

    status_parser = sub.add_parser("status", help="show agent-slot capacity and leases")
    common(status_parser)
    acquire_parser = sub.add_parser("acquire", help="acquire one agent slot lease")
    acquire_parser.add_argument("agent_id")
    acquire_parser.add_argument("--worktree", default=None)
    acquire_parser.add_argument("--lease-id", default=None)
    common(acquire_parser)
    start_parser = sub.add_parser("start", help="mark an acquired agent slot as started")
    start_parser.add_argument("agent_id")
    common(start_parser)
    close_parser = sub.add_parser("close", help="close an agent slot lease")
    close_parser.add_argument("agent_id")
    close_parser.add_argument("--status", choices=tuple(TERMINAL_STATES), default="completed")
    close_parser.add_argument("--reason", default="")
    common(close_parser)
    reclaim_parser = sub.add_parser("reclaim", help="reclaim expired or abandoned agent slots")
    reclaim_parser.add_argument("agent_id", nargs="?")
    common(reclaim_parser)
    blockers_parser = sub.add_parser("update-blockers", help="update dependency blockers for an agent slot")
    blockers_parser.add_argument("agent_id")
    blockers_parser.add_argument("--descendants", type=int, default=0)
    blockers_parser.add_argument("--worktree-active", action="store_true")
    blockers_parser.add_argument("--lease-active", action="store_true")
    common(blockers_parser)

    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.route == "legacy":
        result = {
            "schema": "simplicio.loop-agent-slots-route/v1",
            "status": "blocked",
            "reason_code": "LEGACY_ROUTE_REMOVED",
            "message": "local agent-slot persistence was removed; use the MapperStore route",
        }
        sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
        return 3

    mapper_db = args.mapper_db or str(_default_mapper_db(args.repo))
    from . import mapper_agent_slots

    registry = mapper_agent_slots.MapperAgentSlotRegistry(
        mapper_db, capacity=args.capacity, auto_create=False
    )
    if args.mapper_init:
        registry.initialize()
    if args.command == "status":
        result = registry.status()
    elif args.command == "acquire":
        result = registry.acquire(args.agent_id, worktree=args.worktree, lease_id=args.lease_id)
    elif args.command == "start":
        result = registry.start(args.agent_id)
    elif args.command == "close":
        result = registry.close_agent(args.agent_id, status=args.status, reason=args.reason)
    elif args.command == "reclaim":
        result = registry.reclaim(args.agent_id)
    else:
        result = registry.update_blockers(
            args.agent_id,
            descendants=args.descendants,
            worktree_active=args.worktree_active,
            lease_active=args.lease_active,
        )
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


def _git_root(repo: str) -> Path:
    candidate = Path(repo).expanduser().resolve()
    result = subprocess.run(
        ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False, timeout=10,
    )
    if result.returncode != 0:
        raise AgentSlotError("--repo must resolve to a Git worktree root")
    root = Path(result.stdout.strip()).resolve()
    if root != candidate:
        raise AgentSlotError("--repo must be the Git worktree root")
    return root


def _default_mapper_db(repo: str) -> Path:
    """Resolve the canonical operations store without creating it."""
    try:
        from simplicio_mapper.store import resolve_store_location
    except (ImportError, ModuleNotFoundError) as exc:
        raise AgentSlotError("MapperStore operations API is not installed") from exc
    root = _git_root(repo)
    environ = dict(os.environ)
    environ.pop("SIMPLICIO_DATA_DIR", None)
    environ.pop("SIMPLICIO_HOME", None)
    environ["SIMPLICIO_STORE_SCOPE"] = "repo"
    try:
        return resolve_store_location(environ=environ, repo_root=root).database("operations.sqlite")
    except (OSError, ValueError) as exc:
        raise AgentSlotError(f"canonical MapperStore path unavailable: {exc}") from exc
