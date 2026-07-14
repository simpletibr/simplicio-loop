"""cache_cli.py - `simplicio-py cache` subcommand (stats / clear).

Lightweight management surface for the content-addressed completion cache
landed by issue #34.

  simplicio-py cache stats         print hit/miss/size/oldest
  simplicio-py cache clear         wipe cache directory
  simplicio-py cache stats --json  machine-readable
"""

from __future__ import annotations

import argparse
import json
import sys

from ._cache import cache


def _cmd_stats(args: argparse.Namespace) -> int:
    # cache().stats() returns a plain dict (see _cache.py's Cache.stats):
    # entries/bytes/root/enabled/bust/oldest_age_s, not an object with
    # attributes — accessing it as `s.entries` etc. raised AttributeError
    # on every invocation of this command.
    s = cache().stats()
    oldest_age_days = round(s["oldest_age_s"] / 86400, 2) if s["oldest_age_s"] is not None else None
    if args.json:
        print(
            json.dumps(
                {
                    "entries": s["entries"],
                    "size_bytes": s["bytes"],
                    "size_mb": s["mb"],
                    "oldest_age_days": oldest_age_days,
                    "enabled": s["enabled"],
                    "bust_active": s["bust"],
                    "root": s["root"],
                },
                indent=2,
            )
        )
        return 0
    print("simplicio-py cache stats")
    print(f"  root              {s['root']}")
    print(f"  enabled           {'yes' if s['enabled'] else 'no (SIMPLICIO_CACHE=0)'}")
    print(f"  bust active       {'YES (SIMPLICIO_BUST_CACHE=1)' if s['bust'] else 'no'}")
    print(f"  entries           {s['entries']}")
    print(f"  size              {s['mb']:.2f} MB")
    print(f"  oldest entry      {oldest_age_days} days")
    return 0


def _cmd_clear(args: argparse.Namespace) -> int:
    if not args.force:
        print(
            "[cache] refusing to clear without --force; this removes every cached completion.",
            file=sys.stderr,
        )
        return 2
    removed = cache().clear()
    print(f"[cache] cleared {removed} entries", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="simplicio-py cache")
    sub = p.add_subparsers(dest="verb", required=True)

    ps = sub.add_parser("stats", help="show cache size/age/state")
    ps.add_argument("--json", action="store_true")

    pc = sub.add_parser("clear", help="remove every cached completion")
    pc.add_argument("--force", action="store_true", help="required: confirm destructive op")

    args = p.parse_args(argv)
    if args.verb == "stats":
        return _cmd_stats(args)
    if args.verb == "clear":
        return _cmd_clear(args)
    return 2
