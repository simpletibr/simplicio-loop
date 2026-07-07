"""``simplicio-py inspect`` — inspect a target with mapper-backed context.

Extracted from `cli.py`'s `_run_inspect_command` (issue #103); behavior
unchanged.
"""

from __future__ import annotations

import argparse
import json


def run(a: argparse.Namespace) -> int:
    from ..mapper import inspect_target

    payload = {
        "schema": "simplicio.dev-cli.inspect/v1",
        **inspect_target(a.root, a.target, goal=a.goal),
    }
    if a.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(payload["context"])
    return 0
