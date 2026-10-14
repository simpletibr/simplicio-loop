"""On-disk outbox, send ledger and the export lock.

Each request body is one file ``<time_ns>-<uuid8>.<kind>.json`` holding ``{kind, attempts, body, marks}``.
``marks`` are the ``[id, content_hash]`` pairs the request carries; they are recorded as sent only after
the server accepts it. Names sort in enqueue order and never collide, so a drained queue cannot reuse a
number and a dead-lettered file is never overwritten. Files are written atomically (tmp + rename).
Export cycles hold ``ExportLock`` (POSIX ``flock``) so two runs cannot interleave on the same queue.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]


def content_hash(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


class ExportLock:
    """Exclusive lock on ``<dir>/.lock`` for the whole export cycle."""

    def __init__(self, directory: Path) -> None:
        if fcntl is None:
            raise RuntimeError(
                "the Langfuse exporter needs POSIX flock; it is not available on this platform"
            )
        self.path = Path(directory) / ".lock"
        self._fd: int | None = None

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None


@dataclass(frozen=True)
class Item:
    path: Path
    kind: str


class Outbox:
    def __init__(self, queue_dir: Path, dead_dir: Path) -> None:
        self.queue_dir = Path(queue_dir)
        self.dead_dir = Path(dead_dir)

    def enqueue(
        self, kind: str, body: Any, marks: list[list[str]] | None = None
    ) -> Path:
        path = (
            self.queue_dir / f"{time.time_ns():020d}-{uuid.uuid4().hex[:8]}.{kind}.json"
        )
        _write_json(
            path, {"kind": kind, "attempts": 0, "body": body, "marks": marks or []}
        )
        return path

    def pending(self) -> list[Item]:
        if not self.queue_dir.is_dir():
            return []
        items = []
        for path in sorted(self.queue_dir.glob("*.json")):
            kind = path.name.rsplit(".", 2)[-2]
            items.append(Item(path=path, kind=kind))
        return items

    def read(self, item: Item) -> dict[str, Any]:
        return json.loads(item.path.read_text(encoding="utf-8"))

    def ack(self, item: Item) -> None:
        item.path.unlink(missing_ok=True)

    def fail(self, item: Item, *, max_attempts: int) -> bool:
        """Count one retryable failure. True when attempts are exhausted and the file moved to ``dead/``."""
        record = self.read(item)
        record["attempts"] = int(record.get("attempts", 0)) + 1
        _write_json(item.path, record)  # the count is saved before the file can move
        if record["attempts"] >= max_attempts:
            self.dead_letter(item)
            return True
        return False

    def dead_letter(self, item: Item) -> None:
        self.dead_dir.mkdir(parents=True, exist_ok=True)
        os.replace(item.path, self.dead_dir / item.path.name)


class Ledger:
    """What the server has accepted (``sent``), what is queued (``pending``), what it finally refused (``rejected``)."""

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
        self.forget_pending(marks)

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
