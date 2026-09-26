"""Stable-first key order for public loop JSON payloads (issue #1342).

Invariant fields come first (``schema`` leads); per-run volatile fields
(``run_id``, ``*_at`` timestamps, ``*_ms``/``*_s``/``elapsed`` durations,
receipt/path fields, ``receipt_hash``) move to the end, so only the tail of
the serialized JSON changes between runs. Values are never modified and
relative order within each group is preserved (no ``sort_keys``).
The same volatile tail as ``apply`` (#1336): ``run_id``/``created_at``/
``receipt_path``.
"""
from __future__ import annotations

from typing import Any

VOLATILE_KEYS = frozenset({
    "run_id", "receipt", "receipt_hash", "receipt_path", "elapsed",
    "state_dir", "run_dir", "path",
})
VOLATILE_SUFFIXES = ("_at", "_ms", "_s", "_path", "_receipt", "_elapsed")


def is_volatile(key: Any, value: Any = None) -> bool:
    if not isinstance(key, str):
        return False
    if key in VOLATILE_KEYS or "receipt" in key or key.endswith(VOLATILE_SUFFIXES):
        return True
    return isinstance(value, str) and ".simplicio-loop/" in value


def stable_first(payload: Any, *, schema_first: bool = True) -> Any:
    """Return ``payload`` with volatile keys moved last, recursively."""
    if isinstance(payload, list):
        return [stable_first(item, schema_first=schema_first) for item in payload]
    if not isinstance(payload, dict):
        return payload
    head: dict[Any, Any] = {}
    stable: dict[Any, Any] = {}
    tail: dict[Any, Any] = {}
    for key, value in payload.items():
        value = stable_first(value, schema_first=schema_first)
        if schema_first and key == "schema":
            head[key] = value
        elif is_volatile(key, value):
            tail[key] = value
        else:
            stable[key] = value
    return {**head, **stable, **tail}
