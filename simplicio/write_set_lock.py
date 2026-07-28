"""Write-set locks, capability leases and fencing (#365).

Loop owns concurrency policy. Dev CLI enforces mutual exclusion on write-set
paths and rejects stale fencing tokens before mutation.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Sequence


class LockError(RuntimeError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _normalize(path: str) -> str:
    value = path.replace("\\", "/").strip()
    if not value or value.startswith("/") or ".." in value.split("/"):
        raise LockError("UNSAFE_PATH", path)
    return value


class WriteSetLockManager:
    """SQLite-backed exclusive locks ordered by normalized path."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        state = self.root / ".simplicio"
        state.mkdir(parents=True, exist_ok=True)
        self.db_path = state / "write-set-locks.sqlite3"
        with self._db() as database:
            database.executescript(
                """
                CREATE TABLE IF NOT EXISTS locks(
                    path TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    lease_id TEXT NOT NULL,
                    fencing_token TEXT NOT NULL,
                    acquired_ns INTEGER NOT NULL
                );
                """
            )

    def _db(self) -> sqlite3.Connection:
        database = sqlite3.connect(self.db_path, isolation_level=None, timeout=30)
        database.execute("PRAGMA journal_mode=WAL")
        return database

    def acquire(
        self,
        paths: Sequence[str],
        *,
        owner: str,
        lease_id: str,
        fencing_token: str,
        active_fence: str | None = None,
    ) -> dict[str, Any]:
        if not owner or not lease_id or not fencing_token:
            raise LockError("LEASE_REQUIRED")
        if active_fence is not None and active_fence != fencing_token:
            raise LockError("STALE_FENCE", fencing_token)
        ordered = sorted({_normalize(path) for path in paths})
        if not ordered:
            raise LockError("EMPTY_WRITE_SET")
        now = time.time_ns()
        with self._db() as database:
            database.execute("BEGIN IMMEDIATE")
            for path in ordered:
                row = database.execute(
                    "SELECT owner, lease_id, fencing_token FROM locks WHERE path=?",
                    (path,),
                ).fetchone()
                if row and (row[0] != owner or row[1] != lease_id):
                    database.execute("ROLLBACK")
                    raise LockError("CONFLICT_BLOCKED", f"{path} held by {row[0]}")
                database.execute(
                    "INSERT INTO locks(path,owner,lease_id,fencing_token,acquired_ns) "
                    "VALUES(?,?,?,?,?) "
                    "ON CONFLICT(path) DO UPDATE SET owner=excluded.owner, "
                    "lease_id=excluded.lease_id, fencing_token=excluded.fencing_token, "
                    "acquired_ns=excluded.acquired_ns",
                    (path, owner, lease_id, fencing_token, now),
                )
            database.execute("COMMIT")
        return {
            "schema": "simplicio.write-set-lock-receipt/v1",
            "owner": owner,
            "lease_id": lease_id,
            "fencing_token": fencing_token,
            "paths": ordered,
            "status": "acquired",
        }

    def validate_fence(self, fencing_token: str, *, expected: str) -> None:
        if fencing_token != expected:
            raise LockError("STALE_FENCE", fencing_token)

    def release(self, *, owner: str, lease_id: str) -> dict[str, Any]:
        with self._db() as database:
            database.execute("BEGIN IMMEDIATE")
            database.execute(
                "DELETE FROM locks WHERE owner=? AND lease_id=?",
                (owner, lease_id),
            )
            database.execute("COMMIT")
        return {
            "schema": "simplicio.write-set-lock-receipt/v1",
            "owner": owner,
            "lease_id": lease_id,
            "status": "released",
        }

    def held_paths(self) -> list[str]:
        with self._db() as database:
            rows = database.execute("SELECT path FROM locks ORDER BY path").fetchall()
        return [str(row[0]) for row in rows]
