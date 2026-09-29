"""Packaged CLI surface for the #516 supervisor observability/enforcement slice.

Wires ``status`` / ``top`` / ``queue`` / ``cancel`` / ``drain`` / ``reports`` to the real state
kept by :mod:`simplicio_loop.process_enforcement` (a :class:`ProcessRegistry` on disk) -- not to
stub/fake data. Each subcommand prints one JSON object to stdout and exits 0 on success.

Honest scope note (see ``docs/SUPERVISOR_ENFORCEMENT_RUNBOOK.md``): ``queue`` here reports the
currently *active* (in-flight) supervised leases only -- there is no separate pending-priority
queue wired in, so this slice reports what the registry actually has bookkept rather than
fabricating queue depth.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from typing import Any, Dict, List, Optional

from .process_enforcement import (
    CircuitBreaker,
    ProcessRegistry,
    detect_unsupervised,
    enforce,
    enforcement_enabled,
    append_event,
    read_events,
)


def _print(payload: Dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def _registry(args: argparse.Namespace) -> ProcessRegistry:
    from pathlib import Path

    return ProcessRegistry(Path(args.registry) if args.registry else None)


def cmd_status(args: argparse.Namespace) -> int:
    from pathlib import Path

    registry = _registry(args)
    active = registry.active()
    breaker = CircuitBreaker.load(Path(args.breaker) if args.breaker else None)
    return _print({
        "schema": "simplicio.supervisor-status/v1",
        "ts": time.time(),
        "enforcement_enabled": enforcement_enabled(),
        "active_supervised_count": len(active),
        "circuit_breaker": breaker.to_dict(),
        "registry_path": str(registry.path),
    })


def cmd_top(args: argparse.Namespace) -> int:
    registry = _registry(args)
    now = time.time()
    rows = [
        {
            "pid": pid,
            "lease_id": record.get("lease_id"),
            "spec_hash": record.get("spec_hash"),
            "argv": record.get("argv"),
            "age_seconds": round(now - float(record.get("registered_at", now)), 3),
        }
        for pid, record in registry.active().items()
    ]
    rows.sort(key=lambda row: row["age_seconds"], reverse=True)
    return _print({"schema": "simplicio.supervisor-top/v1", "ts": now, "processes": rows})


def cmd_queue(args: argparse.Namespace) -> int:
    registry = _registry(args)
    active = registry.active()
    report: Dict[str, Any] = {
        "schema": "simplicio.supervisor-queue/v1",
        "ts": time.time(),
        "note": "reports active (in-flight) supervised leases",
        "in_flight": len(active),
        "leases": [
            {"pid": pid, "lease_id": record.get("lease_id")}
            for pid, record in active.items()
        ],
    }
    return _print(report)


def cmd_cancel(args: argparse.Namespace) -> int:
    registry = _registry(args)
    active = registry.active()
    target_pid: Optional[int] = None
    if args.pid is not None:
        target_pid = args.pid
    else:
        for pid, record in active.items():
            if record.get("lease_id") == args.lease_id:
                target_pid = pid
                break
    if target_pid is None:
        return _print({
            "schema": "simplicio.supervisor-cancel/v1", "ok": False,
            "reason": "no matching active lease/pid found",
        })
    try:
        os.kill(target_pid, signal.SIGTERM)
        ok, error = True, None
    except OSError as exc:
        ok, error = False, str(exc)
    append_event("cancel", {"pid": target_pid, "ok": ok, "error": error})
    return _print({"schema": "simplicio.supervisor-cancel/v1", "ok": ok, "pid": target_pid, "error": error})


def cmd_drain(args: argparse.Namespace) -> int:
    registry = _registry(args)
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        active = registry.active()
        if not active:
            return _print({"schema": "simplicio.supervisor-drain/v1", "drained": True, "remaining": 0})
        time.sleep(args.poll_interval)
    remaining = registry.active()
    if args.force:
        for pid in list(remaining):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    return _print({
        "schema": "simplicio.supervisor-drain/v1",
        "drained": False,
        "remaining": len(remaining),
        "forced": bool(args.force),
    })


def cmd_reports(args: argparse.Namespace) -> int:
    if args.scan:
        registry = _registry(args)
        flagged = detect_unsupervised(registry)
        enabled = enforcement_enabled(override=args.enforce if args.enforce else None)
        actions = enforce(flagged, enabled=enabled)
        event = append_event("detection_scan", {
            "flagged_count": len(flagged),
            "flagged": [{"pid": r.pid, "argv": r.cmdline} for r in flagged],
            "enforcement_enabled": enabled,
            "actions": actions,
        })
        return _print(event)
    events = read_events(limit=args.limit)
    return _print({"schema": "simplicio.supervisor-reports/v1", "count": len(events), "events": events})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=None, help="override the registry.json path")
    parser.add_argument("--breaker", default=None, help="override the breaker.json path")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="enforcement mode, active count, circuit breaker state")

    sub.add_parser("top", help="list currently supervised processes with pid/lease/age")

    sub.add_parser("queue", help="list in-flight supervised leases (see honest scope note)")

    p_cancel = sub.add_parser("cancel", help="SIGTERM a supervised process by pid or lease id")
    group = p_cancel.add_mutually_exclusive_group(required=True)
    group.add_argument("--pid", type=int)
    group.add_argument("--lease-id")

    p_drain = sub.add_parser("drain", help="wait for all active leases to finish (or --force)")
    p_drain.add_argument("--timeout", type=float, default=10.0)
    p_drain.add_argument("--poll-interval", type=float, default=0.2)
    p_drain.add_argument("--force", action="store_true")

    p_reports = sub.add_parser("reports", help="replay logged events, or run a fresh --scan")
    p_reports.add_argument("--limit", type=int, default=50)
    p_reports.add_argument("--scan", action="store_true", help="run a detection pass and log it")
    p_reports.add_argument("--enforce", action="store_true", help="force enforcement on for this --scan")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "status": cmd_status,
        "top": cmd_top,
        "queue": cmd_queue,
        "cancel": cmd_cancel,
        "drain": cmd_drain,
        "reports": cmd_reports,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
