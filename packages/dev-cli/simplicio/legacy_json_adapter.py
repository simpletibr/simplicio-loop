"""Explicit, read-once adapter for legacy JSONL migration.

JSON is accepted here only at the migration boundary. Callers must immediately
encode the returned scalar fields into HBP; this module never writes JSON and
must not be used by a normal execution path.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class LegacyJsonMigrationError(ValueError):
    """Raised when a legacy JSONL stream cannot be migrated safely."""


def _flatten(value: Any, prefix: str = "") -> dict[str, str]:
    if isinstance(value, Mapping):
        result: dict[str, str] = {}
        for key in sorted(value, key=str):
            name = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(value[key], name))
        return result
    if isinstance(value, list):
        return {prefix: repr(value)}
    if value is None:
        return {prefix: "null"}
    if isinstance(value, bool):
        return {prefix: "true" if value else "false"}
    if isinstance(value, (str, int, float)):
        return {prefix: str(value)}
    raise LegacyJsonMigrationError(f"unsupported legacy JSON value at {prefix or '<root>'}")


def read_jsonl(path: str | Path) -> list[dict[str, str]]:
    """Parse and validate every legacy row before a migration can write.

    The complete input is validated first so a malformed trailing row cannot
    leave a partially migrated target behind.
    """

    source = Path(path)
    rows: list[dict[str, str]] = []
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise LegacyJsonMigrationError(f"cannot read legacy JSONL: {source}") from exc
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LegacyJsonMigrationError(f"invalid legacy JSONL at line {number}") from exc
        if not isinstance(payload, Mapping):
            raise LegacyJsonMigrationError(f"legacy JSONL line {number} must be an object")
        rows.append(_flatten(payload))
    return rows


__all__ = ["LegacyJsonMigrationError", "read_jsonl"]
