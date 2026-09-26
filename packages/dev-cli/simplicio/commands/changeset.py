"""CLI adapter for the Dev CLI JSON changeset v2."""

from __future__ import annotations

import json
import sys

from ._shared import read_binary_source


def run(args) -> int:
    from simplicio.changeset_v2 import execute_changeset_json
    from simplicio.standalone_migration import MutationRouteAdmission

    requested_mode = getattr(args, "mode", None) or "standalone"
    if requested_mode == "integrated":
        receipt = {
            "schema": "simplicio.fast.changeset-receipt/v2",
            "status": "refused",
            "applied": False,
            "dry_run": not args.apply,
            "errors": [
                {
                    "code": "RUNTIME_AUTHORIZATION_REQUIRED",
                    "message": (
                        "changeset direct execution supports standalone/auto; "
                        "use task for runtime-backed effects"
                    ),
                }
            ],
            "execution_mode": {"requested": requested_mode, "effective": "blocked", "runtime_required": True},
        }
        if args.json:
            print(json.dumps(receipt, sort_keys=True))
        else:
            print(f"{receipt['status']}: applied=False dry_run={receipt['dry_run']}")
        return 1

    route_admission = MutationRouteAdmission(requested_mode, "standalone")
    try:
        source = read_binary_source(args.plan)
    except OSError as exc:
        print(f"simplicio-py changeset: {exc}", file=sys.stderr)
        return 2
    receipt = execute_changeset_json(
        source,
        root=args.root,
        apply=args.apply,
        current_generation=args.current_generation,
        route_admission=route_admission,
    )
    receipt["execution_mode"] = {
        "requested": requested_mode,
        "effective": "standalone",
        "runtime_required": False,
        "provider_calls": 0,
        "route": "standalone",
    }
    if args.json:
        print(json.dumps(receipt, sort_keys=True))
    else:
        print(f"{receipt['status']}: applied={receipt['applied']} dry_run={receipt['dry_run']}")
    return 0 if receipt["status"] == "ok" else 1
