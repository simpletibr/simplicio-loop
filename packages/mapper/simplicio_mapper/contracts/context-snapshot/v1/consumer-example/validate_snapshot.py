#!/usr/bin/env python3
"""Validate a ContextSnapshot v1 file from an installed simplicio-mapper wheel."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from simplicio_mapper.context_contract import validate_context_file


def _error(code: str, message: str) -> dict[str, Any]:
    return {
        "valid": False,
        "reason_codes": [{"code": code, "path": "$", "message": message}],
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(json.dumps(_error("USAGE", "usage: validate_snapshot.py SNAPSHOT.json"), sort_keys=True))
        return 2

    try:
        result = validate_context_file(Path(args[0]))
    except OSError as exc:
        result = _error("READ_ERROR", str(exc))
    except Exception as exc:  # noqa: BLE001 - preserve the example's JSON protocol
        result = _error("VALIDATOR_ERROR", str(exc))

    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
