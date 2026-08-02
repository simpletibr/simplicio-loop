"""JSON API for the MapperStore schema registry and migrations (#475)."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from ..store.registry import (
    REASON_CHECKSUM_DIVERGENCE,
    REASON_INCOMPATIBLE_WRITER,
    IncompatibleWriterError,
    MigrationEngine,
    RegistryChecksumError,
    RegistryError,
    negotiate,
)


def run_store_migrations_cli(argv: list[str], *, governed: bool = False) -> int:
    from ._store_migration import VERBS, run_migration_cli

    if governed and argv and (argv[0] in VERBS or (argv[0] == "backup" and "--source" not in argv)):
        if argv[0] == "backup" and "--source" not in argv:
            from ._store_operations import run_store_operations_cli

            return run_store_operations_cli(argv)
        return run_migration_cli(argv)
    if governed and argv and argv[0] in {"doctor", "restore", "repair", "metrics", "benchmark", "capacity"}:
        from ._store_operations import run_store_operations_cli

        return run_store_operations_cli(argv)
    if not argv or argv[0] not in {"plan", "apply", "status", "verify", "rollback", "negotiate"}:
        print(
            "usage: simplicio-mapper store-migrations <plan|apply|status|verify|rollback|negotiate> [--database PATH] [--json]",
            file=sys.stderr,
        )
        return 2
    verb = argv[0]
    database = Path("catalog.sqlite")
    json_mode = "--json" in argv
    target = None
    negotiation_args = {
        "reader_min": 1,
        "reader_max": 2,
        "writer_min": 1,
        "writer_max": 2,
        "reader_capabilities": None,
        "writer_capabilities": None,
    }
    i = 1
    while i < len(argv):
        if argv[i] == "--database" and i + 1 < len(argv):
            database = Path(argv[i + 1])
            i += 2
        elif argv[i] == "--target" and i + 1 < len(argv):
            try:
                target = int(argv[i + 1])
                if target < 0:
                    raise ValueError
            except ValueError:
                payload = {
                    "schema": "simplicio.mapper-store.error/v1",
                    "ok": False,
                    "error_type": "ValueError",
                    "reason_code": "INVALID_ARGUMENT",
                    "reason": "--target requires an integer",
                }
                print(
                    json.dumps(payload, sort_keys=True) if json_mode else payload["reason"],
                    file=sys.stderr if not json_mode else sys.stdout,
                )
                return 1
            i += 2
        elif argv[i] in {"--reader-min", "--reader-max", "--writer-min", "--writer-max"} and i + 1 < len(
            argv
        ):
            key = argv[i][2:].replace("-", "_")
            try:
                negotiation_args[key] = int(argv[i + 1])
            except ValueError:
                payload = {
                    "schema": "simplicio.mapper-store.error/v1",
                    "ok": False,
                    "error_type": "ValueError",
                    "reason_code": "INVALID_ARGUMENT",
                    "reason": f"{argv[i]} requires an integer",
                }
                print(
                    json.dumps(payload, sort_keys=True) if json_mode else payload["reason"],
                    file=sys.stdout if json_mode else sys.stderr,
                )
                return 1
            i += 2
        elif argv[i] in {"--reader-capabilities", "--writer-capabilities"} and i + 1 < len(argv):
            key = argv[i][2:].replace("-", "_")
            negotiation_args[key] = {item for item in argv[i + 1].split(",") if item}
            i += 2
        elif argv[i] == "--json":
            json_mode = True
            i += 1
        else:
            payload = {
                "schema": "simplicio.mapper-store.error/v1",
                "ok": False,
                "error_type": "ValueError",
                "reason_code": "INVALID_ARGUMENT",
                "reason": f"unknown option or missing value: {argv[i]}",
            }
            print(
                json.dumps(payload, sort_keys=True) if json_mode else payload["reason"],
                file=sys.stdout if json_mode else sys.stderr,
            )
            return 1
    try:
        if verb == "negotiate":
            payload = negotiate(**negotiation_args, strict=False)
        else:
            engine = MigrationEngine(database)
            if verb == "apply":
                payload = engine.apply(target, **negotiation_args)
            elif verb == "plan":
                payload = engine.plan(target)
            elif verb == "rollback":
                payload = engine.rollback(**negotiation_args)
            else:
                payload = getattr(engine, verb)()
    except (RegistryError, ValueError, OSError, sqlite3.Error) as error:
        payload = {
            "schema": "simplicio.mapper-store.error/v1",
            "ok": False,
            "error_type": type(error).__name__,
            "reason_code": (
                REASON_CHECKSUM_DIVERGENCE
                if isinstance(error, RegistryChecksumError)
                else REASON_INCOMPATIBLE_WRITER
                if isinstance(error, IncompatibleWriterError)
                else "SQLITE_ERROR"
                if isinstance(error, sqlite3.Error)
                else "INVALID_ARGUMENT"
                if isinstance(error, ValueError)
                else "REGISTRY_ERROR"
            ),
            "reason": str(error),
        }
        if not json_mode:
            print(payload["reason"], file=sys.stderr)
        else:
            print(json.dumps(payload, sort_keys=True))
        return 1
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"{verb}: {payload.get('status', payload.get('valid', payload.get('current_version', 'ok')))}")
    return 0
