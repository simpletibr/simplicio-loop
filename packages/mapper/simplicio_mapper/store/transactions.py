"""Bounded SQLite transaction/retry and fence hooks."""

from __future__ import annotations

import random
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from .connection import StoreConnection, StoreError


class TransactionError(StoreError):
    """Raised when transaction setup or cleanup fails."""


class FenceViolationError(TransactionError):
    """Raised before DML when a writer fence is stale."""


@dataclass(frozen=True)
class FenceValidator:
    """Small hook that lets a caller reject stale writers before BEGIN."""

    validate: Callable[[], bool]
    fence_id: str

    def assert_current(self) -> None:
        if not self.validate():
            raise FenceViolationError(f"stale fence rejected: {self.fence_id}")


class TransactionConnection:
    """Connection facade that revalidates the writer fence before every SQL call."""

    def __init__(self, store: StoreConnection, fence: FenceValidator | None) -> None:
        self._store = store
        self._fence = fence

    def _assert_fence(self) -> None:
        if self._fence is not None:
            self._fence.assert_current()

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> TransactionCursor:
        self._assert_fence()
        return TransactionCursor(self._store.connection.execute(sql, parameters), self._fence)

    def executemany(self, sql: str, parameters: object) -> TransactionCursor:
        self._assert_fence()
        return TransactionCursor(self._store.connection.executemany(sql, parameters), self._fence)

    def executescript(self, sql: str) -> None:
        raise TransactionError("executescript is disabled because SQLite commits it implicitly")

    def cursor(self) -> TransactionCursor:
        self._assert_fence()
        return TransactionCursor(self._store.connection.cursor(), self._fence)

    def __getattr__(self, name: str) -> object:
        if name in {"connection", "commit", "rollback"}:
            raise TransactionError("raw transaction controls are not exposed")
        return getattr(self._store.connection, name)


class TransactionCursor:
    """Cursor facade that preserves fence validation for cursor-based DML."""

    def __init__(self, cursor: sqlite3.Cursor, fence: FenceValidator | None) -> None:
        self._cursor = cursor
        self._fence = fence

    def _assert_fence(self) -> None:
        if self._fence is not None:
            self._fence.assert_current()

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> TransactionCursor:
        self._assert_fence()
        self._cursor.execute(sql, parameters)
        return self

    def executemany(self, sql: str, parameters: object) -> TransactionCursor:
        self._assert_fence()
        self._cursor.executemany(sql, parameters)
        return self

    def __getattr__(self, name: str) -> object:
        if name == "connection":
            raise TransactionError("raw SQLite connection is not exposed by a fenced cursor")
        return getattr(self._cursor, name)

    def __iter__(self):
        return iter(self._cursor)


@contextmanager
def transaction(
    store: StoreConnection,
    mode: str | None = None,
    *,
    fence: FenceValidator | None = None,
) -> Iterator[TransactionConnection]:
    """Begin a transaction and guarantee rollback on every exception."""

    if store.profile.mode.value in {"read-only", "backup"}:
        raise TransactionError("read-only/backup profiles cannot start a write transaction")
    if store._transaction_active or store._connection.in_transaction:
        raise TransactionError("nested transactions are not supported")
    selected = (mode or store.profile.transaction_mode).upper()
    if selected not in {"DEFERRED", "IMMEDIATE", "EXCLUSIVE"}:
        raise TransactionError(f"invalid transaction mode: {selected}")
    if fence is not None:
        fence.assert_current()
    try:
        store._connection.execute(f"BEGIN {selected}")
        store._transaction_active = True
        store._active_fence = fence
        yield TransactionConnection(store, fence)
        if fence is not None:
            fence.assert_current()
    except BaseException:
        if store._connection.in_transaction:
            store._connection.rollback()
        raise
    else:
        try:
            store._connection.commit()
        except Exception:
            if store._connection.in_transaction:
                store._connection.rollback()
            raise
    finally:
        store._active_fence = None
        store._transaction_active = False


def is_busy_error(error: BaseException) -> bool:
    if not isinstance(error, sqlite3.OperationalError):
        return False
    code = getattr(error, "sqlite_errorcode", None)
    busy_code = getattr(sqlite3, "SQLITE_BUSY", 5)
    locked_code = getattr(sqlite3, "SQLITE_LOCKED", 6)
    if code is not None and code & 0xFF in {busy_code, locked_code}:
        return True
    return str(error).lower().strip() in {
        "database is locked",
        "database is busy",
        "database table is locked",
        "database schema is locked",
    }


def run_with_retry(
    operation: Callable[[], object],
    *,
    deadline_seconds: float = 5.0,
    max_attempts: int = 5,
    base_delay_seconds: float = 0.01,
    jitter_seconds: float = 0.005,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    randomizer: Callable[[], float] = random.random,
) -> object:
    """Retry only busy/locked operations until deadline and then re-raise."""

    if deadline_seconds < 0 or max_attempts < 1:
        raise ValueError("deadline_seconds must be non-negative and max_attempts must be positive")
    started = clock()
    attempt = 0
    while True:
        attempt += 1
        try:
            return operation()
        except Exception as error:
            if not is_busy_error(error) or attempt >= max_attempts:
                raise
            elapsed = clock() - started
            remaining = deadline_seconds - elapsed
            if remaining <= 0:
                raise
            delay = min(base_delay_seconds * (2 ** (attempt - 1)) + jitter_seconds * randomizer(), remaining)
            sleeper(delay)
            if clock() - started >= deadline_seconds:
                raise
