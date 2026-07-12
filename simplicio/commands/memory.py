"""``simplicio-py memory`` — cross-vendor memory handoff.

Extracted from `cli.py`'s `_run_memory_command` (issue #103); behavior
unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys

CLI_PROG = "simplicio-py"


def run(a: argparse.Namespace) -> int:
    from ..memory_store import build_handoff, init_memory, recall_memory, store_memory, validate_memory

    if a.memory_cmd == "init":
        payload = init_memory(root=a.dir)
        if a.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(
                f"{CLI_PROG} memory init: {payload['dir']} "
                f"(created={payload['created']}, git={payload['git_initialized']})"
            )
        return 0
    if a.memory_cmd == "store":
        tags = [t.strip() for t in a.tags.split(",") if t.strip()] if a.tags else None
        payload = store_memory(a.topic, a.content, tags=tags, root=a.dir)
        if a.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"{CLI_PROG} memory store: {payload['path']} (committed={payload['committed']})")
        return 0
    if a.memory_cmd == "recall":
        results = recall_memory(a.query, limit=a.limit, root=a.dir, mode=a.mode)
        if a.json:
            print(json.dumps({"results": results}, sort_keys=True))
        else:
            if not results:
                print(f"{CLI_PROG} memory recall: no matches")
            for r in results:
                print(f"[{r['score']}] {r['topic']}: {r['snippet'][:120]}")
        return 0
    if a.memory_cmd == "validate":
        payload = validate_memory(root=a.dir)
        if a.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(
                f"{CLI_PROG} memory validate: ok={payload['ok']} "
                f"notes={payload['notes']} entries={payload['entries']}"
            )
            for row in payload["errors"]:
                print(f"ERROR {row['code']}: {row['message']}")
            for row in payload["warnings"]:
                print(f"WARN {row['code']}: {row['message']}")
        return 0 if payload["ok"] or not getattr(a, "strict", False) else 2
    if a.memory_cmd == "handoff":
        payload = build_handoff(
            a.query,
            limit=a.limit,
            root=a.dir,
            from_agent=a.from_agent,
            to_agent=a.to_agent,
        )
        if a.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(
                f"{CLI_PROG} memory handoff: {len(payload['results'])} results "
                f"from={payload['from_agent']} to={payload['to_agent']} "
                f"validation_ok={payload['validation']['ok']}"
            )
            for row in payload["results"]:
                print(f"[{row['score']}] {row['topic']}: {row['snippet'][:120]}")
        return 0
    print(f"{CLI_PROG} memory: unsupported command", file=sys.stderr)
    return 2
