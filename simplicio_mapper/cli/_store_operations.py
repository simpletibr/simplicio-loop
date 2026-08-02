"""Operational MapperStore commands for doctor, backup, repair and metrics."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..store import (
    DoctorError,
    backup_store,
    capacity_report,
    doctor_store,
    metrics_for_store,
    repair_store,
    restore_store,
    run_benchmark,
    secure_export,
)

VERBS = {"doctor", "backup", "restore", "repair", "metrics", "benchmark", "capacity"}


def _error(reason_code: str, reason: str, json_mode: bool) -> int:
    payload = {
        "schema": "simplicio.mapper-store.error/v1",
        "ok": False,
        "reason_code": reason_code,
        "reason": reason,
    }
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) if json_mode else reason,
        file=sys.stdout if json_mode else sys.stderr,
    )
    return 1


def run_store_operations_cli(argv: list[str]) -> int:
    verb = argv[0] if argv else ""
    if verb not in VERBS:
        return 2
    json_mode = "--json" in argv
    database = Path("mapper-store.sqlite")
    destination: Path | None = None
    manifest: Path | None = None
    export_path: Path | None = None
    apply = False
    allow_overwrite = False
    authorization = None
    workers = (1, 6, 64)
    repetitions = 3
    i = 1
    while i < len(argv):
        option = argv[i]
        if option in {
            "--database",
            "--path",
            "--destination",
            "--backup",
            "--manifest",
            "--export",
        } and i + 1 < len(argv):
            value = Path(argv[i + 1])
            if option in {"--database", "--path"}:
                database = value
            elif option in {"--destination", "--backup"}:
                destination = value
            elif option == "--manifest":
                manifest = value
            else:
                export_path = value
            i += 2
        elif option == "--apply":
            apply = True
            i += 1
        elif option == "--allow-overwrite":
            allow_overwrite = True
            i += 1
        elif option == "--authorization" and i + 1 < len(argv):
            authorization = argv[i + 1]
            i += 2
        elif option == "--workers" and i + 1 < len(argv):
            workers = tuple(int(item) for item in argv[i + 1].split(",") if item)
            i += 2
        elif option == "--repetitions" and i + 1 < len(argv):
            repetitions = int(argv[i + 1])
            i += 2
        elif option == "--json":
            json_mode = True
            i += 1
        else:
            return _error("INVALID_ARGUMENT", f"unknown option or missing value: {option}", json_mode)
    try:
        if verb == "doctor":
            payload = doctor_store(database)
        elif verb == "capacity":
            payload = capacity_report(database)
        elif verb == "backup":
            if destination is None:
                return _error("INVALID_ARGUMENT", "--destination is required", json_mode)
            payload = backup_store(database, destination)
        elif verb == "restore":
            if destination is None:
                return _error("INVALID_ARGUMENT", "--destination is required", json_mode)
            payload = restore_store(
                database,
                destination,
                manifest=manifest,
                allow_overwrite=allow_overwrite,
                authorization=authorization,
            )
        elif verb == "repair":
            payload = repair_store(database, apply=apply, backup_manifest=manifest)
        elif verb == "metrics":
            payload = metrics_for_store(database)
        else:
            payload = run_benchmark(database, workers=workers, repetitions=repetitions)
        if export_path is not None:
            payload = {**payload, "export": secure_export(payload, export_path)}
    except (DoctorError, OSError, ValueError, json.JSONDecodeError) as error:
        return _error(getattr(error, "reason_code", "OPERATIONAL_ERROR"), str(error), json_mode)
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"{verb}: {payload.get('status', payload.get('state', 'ok'))}")
    return 0


__all__ = ["VERBS", "run_store_operations_cli"]
