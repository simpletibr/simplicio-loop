"""Deterministic post-run retrospective and durable lesson writer."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).lower()


def _iter_records(root: Path, run_id: str | None) -> Iterable[tuple[Path, dict[str, Any]]]:
    base = root / ".simplicio-loop" / "orchestrator" / "trajectory"
    paths = sorted(base.glob("*.jsonl")) if base.exists() else []
    if run_id:
        paths = [p for p in paths if p.stem == run_id]
    for path in paths:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield path, record


def _candidate(record: dict[str, Any]) -> str | None:
    for key in ("lesson", "learned", "retrospective", "lesson_text"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return re.sub(r"\s+", " ", value.strip())
    return None


def retrospective(root: str | Path = ".", run_id: str | None = None) -> dict[str, Any]:
    """Aggregate explicit trajectory lessons, deduplicate, and persist receipts."""
    repo = Path(root).resolve()
    records = list(_iter_records(repo, run_id))
    candidates: list[str] = []
    source_files: set[str] = set()
    for path, record in records:
        lesson = _candidate(record)
        if lesson:
            candidates.append(lesson)
            source_files.add(str(path.relative_to(repo)))

    base = repo / ".simplicio-loop" / "orchestrator"
    base.mkdir(parents=True, exist_ok=True)
    lessons_path = base / "lessons.jsonl"
    existing: dict[str, dict[str, Any]] = {}
    if lessons_path.exists():
        for line in lessons_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("fingerprint"):
                existing[row["fingerprint"]] = row

    new_count = 0
    merged_count = 0
    for lesson in candidates:
        fingerprint = hashlib.sha256(_norm(lesson).encode("utf-8")).hexdigest()
        if fingerprint in existing:
            existing[fingerprint]["hit_count"] = int(existing[fingerprint].get("hit_count", 1)) + 1
            existing[fingerprint]["last_seen"] = _stamp()
            merged_count += 1
            continue
        existing[fingerprint] = {"schema": "simplicio.lesson/v1", "fingerprint": fingerprint,
                                 "lesson": lesson, "hit_count": 1, "last_seen": _stamp()}
        new_count += 1
    lessons_path.write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in existing.values()), encoding="utf-8")

    index_path = base / "learn-index.json"
    index_path.write_text(json.dumps({"schema": "simplicio.learn-index/v1", "last_run": _stamp(),
                                      "run_id": run_id, "sources": sorted(source_files)},
                                     ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {"schema": "simplicio.retrospective-receipt/v1", "run_id": run_id,
               "records_seen": len(records), "candidates": len(candidates), "new": new_count,
               "merged": merged_count, "lessons_path": str(lessons_path), "index_path": str(index_path),
               "created_at": _stamp()}
    receipt_path = base / "retrospective-receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt
