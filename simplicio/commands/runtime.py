"""``simplicio-py runtime`` — runtime-facing dev-cli contracts.

Extracted from `cli.py`'s `_run_runtime_command` (issue #103); behavior
unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys

CLI_PROG = "simplicio-py"

# Issue #167 (ecosystem rebrand), plan steps 16/17: a single static,
# stderr-only compat warning emitted when `runtime verify` detects the
# probed binary is a known pre-rebrand alias (Hermes/Agent) rather than the
# real Simplicio Runtime. Deliberately static — no interpolated CLI args,
# prompt content, or env values — so it can never leak local/sensitive data
# and never corrupts stdout (the JSON contract below is the only thing this
# command writes to stdout).
LEGACY_RUNTIME_ALIAS_WARNING = (
    "simplicio-py: detected a legacy runtime alias (Hermes/Agent) on the "
    "reserved `simplicio` command; this is deprecated, see the ecosystem "
    "migration guide (issue #167)."
)


def run(a: argparse.Namespace) -> int:
    from ..observability import warn
    from ..runtime_contracts import doctor_contract, runtime_verify_contract

    if a.runtime_cmd == "verify":
        payload = runtime_verify_contract(timeout=a.timeout)
        if payload.get("legacy_alias"):
            warn(LEGACY_RUNTIME_ALIAS_WARNING)
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload["verified"] else 1

    if a.runtime_cmd == "capabilities":
        from ..execution_mode import capabilities_report

        payload = capabilities_report(
            a.mode,
            root=a.root,
            context_snapshot_path=getattr(a, "context_snapshot", None),
            attempt_id=getattr(a, "attempt_id", None),
            lease_id=getattr(a, "lease_id", None),
            fencing_token=getattr(a, "fencing_token", None),
            context_handle=getattr(a, "context_handle", None),
            coordinator_kind=getattr(a, "coordinator_kind", None),
            coordinator_id=getattr(a, "coordinator_id", None),
        )
        print(
            json.dumps(payload, sort_keys=True) if a.json else json.dumps(payload, indent=2, sort_keys=True)
        )
        return 0
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
