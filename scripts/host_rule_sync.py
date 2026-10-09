#!/usr/bin/env python3
"""Sync multi-LLM operator-flow rules into every supported host surface.

CLI over `simplicio_loop.host_rules` (the implementation ships in the wheel).
Idempotent. Creates dirs; overwrites only Simplicio-owned rule files.
Does not delete foreign user rules.

Usage:
  python3 scripts/host_rule_sync.py --global --json
  python3 scripts/host_rule_sync.py --target /path/to/repo --json
  python3 scripts/host_rule_sync.py --global --target . --json
  python3 scripts/host_rule_sync.py --check --target . --json   # drift check, no writes (#1305)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simplicio_loop.host_rules import check, sync  # noqa: E402,F401  (sync is re-exported)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--global", dest="do_global", action="store_true")
    p.add_argument("--target", type=str, default=None)
    p.add_argument("--check", action="store_true", help="read-only drift check; no writes")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    if args.check:
        target = Path(args.target).resolve() if args.target else Path.cwd()
        try:
            receipt = check(target=target)
        except Exception as exc:
            err = {"schema": "simplicio.host-rule-sync-check/v1", "ok": False, "error": str(exc)}
            print(json.dumps(err, indent=2) if args.json else f"host_rule_sync --check FAIL: {exc}")
            return 1
        if args.json:
            print(json.dumps(receipt, indent=2, sort_keys=True))
        else:
            print(f"host_rule_sync --check: {'OK' if receipt['ok'] else 'DRIFT'} "
                  f"({len(receipt['checked'])} checked, {len(receipt['drift'])} drifted)")
            for item in receipt["drift"]:
                print(f"  - {item['surface']}: {item['path']}")
        return 0 if receipt["ok"] else 1
    if not args.do_global and not args.target:
        args.do_global = True
    try:
        receipt = sync(
            do_global=args.do_global,
            target=Path(args.target) if args.target else None,
        )
    except Exception as exc:
        err = {"schema": "simplicio.host-rule-sync/v1", "ok": False, "error": str(exc)}
        print(json.dumps(err, indent=2) if args.json else f"host_rule_sync FAIL: {exc}")
        return 1
    if args.json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        print(f"host_rule_sync: wrote {receipt['count']} surfaces")
        for item in receipt["written"]:
            print(f"  - {item['surface']}: {item['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
