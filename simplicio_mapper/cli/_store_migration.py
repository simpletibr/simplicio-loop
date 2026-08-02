"""CLI for governed legacy MapperStore migration (#479)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..store.migration import MigrationCoordinator, MigrationCoordinatorError

VERBS = {"discover", "plan", "backup", "import", "validate", "shadow", "cutover", "rollback", "status"}

_HELP = """usage: simplicio-mapper store-migrations <verb> [options]

Plan, apply, validate, inspect or roll back governed MapperStore migrations.
Verbs: discover, plan, backup, import, validate, shadow, cutover, rollback, status.
Use --database PATH, --source NAME=PATH, --dry-run or --json as needed.
"""


def _error(reason_code: str, reason: str, json_mode: bool) -> int:
    payload = {
        "schema": "simplicio.mapper-store.error/v1",
        "ok": False,
        "reason_code": reason_code,
        "reason": reason,
    }
    print(
        json.dumps(payload, sort_keys=True) if json_mode else reason,
        file=sys.stdout if json_mode else sys.stderr,
    )
    return 1


def run_migration_cli(argv: list[str]) -> int:
    if "--help" in argv or "-h" in argv:
        print(_HELP, end="")
        return 0
    verb = argv[0] if argv else ""
    if verb not in VERBS:
        return 2
    database = Path("mapper-store.sqlite")
    state = None
    backup_dir = None
    sources: dict[str, Path] = {}
    json_mode = "--json" in argv
    dry_run = False
    index = 1
    while index < len(argv):
        option = argv[index]
        if option in {"--database", "--state", "--backup-dir", "--source"} and index + 1 < len(argv):
            value = argv[index + 1]
            if option == "--database":
                database = Path(value)
            elif option == "--state":
                state = Path(value)
            elif option == "--backup-dir":
                backup_dir = Path(value)
            else:
                if "=" not in value:
                    return _error("INVALID_ARGUMENT", "--source requires NAME=PATH", json_mode)
                name, path = value.split("=", 1)
                if not name or not path:
                    return _error("INVALID_ARGUMENT", "--source requires NAME=PATH", json_mode)
                sources[name] = Path(path)
            index += 2
        elif option == "--json":
            json_mode = True
            index += 1
        elif option == "--dry-run":
            dry_run = True
            index += 1
        else:
            return _error("INVALID_ARGUMENT", f"unknown option or missing value: {option}", json_mode)
    if verb not in {"status", "plan"} and not sources:
        return _error("INVALID_ARGUMENT", "at least one --source NAME=PATH is required", json_mode)
    try:
        coordinator = MigrationCoordinator(database, sources, state_path=state, backup_dir=backup_dir)
        if verb == "discover":
            payload = coordinator.discover(dry_run=dry_run)
        elif verb == "plan":
            payload = coordinator.plan(dry_run=True if not dry_run else dry_run)
        elif verb == "backup":
            payload = coordinator.backup(dry_run=dry_run)
        elif verb == "import":
            payload = coordinator.import_data(dry_run=dry_run)
        elif verb == "validate":
            payload = coordinator.validate(record=not dry_run)
        elif verb == "shadow":
            payload = coordinator.shadow(dry_run=dry_run)
        elif verb == "cutover":
            payload = coordinator.cutover(dry_run=dry_run)
        elif verb == "rollback":
            payload = coordinator.rollback(dry_run=dry_run)
        else:
            payload = coordinator.status()
    except (MigrationCoordinatorError, OSError, ValueError) as error:
        return _error(getattr(error, "reason_code", "MIGRATION_ERROR"), str(error), json_mode)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"{verb}: {payload.get('status', payload.get('state', payload.get('ok', 'ok')))}")
    return 0


__all__ = ["VERBS", "run_migration_cli"]
