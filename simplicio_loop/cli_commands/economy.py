"""`economy`: the fastest and cheapest profile.

Split from cli_impl.py (#1818). The code is moved unchanged; see
cli_commands/_base.py for why some names are read through impl().
"""
from __future__ import annotations

import sys

def economy_command(args) -> int:
    """economy status | print | apply — fastest token path + parallel defaults."""
    import json as _json

    from ..economy_profile import (
        economy_parallel_env,
        persist_user_profile,
        profile_status,
        render_shell_exports,
    )

    sub = getattr(args, "economy_command", None)
    if sub == "status":
        payload = profile_status()
        if args.json:
            print(_json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"economy profile: {payload['profile']} enabled={payload['enabled']}")
            print(
                f"  execution_profile={payload.get('execution_profile')} "
                f"runtime_operational={payload.get('runtime_operational')}"
            )
            if payload.get("note"):
                print(f"  note: {payload['note']}")
            print(f"  cpu={payload['cpu_count']} aligned={payload['aligned']}")
            print(f"  workers={payload['recommended'].get('SIMPLICIO_LOOP_OPERATOR_WORKERS')}")
            print(f"  prism_slots={payload['recommended'].get('SIMPLICIO_PRISM_SLOTS')}")
            print(f"  async={payload['recommended'].get('SIMPLICIO_ASYNC_IO_MAX_CONCURRENCY')}")
            print(f"  fan_out={payload['recommended'].get('SIMPLICIO_LOOP_AUTO_FAN_OUT')}")
            if payload["drift_keys"]:
                print(f"  drift: {', '.join(payload['drift_keys'][:12])}")
                if payload.get("drift_explanation"):
                    print(f"  why: {payload['drift_explanation']}")
                if payload.get("drift_fix"):
                    print(f"  fix: {payload['drift_fix']}")
            print("  backends: Runtime Tokio · Python asyncio · Prism slots")
        return 0 if payload.get("enabled") else 1
    if sub == "print":
        env_map = economy_parallel_env()
        if args.json:
            print(_json.dumps({"schema": "simplicio.economy-parallel-profile/v1", "env": env_map},
                              ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_shell_exports(env_map, shell=args.shell), end="")
        return 0
    if sub == "apply":
        no_user = bool(getattr(args, "no_user", False))
        if no_user:
            import os as _os

            applied = economy_parallel_env()
            for key, value in applied.items():
                _os.environ[key] = value
            payload = {
                "schema": "simplicio.economy-parallel-profile/v1",
                "ok": True,
                "scope": "process",
                "env": applied,
            }
        else:
            payload = persist_user_profile(set_windows_user_env=True)
        if args.json:
            print(_json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"economy apply ok={payload.get('ok')} profile={payload.get('profile')}")
            paths = payload.get("paths") or {}
            if paths.get("ps1"):
                print(f"  ps1: {paths['ps1']}")
            if paths.get("sh"):
                print(f"  sh:  {paths['sh']}")
            if payload.get("rc_files_changed"):
                print(f"  rc_files_changed: {', '.join(payload['rc_files_changed'])}")
            print(f"  workers={payload.get('env', {}).get('SIMPLICIO_LOOP_OPERATOR_WORKERS')}")
            print(f"  prism_slots={payload.get('env', {}).get('SIMPLICIO_PRISM_SLOTS')}")
        return 0 if payload.get("ok", True) else 1
    print("unknown economy command", file=sys.stderr)
    return 2


def add_economy(sub):
    p_economy = sub.add_parser(
        "economy",
        help="fastest + cheapest profile: token economy, bounded CPU/RAM, Prism/asyncio parallel",
    )
    economy_sub = p_economy.add_subparsers(dest="economy_command", required=True)
    p_economy_status = economy_sub.add_parser(
        "status", help="show recommended vs applied economy-parallel env"
    )
    p_economy_status.add_argument("--json", action="store_true")
    p_economy_print = economy_sub.add_parser(
        "print", help="print shell exports (ps1 on Windows, sh elsewhere)"
    )
    p_economy_print.add_argument(
        "--shell", choices=("auto", "ps1", "sh"), default="auto"
    )
    p_economy_print.add_argument("--json", action="store_true")
    p_economy_apply = economy_sub.add_parser(
        "apply",
        help="apply profile to this process + ~/.simplicio-loop + Windows User env",
    )
    p_economy_apply.add_argument(
        "--user",
        action="store_true",
        default=True,
        help="persist to Windows User env / shell files (default)",
    )
    p_economy_apply.add_argument(
        "--no-user",
        action="store_true",
        help="only mutate the current process environ",
    )
    p_economy_apply.add_argument("--json", action="store_true")
