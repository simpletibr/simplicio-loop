"""CLI adapter for Fast changeset v2."""

from __future__ import annotations

import json
import sys

from ._shared import read_binary_source


def run(args) -> int:
    from simplicio.changeset_v2 import BINARY_MAGIC, execute_changeset_bytes, execute_changeset_json

    try:
        source = read_binary_source(args.plan)
    except OSError as exc:
        print(f"simplicio-py changeset: {exc}", file=sys.stderr)
        return 2
    if source.startswith(BINARY_MAGIC):
        receipt = execute_changeset_bytes(
            source,
            root=args.root,
            apply=args.apply,
            current_generation=args.current_generation,
            fast_engine=args.fast_engine,
        )
    else:
        try:
            text = source.decode("utf-8")
        except UnicodeDecodeError:
            receipt = execute_changeset_bytes(
                source,
                root=args.root,
                apply=args.apply,
                current_generation=args.current_generation,
                fast_engine=args.fast_engine,
            )
        else:
            receipt = execute_changeset_json(
                text,
                root=args.root,
                apply=args.apply,
                current_generation=args.current_generation,
            )
    if args.json:
        print(json.dumps(receipt, sort_keys=True))
    else:
        print(f"{receipt['status']}: applied={receipt['applied']} dry_run={receipt['dry_run']}")
    return 0 if receipt["status"] == "ok" else 1
