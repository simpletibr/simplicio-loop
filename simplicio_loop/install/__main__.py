"""python -m simplicio_loop.install --host claude --target DIR"""
from __future__ import annotations

import argparse
import json
import sys

from .planner import InstallError, apply_plan, plan_install, uninstall, verify_plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simplicio-loop install")
    parser.add_argument("--host", default="claude", help="host id or 'all'")
    parser.add_argument("--target", default=".", help="project directory")
    parser.add_argument("--global", dest="globally", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--all-skills", action="store_true", help="also install the skills other than simplicio-loop")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.uninstall:
            payload = uninstall(args.target)
        else:
            plan = plan_install(args.target, host=args.host, globally=args.globally, all_skills=args.all_skills)
            if args.verify:
                payload = verify_plan(plan)
            else:
                payload = apply_plan(plan, dry_run=args.dry_run)
    except InstallError as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}), flush=True)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
