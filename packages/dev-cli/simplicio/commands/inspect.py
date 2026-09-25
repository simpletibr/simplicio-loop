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
    if getattr(a, "context", False):
        payload["context_explain"] = [
            {
                "stable_id": f"file:{item.get('path', '')}",
                "path": item.get("path"),
                "reasons": [
                    *(
                        ["target_match"]
                        if str(item.get("path", "")).replace("\\", "/") == str(a.target).replace("\\", "/")
                        else []
                    ),
                    *([f"role:{role}" for role in item.get("roles", [])]),
                    *(["goal_ranked"] if a.goal else []),
                ],
            }
            for item in payload.get("relevant_files", [])
            if isinstance(item, dict) and item.get("path")
        ]
    if a.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(payload["context"])
    return 0
