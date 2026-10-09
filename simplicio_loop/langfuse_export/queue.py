"""On-disk outbox and send ledger: nothing is dropped on a network failure, nothing is sent twice.

Each request body is one file ``<seq>.<kind>.json`` holding ``{kind, attempts, body, marks}``;
``marks`` are the ``[id, content_hash]`` pairs the request carries, recorded as sent only after the
server accepts it. Files are written atomically (tmp + rename) and sent in sequence order.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def content_hash(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


@dataclass(frozen=True)
class Item:
    path: Path
    kind: str
    seq: int


class Outbox:
    def __init__(self, queue_dir: Path, dead_dir: Path) -> None:
        self.queue_dir = Path(queue_dir)
        self.dead_dir = Path(dead_dir)

    def _next_seq(self) -> int:
        seqs = [item.seq for item in self.pending()]
        return (max(seqs) + 1) if seqs else 1

    def enqueue(
        self, kind: str, body: Any, marks: list[list[str]] | None = None
    ) -> Path:
        seq = self._next_seq()
        path = self.queue_dir / f"{seq:012d}.{kind}.json"
        _write_json(
            path, {"kind": kind, "attempts": 0, "body": body, "marks": marks or []}
        )
        return path

    def pending(self) -> list[Item]:
        if not self.queue_dir.is_dir():
            return []
        items = []
        for path in sorted(self.queue_dir.glob("*.json")):
            seq, _, kind = path.name.partition(".")
            items.append(Item(path=path, kind=kind[: -len(".json")], seq=int(seq)))
        return items

    def read(self, item: Item) -> dict[str, Any]:
        return json.loads(item.path.read_text(encoding="utf-8"))

    def ack(self, item: Item) -> None:
        item.path.unlink(missing_ok=True)

    def fail(self, item: Item, *, max_attempts: int) -> bool:
        """Count one failed attempt. True when the request was dead-lettered (attempts exhausted)."""
        record = self.read(item)
        record["attempts"] = int(record.get("attempts", 0)) + 1
        if record["attempts"] >= max_attempts:
            self.dead_dir.mkdir(parents=True, exist_ok=True)
            os.replace(item.path, self.dead_dir / item.path.name)
            return True
        _write_json(item.path, record)
        return False

    def dead_letter(self, item: Item) -> None:
        """A permanent rejection (4xx other than 429): keep it for inspection, never retry it."""
        self.dead_dir.mkdir(parents=True, exist_ok=True)
        os.replace(item.path, self.dead_dir / item.path.name)


class Ledger:
    """What the server has accepted (``sent``), what is queued (``pending``), what it rejected."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        data = (
            json.loads(self.path.read_text(encoding="utf-8"))
            if self.path.is_file()
            else {}
        )
        self.sent: dict[str, str] = dict(data.get("sent") or {})
        self.pending: dict[str, str] = dict(data.get("pending") or {})
        self.rejected: dict[str, str] = dict(data.get("rejected") or {})
        self.last_flush: float | None = data.get("last_flush")

    def wants(self, key: str, digest: str) -> bool:
        return not any(
            table.get(key) == digest
            for table in (self.sent, self.pending, self.rejected)
        )

    def mark_pending(self, key: str, digest: str) -> None:
        self.pending[key] = digest

    def mark_sent(self, marks: list[list[str]]) -> None:
        for key, digest in marks:
            self.sent[key] = digest
            if self.pending.get(key) == digest:
                del self.pending[key]

    def forget_pending(self, marks: list[list[str]]) -> None:
        for key, digest in marks:
            if self.pending.get(key) == digest:
                del self.pending[key]

    def mark_rejected(self, marks: list[list[str]]) -> None:
        for key, digest in marks:
            self.rejected[key] = digest
        self.forget_pending(marks)

    def save(self) -> None:
        _write_json(
            self.path,
            {
                "sent": self.sent,
                "pending": self.pending,
                "rejected": self.rejected,
                "last_flush": self.last_flush,
            },
        )


def mapping_of(record: Mapping[str, Any]) -> list[list[str]]:
    return [list(m) for m in record.get("marks") or []]
