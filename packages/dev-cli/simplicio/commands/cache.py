"""``simplicio-py cache`` — inspect or clear the completion cache.

Extracted from `cli.py`'s `main()` body (issue #103); behavior unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys

CLI_PROG = "simplicio-py"


def run(a: argparse.Namespace) -> int:
    from .._cache import cache

    c = cache()
    if a.cache_cmd == "stats":
        stats = c.stats()
        if a.json:
            print(json.dumps(stats, sort_keys=True))
        else:
            print(f"root: {stats['root']}")
            print(f"enabled: {stats['enabled']}  bust: {stats['bust']}")
            print(f"entries: {stats['entries']}  size: {stats['mb']} MB")
            print(f"ttl_days: {stats['ttl_days']}  max_mb: {stats['max_mb']}")
        return 0
    if a.cache_cmd == "clear":
        if not a.force:
            print(f"{CLI_PROG} cache clear requires --force", file=sys.stderr)
            return 2
        removed = c.clear()
        print(f"cleared {removed} cached completion(s)")
        return 0
    return 0
