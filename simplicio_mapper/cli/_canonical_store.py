"""CLI for the canonical MapperStore status and legacy absorb APIs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..store.canonical import MapperStore, MapperStoreError

VERBS = {"canonical-status", "capabilities", "conformance", "absorb-legacy", "absorb"}
_HELP = """usage: simplicio-mapper mapper-store <canonical-status|capabilities|conformance|absorb-legacy> [options]

Inspect the canonical Mapper-owned memory/operations stores or explicitly absorb
legacy simplicio-memory.sqlite data. Legacy files are never deleted.

Options:
  --data-dir PATH          canonical store directory
  --database PATH          canonical memory.sqlite path
  --operations PATH        canonical operations.sqlite path
  --source PATH            legacy simplicio-memory.sqlite (absorb-legacy only)
  --no-mark-read-only      do not write the legacy read-only policy marker
  --json                   emit the versioned receipt
"""


def _error(reason_code: str, reason: str, json_mode: bool) -> int:
    payload = {"schema": "simplicio.mapper-store.error/v1", "ok": False, "reason_code": reason_code, "reason": reason}
    print(json.dumps(payload, sort_keys=True) if json_mode else reason, file=sys.stdout if json_mode else sys.stderr)
    return 1


def run_canonical_store_cli(argv: list[str]) -> int:
    if "--help" in argv or "-h" in argv:
        print(_HELP, end="")
        return 0
    verb = argv[0] if argv else ""
    if verb not in VERBS:
        return 2
    data_dir = memory = operations = source = None
    json_mode = False
    mark_read_only = True
    index = 1
    while index < len(argv):
        option = argv[index]
        if option in {"--data-dir", "--database", "--memory", "--operations", "--source"} and index + 1 < len(argv):
            value = argv[index + 1]
            if option == "--data-dir":
                data_dir = Path(value)
            elif option in {"--database", "--memory"}:
                memory = Path(value)
            elif option == "--operations":
                operations = Path(value)
            else:
                source = Path(value)
            index += 2
        elif option == "--no-mark-read-only":
            mark_read_only = False
            index += 1
        elif option == "--json":
            json_mode = True
            index += 1
        else:
            return _error("INVALID_ARGUMENT", f"unknown option or missing value: {option}", json_mode)
    if verb in {"absorb-legacy", "absorb"} and source is None:
        return _error("INVALID_ARGUMENT", "--source PATH is required", json_mode)
    try:
        store = MapperStore(data_dir=data_dir, memory_database=memory, operations_database=operations)
        if verb == "canonical-status":
            payload = store.status()
        elif verb == "capabilities":
            payload = store.capabilities()
        elif verb == "conformance":
            payload = store.conformance()
        else:
            assert source is not None
            payload = store.absorb_legacy(source, mark_read_only=mark_read_only)
    except (MapperStoreError, OSError, ValueError) as error:
        return _error(getattr(error, "reason_code", "MAPPER_STORE_ERROR"), str(error), json_mode)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True) if json_mode else f"{verb}: {payload.get('status', 'ok')}")
    return 0


__all__ = ["VERBS", "run_canonical_store_cli"]
