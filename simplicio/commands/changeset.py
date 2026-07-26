"""CLI adapter for Fast changeset v2."""

from __future__ import annotations

import json
import sys

from ._shared import read_text_source


def run(args) -> int:
    from simplicio.changeset_v2 import execute_changeset_json

    try:
        source = read_text_source(args.plan)
    except OSError as exc:
        print(f"simplicio-py changeset: {exc}", file=sys.stderr)
        return 2
    receipt = execute_changeset_json(
        source,
        root=args.root,
        apply=args.apply,
        current_generation=args.current_generation,
    )
    if args.json:
        print(json.dumps(receipt, sort_keys=True))
    else:
        print(f"{receipt['status']}: applied={receipt['applied']} dry_run={receipt['dry_run']}")
    return 0 if receipt["status"] == "ok" else 1
