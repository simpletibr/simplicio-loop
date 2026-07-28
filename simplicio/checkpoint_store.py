"""Atomic checkpoints and write-set-scoped rollback (#366)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Sequence


class CheckpointError(RuntimeError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _safe_rel(path: str) -> str:
    value = path.replace("\\", "/").strip()
    if not value or value.startswith("/") or ".." in value.split("/"):
        raise CheckpointError("PATH_ESCAPE", path)
    return value


def _file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CheckpointStore:
    """Capture and restore only write-set members under the repository root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.base = self.root / ".simplicio" / "checkpoints"
        self.base.mkdir(parents=True, exist_ok=True)

    def create(self, checkpoint_id: str, write_set: Sequence[str]) -> dict[str, Any]:
        if not checkpoint_id or "/" in checkpoint_id or "\\" in checkpoint_id:
            raise CheckpointError("CHECKPOINT_ID_INVALID", checkpoint_id)
        target = self.base / checkpoint_id
        if target.exists():
            raise CheckpointError("CHECKPOINT_EXISTS", checkpoint_id)
        files_dir = target / "files"
        files_dir.mkdir(parents=True)
        entries: list[dict[str, Any]] = []
        for raw in sorted({_safe_rel(item) for item in write_set}):
            source = self.root / raw
            if source.is_symlink():
                raise CheckpointError("SYMLINK_BLOCKED", raw)
            if source.exists() and not source.is_file():
                raise CheckpointError("NOT_A_FILE", raw)
            payload = {
                "path": raw,
                "existed": source.exists(),
                "sha256": _file_hash(source),
            }
            if source.exists():
                dest = files_dir / raw
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
            entries.append(payload)
        manifest = {
            "schema": "simplicio.checkpoint/v1",
            "checkpoint_id": checkpoint_id,
            "write_set": [item["path"] for item in entries],
            "entries": entries,
        }
        manifest_path = target / "manifest.json"
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        tmp = target / "manifest.json.tmp"
        tmp.write_text(encoded + "\n", encoding="utf-8")
        os.replace(tmp, manifest_path)
        manifest["checkpoint_hash"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return manifest

    def restore(self, checkpoint_id: str) -> dict[str, Any]:
        target = self.base / checkpoint_id
        manifest_path = target / "manifest.json"
        if not manifest_path.is_file():
            raise CheckpointError("CHECKPOINT_MISSING", checkpoint_id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        restored: list[str] = []
        for entry in manifest.get("entries", []):
            rel = _safe_rel(str(entry["path"]))
            live = self.root / rel
            if live.is_symlink():
                raise CheckpointError("SYMLINK_BLOCKED", rel)
            if entry.get("existed"):
                src = target / "files" / rel
                if not src.is_file():
                    raise CheckpointError("CHECKPOINT_BLOB_MISSING", rel)
                live.parent.mkdir(parents=True, exist_ok=True)
                tmp = live.with_suffix(live.suffix + ".ckpt-tmp")
                shutil.copy2(src, tmp)
                os.replace(tmp, live)
                if _file_hash(live) != entry.get("sha256"):
                    raise CheckpointError("HASH_MISMATCH", rel)
            else:
                if live.exists():
                    live.unlink()
            restored.append(rel)
        return {
            "schema": "simplicio.checkpoint-restore/v1",
            "checkpoint_id": checkpoint_id,
            "status": "restored",
            "restored": restored,
        }
