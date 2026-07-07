"""``simplicio-py runtime`` — runtime-facing dev-cli contracts.

Extracted from `cli.py`'s `_run_runtime_command` (issue #103); behavior
unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys

CLI_PROG = "simplicio-py"


def run(a: argparse.Namespace) -> int:
    from ..runtime_contracts import doctor_contract

    if a.runtime_cmd == "doctor":
        payload = doctor_contract(a.root)
        if a.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"{CLI_PROG} runtime doctor: {payload['package']['version']}")
            for name, status in payload["tools"].items():
                state = "ok" if status["available"] else "missing"
                print(f"  {name}: {state}")
        return 0
    print(f"{CLI_PROG} runtime: unsupported command", file=sys.stderr)
    return 2
