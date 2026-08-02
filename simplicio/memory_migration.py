"""Hash-bound backup and restore receipts for the Markdown memory store."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from .memory_store import validate_memory

BACKUP_SCHEMA = "simplicio.dev-cli.memory-backup/v1"
MANIFEST_NAME = ".simplicio-memory-backup.json"


def _files(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != MANIFEST_NAME):
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        rows.append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return rows


def _digest(rows: list[dict[str, Any]]) -> str:
    body = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _manifest(root: Path, *, source: Path) -> dict[str, Any]:
    validation = validate_memory(root=root)
    rows = _files(root)
    return {
        "schema": BACKUP_SCHEMA,
        "source": str(source.resolve()),
        "files": rows,
        "file_count": len(rows),
        "files_digest": _digest(rows),
        "notes": validation.get("notes", 0),
        "entries": validation.get("entries", 0),
        "validation_ok": validation.get("ok", False),
    }


def backup_memory(root: str | Path, destination: str | Path) -> dict[str, Any]:
    source = Path(root).resolve()
    target = Path(destination).resolve()
    validation = validate_memory(root=source)
    if not validation["ok"]:
        return {
            "schema": BACKUP_SCHEMA,
            "status": "blocked",
            "reason": "memory_validation_failed",
            "validation": validation,
        }
    if not source.is_dir():
        return {"schema": BACKUP_SCHEMA, "status": "blocked", "reason": "memory_store_missing"}
    try:
        target.relative_to(source)
    except ValueError:
        pass
    else:
        return {"schema": BACKUP_SCHEMA, "status": "blocked", "reason": "backup_inside_source"}
    if target.exists():
        return {"schema": BACKUP_SCHEMA, "status": "blocked", "reason": "backup_destination_exists"}
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    manifest = _manifest(target, source=source)
    (target / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"schema": BACKUP_SCHEMA, "status": "ok", "operation": "backup", "manifest": manifest}


def _verify_backup(backup: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        manifest = json.loads((backup / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "backup_manifest_invalid"
    if not isinstance(manifest, dict) or manifest.get("schema") != BACKUP_SCHEMA:
        return None, "backup_schema_invalid"
    rows = _files(backup)
    if rows != manifest.get("files") or _digest(rows) != manifest.get("files_digest"):
        return None, "backup_hash_mismatch"
    return manifest, None


def restore_memory(backup: str | Path, root: str | Path, *, apply: bool = False) -> dict[str, Any]:
    source = Path(backup).resolve()
    target = Path(root).resolve()
    manifest, error = _verify_backup(source)
    if error:
        return {"schema": BACKUP_SCHEMA, "status": "blocked", "operation": "restore", "reason": error}
    if not apply:
        return {
            "schema": BACKUP_SCHEMA,
            "status": "dry_run",
            "operation": "restore",
            "apply_required": True,
            "manifest": manifest,
        }
    rollback = target.with_name(target.name + ".rollback")
    if rollback.exists():
        return {
            "schema": BACKUP_SCHEMA,
            "status": "blocked",
            "operation": "restore",
            "reason": "rollback_exists",
        }
    if target.exists():
        target.rename(rollback)
    try:
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(MANIFEST_NAME))
    except OSError:
        if target.exists():
            shutil.rmtree(target)
        if rollback.exists():
            rollback.rename(target)
        raise
    return {
        "schema": BACKUP_SCHEMA,
        "status": "ok",
        "operation": "restore",
        "rollback": str(rollback) if rollback.exists() else None,
        "manifest": manifest,
    }
