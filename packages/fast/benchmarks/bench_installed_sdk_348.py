"""Installed Python SDK/CLI consumer receipt for issue #348."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from simplicio_fast import __version__
from simplicio_fast.installation import python_smoke


SCHEMA = "simplicio.fast.installed-sdk-receipt/v1"


def run() -> dict[str, Any]:
    smoke = python_smoke()
    launcher = shutil.which("simplicio-fast")
    installed = smoke["launcher"]["kind"] == "installed-cli"
    steps = smoke["steps"]
    checks = {
        "installed_launcher": installed,
        "all_cli_steps": all(step["status"] == "pass" for step in steps),
        "build_refresh_query_context_plan_delivery": smoke["checks"][
            "build_refresh_query_context_plan_delivery"
        ],
    }
    return {
        "schema": SCHEMA,
        "status": "pass" if all(checks.values()) else "partial",
        "package": {"name": "simplicio-fast", "version": __version__},
        "launcher": {"path": launcher, "kind": smoke["launcher"]["kind"], "reason_code": smoke["launcher"]["reason_code"]},
        "checks": checks,
        "steps": steps,
        "residuals": ["backpressure_cancellation", "cross_platform_artifacts", "upgrade_rollback_receipts"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run()
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    if receipt["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
