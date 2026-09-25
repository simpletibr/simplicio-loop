"""``simplicio-py capabilities`` argparse fallback (``--help`` path).

The hot path (``simplicio-dev-cli capabilities`` / ``--json``) is
intercepted earlier in :mod:`simplicio.cli`'s ``_main_unwrapped`` before the
argparse tree is even built, so it never reaches this module. This module
only runs for ``capabilities -h``/``--help``, which argparse must handle
itself to print real usage text -- so it reuses the exact same static
manifest for consistency rather than duplicating output logic.
"""

from __future__ import annotations

import argparse
import json

from ..capabilities import load_capabilities_manifest

CLI_PROG = "simplicio-py"


def run(a: argparse.Namespace) -> int:
    payload = load_capabilities_manifest()
    if getattr(a, "json", False):
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"{CLI_PROG} capabilities: schema={payload['schema']} version={payload['package']['version']}")
        print(f"  commands: {', '.join(sorted(payload['commands']))}")
    return 0
