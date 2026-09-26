#!/usr/bin/env python3
"""Append-only structured audit log for #289 authorization decisions.

Gap this closes: `secure_transport.py`, `distributed_trust_policy.py` and
`short_lived_credentials.py` each made a fail-closed accept/reject decision
but none of them recorded *why* -- an incident responder had no durable trail
of "who tried what, when, and what the verdict was" to reconstruct an attack
or prove a legitimate run was authorized. This module is the single place
those call sites append one JSON line per decision to an append-only file.

Every entry is ``{schema, ts, event, decision, who, operation, reason, ...}``.
Callers must never place secret material (tokens, signing secrets, private
keys) in ``extra`` -- this module does not redact, it only appends what it is
given, so the discipline lives at the call site (the same discipline #289
already requires of `secure_transport.request_json`, which never logs a
bearer token).

Writing here is best-effort: a full disk or unwritable directory must never
turn an otherwise-correct fail-closed decision into a silent open door, so
:func:`append_event` swallows its own I/O errors after trying once. The
authorization/verification decision itself -- raising, returning False, or
rejecting the request -- happens at the call site regardless of whether the
audit line was written.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "simplicio.security-audit-log/v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_LOG_PATH = REPO_ROOT / ".simplicio-loop/orchestrator" / "security" / "audit-log.jsonl"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def append_event(
    path: Optional[Path] = None,
    *,
    event: str,
    decision: str,
    who: str = "",
    operation: str = "",
    reason: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Append one structured audit line. Never raises.

    ``decision`` should be one of ``"accept"``/``"reject"``. ``who``/``operation``
    are free-form identifiers (agent id, actor, subject, environment id, jti,
    origin id, pin id) -- never a bearer token or signing secret.
    """
    if decision not in ("accept", "reject"):
        decision = "reject" if decision not in ("accept",) else decision
    target = Path(path) if path is not None else DEFAULT_AUDIT_LOG_PATH
    record: Dict[str, Any] = {
        "schema": SCHEMA,
        "ts": _now_iso(),
        "event": str(event),
        "decision": decision,
        "who": str(who or ""),
        "operation": str(operation or ""),
        "reason": str(reason or ""),
    }
    if extra:
        for key, value in extra.items():
            if key in record:
                continue
            record[key] = value
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
    except OSError:
        # Best-effort: a full disk or unwritable directory must not flip an
        # otherwise fail-closed decision into a silent pass. The caller's own
        # accept/reject already happened (or is about to); losing the audit
        # line is a degraded-observability event, not a security bypass.
        return


def read_events(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    target = Path(path) if path is not None else DEFAULT_AUDIT_LOG_PATH
    if not target.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _cmd_tail(args: argparse.Namespace) -> int:
    events = read_events(Path(args.audit_log))
    for record in events[-args.n:]:
        print(json.dumps(record, sort_keys=True))
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    events = read_events(Path(args.audit_log))
    accepted = sum(1 for e in events if e.get("decision") == "accept")
    rejected = sum(1 for e in events if e.get("decision") == "reject")
    print(json.dumps({"ok": True, "total": len(events), "accepted": accepted, "rejected": rejected}))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-log", default=str(DEFAULT_AUDIT_LOG_PATH))
    sub = parser.add_subparsers(dest="command", required=True)

    p_tail = sub.add_parser("tail")
    p_tail.add_argument("-n", type=int, default=20)
    p_tail.set_defaults(func=_cmd_tail)

    sub.add_parser("stats").set_defaults(func=_cmd_stats)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
