"""Read-only diagnostics for the MapperStore cutover window (#1027/#1028).

The inspector deliberately does not open a database in write mode, run DDL,
copy rows, or infer a successful migration from the presence of one file.  It
only inventories known legacy/canonical paths, validates SQLite file headers,
and reads migration/route receipts so a caller can decide whether migration,
rollback, or reconciliation is safe.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.storage-cutover-doctor/v1"
_SQLITE_HEADER = b"SQLite format 3\x00"

_LEGACY_RELATIVE_PATHS = (
    ".simplicio-loop/orchestrator/queue.sqlite3",
    ".simplicio-loop/orchestrator/agent-slots.sqlite",
    ".simplicio-loop/orchestrator/agent-slots.sqlite3",
    ".simplicio-loop/orchestrator/run-journal.sqlite",
    ".simplicio-loop/orchestrator/run-journal.sqlite3",
    ".simplicio-loop/orchestrator/hookwall.sqlite3",
)
_RUN_LEGACY_NAMES = ("run-journal.sqlite", "run-journal.sqlite3", "hookwall.sqlite3")
_MIGRATION_MARKERS = (
    ".simplicio-loop/storage-migration.json",
    ".simplicio-loop/mapper-store-migration.json",
    ".simplicio-loop/orchestrator/storage-migration.json",
    ".simplicio-loop/orchestrator/mapper-store-migration.json",
    ".simplicio-loop/storage.migrating",
    ".simplicio-loop/mapper-store.migrating",
)
_ROUTE_RECEIPT_GLOB = ".simplicio-loop/loop-runs/*/storage-route-receipt.json"


def _path_label(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _file_observation(path: Path, root: Path) -> dict[str, Any]:
    try:
        size = path.stat().st_size
        header = path.read_bytes()[: len(_SQLITE_HEADER)]
    except OSError as exc:
        return {
            "path": _path_label(path, root),
            "status": "UNREADABLE",
            "error": str(exc),
        }
    valid = size >= len(_SQLITE_HEADER) and header == _SQLITE_HEADER
    return {
        "path": _path_label(path, root),
        "status": "VALID" if valid else "CORRUPT",
        "size_bytes": size,
        "sqlite_header": valid,
    }


def _discover_legacy_paths(root: Path) -> list[Path]:
    paths = [root / relative for relative in _LEGACY_RELATIVE_PATHS]
    runs_root = root / ".simplicio-loop" / "loop-runs"
    if runs_root.is_dir():
        for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
            paths.extend(run_dir / name for name in _RUN_LEGACY_NAMES)
    return sorted({path for path in paths if path.is_file()})


def _migration_observations(root: Path) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for relative in _MIGRATION_MARKERS:
        path = root / relative
        if not path.is_file():
            continue
        observation: dict[str, Any] = {"path": relative, "status": "OBSERVED"}
        if path.suffix == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError) as exc:
                observation.update({"status": "CORRUPT", "error": str(exc)})
            else:
                if not isinstance(payload, dict):
                    observation.update({"status": "CORRUPT", "error": "marker is not an object"})
                else:
                    observation["payload"] = payload
                    state = str(payload.get("status") or payload.get("phase") or "").lower()
                    observation["migration_state"] = state or "unknown"
        else:
            observation["migration_state"] = "migrating"
        observations.append(observation)
    return observations


def _route_observations(root: Path) -> tuple[list[dict[str, Any]], set[str], bool]:
    observations: list[dict[str, Any]] = []
    selected: set[str] = set()
    invalid = False
    for path in sorted(root.glob(_ROUTE_RECEIPT_GLOB)):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError) as exc:
            observations.append({
                "path": _path_label(path, root),
                "status": "CORRUPT",
                "error": str(exc),
            })
            invalid = True
            continue
        route = payload.get("selected") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != "simplicio.loop-store-route-receipt/v1"
            or route not in {"legacy", "shadow", "mapper"}
        ):
            observations.append({
                "path": _path_label(path, root),
                "status": "CORRUPT",
                "error": "invalid route receipt shape",
            })
            invalid = True
            continue
        selected.add(str(route))
        observations.append({
            "path": _path_label(path, root),
            "status": "OBSERVED",
            "selected": route,
            "generation": payload.get("generation"),
            "receipt_hash": payload.get("receipt_hash"),
        })
    return observations, selected, invalid


def inspect_storage_cutover(
    repo_root: str | Path,
    *,
    canonical_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a side-effect-free cutover report for one repository root."""

    root = Path(repo_root).expanduser().absolute()
    canonical = (
        Path(canonical_path).expanduser().absolute()
        if canonical_path is not None
        else root / ".simplicio-loop" / "data" / "operations.sqlite"
    )
    legacy_paths = _discover_legacy_paths(root)
    legacy = [_file_observation(path, root) for path in legacy_paths]
    canonical_observation = (
        _file_observation(canonical, root) if canonical.is_file() else None
    )
    migrations = _migration_observations(root)
    routes, selected_routes, invalid_route = _route_observations(root)

    corrupt_paths = [
        item["path"] for item in legacy + ([canonical_observation] if canonical_observation else [])
        if item.get("status") in {"CORRUPT", "UNREADABLE"}
    ]
    corrupt_paths.extend(item["path"] for item in migrations if item.get("status") == "CORRUPT")
    corrupt_paths.extend(item["path"] for item in routes if item.get("status") == "CORRUPT")
    migration_active = any(
        item.get("migration_state") in {"migrating", "running", "in_progress"}
        for item in migrations
    )
    legacy_present = bool(legacy)
    canonical_present = bool(canonical_observation)
    split_brain = (
        legacy_present and canonical_present
        or (legacy_present and "mapper" in selected_routes)
        or len(selected_routes) > 1
    )

    if migration_active:
        status = "MIGRATING"
        next_action = "finish_or_rollback_the_recorded_migration_before_writes"
    elif corrupt_paths or invalid_route:
        status = "CORRUPT"
        next_action = "backup_and_reconcile_corrupt_receipts_or_stores"
    elif split_brain:
        status = "SPLIT_BRAIN"
        next_action = "stop_writers_and_run_mapper_cutover_reconciliation"
    elif legacy_present:
        status = "LEGACY_PRESENT"
        next_action = "run_backup_shadow_read_and_explicit_mapper_cutover"
    elif canonical_present:
        status = "CLEAN"
        next_action = "continue_with_mapper_store_and_keep_legacy_writers_disabled"
    else:
        status = "UNVERIFIED"
        next_action = "initialize_mapper_store_explicitly_then_re-run_doctor"

    writer_authority = (
        "none"
        if status in {"UNVERIFIED", "CORRUPT", "SPLIT_BRAIN", "MIGRATING"}
        else "loop-legacy-read-only"
        if legacy_present
        else "mapper-store"
        if canonical_present
        else "none"
    )
    return {
        "schema": SCHEMA,
        "status": status,
        "repo_root": str(root),
        "canonical_store": canonical_observation,
        "legacy_stores": legacy,
        "route_receipts": routes,
        "migration_markers": migrations,
        "corrupt_paths": sorted(set(corrupt_paths)),
        "legacy_read_only": legacy_present,
        "writer_authority": writer_authority,
        "cutover_ready": status == "CLEAN",
        "effects_attempted": False,
        "next_action": next_action,
    }


__all__ = ["SCHEMA", "inspect_storage_cutover"]
