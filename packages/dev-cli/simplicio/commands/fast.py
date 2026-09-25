"""CLI adapter for optional Simplicio Fast negotiation."""

from __future__ import annotations

import json

from simplicio.fast_contracts import capabilities_contract, doctor_contract, write_local_receipt


def run(args) -> int:
    if args.fast_cmd == "capabilities":
        payload = capabilities_contract(offline=args.offline)
        code = 0
    else:
        payload = doctor_contract(snapshot=args.snapshot, offline=args.offline)
        code = payload["exit_codes"][payload["status"]]
    if args.receipt:
        write_local_receipt(args.receipt, command=f"fast {args.fast_cmd}", payload=payload)
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"Simplicio Fast: {payload.get('status') or payload['availability']['status']}")
        correction = payload.get("correction") or payload["availability"].get("correction")
        if correction:
            print(f"Next action: {correction}")
    return code
