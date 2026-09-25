#!/usr/bin/env python3
"""Validate the small cross-repository map handoff contract offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.map-handoff/v1"


def _validate_handoff(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema") != SCHEMA:
        errors.append(f'schema must be "{SCHEMA}"')
    if not isinstance(payload.get("context_pack"), dict):
        errors.append("context_pack must be an object")
    if not isinstance(payload.get("ready"), bool):
        errors.append("ready must be boolean")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path, help="JSON handoff payload")
    args = parser.parse_args()
    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    errors = _validate_handoff(payload)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Cross-repository handoff conformance passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
