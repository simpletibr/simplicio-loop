"""Actionable schema assertions for the contract suite.

Per #100 AC ("contract failures give actionable messages not raw stack
traces"): a bare ``payload["schema"]`` KeyError or a plain ``==`` on a dict
gives a diff no human wants to read. These helpers name exactly what was
expected, what was found, and where.
"""

from __future__ import annotations

from typing import Any


def assert_schema_id(payload: dict[str, Any], expected: str, *, where: str) -> None:
    actual = payload.get("schema")
    assert actual == expected, (
        f"{where}: expected schema {expected!r}, got {actual!r}. "
        f"Full payload keys: {sorted(payload.keys())}"
    )


def assert_has_keys(payload: dict[str, Any], required: set[str], *, where: str) -> None:
    missing = required - payload.keys()
    assert not missing, (
        f"{where}: missing required key(s) {sorted(missing)}. "
        f"Present keys: {sorted(payload.keys())}"
    )
