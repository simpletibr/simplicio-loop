"""SQLite connection factory for MapperStore/v1."""

from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .paths import StorePathError, assert_within_root, reject_network_path, reject_symlink_components
from .profiles import StoreMode, StoreProfile


class StoreError(RuntimeError):
    """Base class for typed MapperStore failures."""


class StoreMissingError(StoreError):
    """Raised when a read-only connection targets a missing database."""


class StoreIntegrityError(StoreError):
    """Raised when a connection cannot establish required pragmas."""


@dataclass(frozen=True)
class WriterIdentity:
    component: str
    process_id: int
    instance_id: str

    @classmethod
    def create(cls, component: str, instance_id: str | None = None) -> WriterIdentity:
        if not component or not component.strip():
            raise ValueError("writer component is required")
        return cls(component.strip(), __import__("os").getpid(), instance_id or uuid.uuid4().hex)


class ConnectionCursor:
    """Public cursor view that consults the owning connection fence."""

    def __init__(self, store: StoreConnection, cursor: sqlite3.Cursor) -> None:
        self._store = store
        self._cursor = cursor

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> ConnectionCursor:
        self._store._assert_active_fence()
        self._store._validate_sql(sql)
        self._cursor.execute(sql, parameters)
        return self

    def executemany(self, sql: str, parameters: object) -> ConnectionCursor:
        self._store._assert_active_fence()
        self._store._validate_sql(sql)
        self._cursor.executemany(sql, parameters)
        return self

    def __getattr__(self, name: str) -> object:
        if name == "connection":
            raise StoreError("raw SQLite connection is not exposed")
        return getattr(self._cursor, name)

    def __iter__(self):
        return iter(self._cursor)


class ConnectionView:
    """Safe public view; raw transaction controls remain private to the owner."""

    def __init__(self, store: StoreConnection) -> None:
        self._store = store

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> ConnectionCursor:
        return self._store.execute(sql, parameters)

    def executemany(self, sql: str, parameters: object) -> ConnectionCursor:
        self._store._assert_active_fence()
        self._store._validate_sql(sql)
        return ConnectionCursor(self._store, self._store._connection.executemany(sql, parameters))

    def cursor(self) -> ConnectionCursor:
        self._store._assert_active_fence()
        return ConnectionCursor(self._store, self._store._connection.cursor())

    def __getattr__(self, name: str) -> object:
        if name in {"in_transaction", "isolation_level", "total_changes", "row_factory", "text_factory"}:
            return getattr(self._store._connection, name)
        raise StoreError(f"SQLite member is not exposed by the safe view: {name}")


class StoreConnection:
    """Owned SQLite connection with verified effective settings."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        path: Path,
        profile: StoreProfile,
        *,
        writer_identity: WriterIdentity | None = None,
        correlation_id: str | None = None,
    ) -> None:
        self._connection = connection
        self._view = ConnectionView(self)
        self.path = path
        self.profile = profile
        self.writer_identity = writer_identity
        self.correlation_id = correlation_id or uuid.uuid4().hex
        self._closed = False
        self._active_fence = None
        self._transaction_active = False

    @classmethod
    def open(
        cls,
        path: str | Path,
        profile: StoreProfile | None = None,
        *,
        root: Path | None = None,
        writer_identity: WriterIdentity | None = None,
        correlation_id: str | None = None,
        immutable: bool | None = None,
    ) -> StoreConnection:
        selected = profile or StoreProfile.read_write()
        if writer_identity is None and selected.mode not in {StoreMode.READ_ONLY, StoreMode.BACKUP}:
            writer_identity = WriterIdentity.create("simplicio_mapper.store")
        raw = Path(path).expanduser()
        reject_network_path(path)
        reject_symlink_components(path)
        if not raw.name or raw.name in {".", ".."}:
            raise StorePathError("database path must name a file")
        if root is not None:
            resolved = assert_within_root(root, raw)
        else:
            resolved = raw.resolve(strict=False)
        if selected.mode == StoreMode.READ_ONLY or selected.mode == StoreMode.BACKUP:
            if not resolved.is_file():
                raise StoreMissingError(f"read-only database does not exist: {resolved}")
        elif not selected.create and not resolved.is_file():
            raise StoreMissingError(f"database does not exist and create=False: {resolved}")
        else:
            resolved.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            try:
                resolved.parent.chmod(0o700)
            except OSError:
                pass
            if root is not None:
                resolved = assert_within_root(root, raw)
        if selected.mode in {StoreMode.READ_ONLY, StoreMode.BACKUP}:
            if immutable is None:
                immutable = True
            query = "mode=ro"
            if immutable:
                query += "&immutable=1"
            uri = f"file:{quote(resolved.as_posix(), safe='/:')}?{query}"
            connection = sqlite3.connect(
                uri, uri=True, timeout=selected.timeout_seconds, isolation_level=None
            )
        else:
            connection = sqlite3.connect(resolved, timeout=selected.timeout_seconds, isolation_level=None)
        try:
            cls._configure(connection, selected)
        except Exception:
            connection.close()
            raise
        return cls(
            connection, resolved, selected, writer_identity=writer_identity, correlation_id=correlation_id
        )

    @staticmethod
    def _configure(connection: sqlite3.Connection, profile: StoreProfile) -> None:
        connection.execute(f"PRAGMA busy_timeout={int(profile.busy_timeout_ms)}")
        if profile.mode not in {StoreMode.READ_ONLY, StoreMode.BACKUP}:
            effective_journal = str(
                connection.execute(f"PRAGMA journal_mode={profile.journal_mode}").fetchone()[0]
            ).upper()
            if effective_journal != profile.journal_mode.upper():
                raise StoreIntegrityError(
                    f"requested journal_mode={profile.journal_mode}, got {effective_journal}"
                )
            connection.execute(f"PRAGMA synchronous={profile.synchronous}")
        connection.execute(f"PRAGMA foreign_keys={'ON' if profile.foreign_keys else 'OFF'}")
        if profile.query_only:
            connection.execute("PRAGMA query_only=ON")
        foreign_keys = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])
        if profile.foreign_keys and foreign_keys != 1:
            raise StoreIntegrityError("foreign_keys pragma was not enabled")

    def effective_settings(self) -> dict[str, object]:
        journal_mode = str(self._connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if (
            self.profile.mode in {StoreMode.READ_ONLY, StoreMode.BACKUP}
            and self.path.with_name(self.path.name + "-wal").exists()
        ):
            journal_mode = "wal"
        return {
            "path": str(self.path),
            "mode": self.profile.mode.value,
            "journal_mode": journal_mode,
            "foreign_keys": bool(self._connection.execute("PRAGMA foreign_keys").fetchone()[0]),
            "busy_timeout_ms": int(self._connection.execute("PRAGMA busy_timeout").fetchone()[0]),
            "query_only": bool(self._connection.execute("PRAGMA query_only").fetchone()[0]),
            "correlation_id": self.correlation_id,
            "writer": self.writer_identity.component if self.writer_identity else None,
        }

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> ConnectionCursor:
        if self._closed:
            raise StoreError("connection is closed")
        self._validate_sql(sql)
        self._assert_active_fence()
        return ConnectionCursor(self, self._connection.execute(sql, parameters))

    def _validate_sql(self, sql: str) -> None:
        cleaned_sql = re.sub(
            r"--[^\n]*|/\*.*?\*/|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"",
            " ",
            sql,
            flags=re.DOTALL,
        ).lstrip()
        statement = cleaned_sql
        keyword_match = re.match(r"([A-Za-z]+)", statement)
        statement = keyword_match.group(1).upper() if keyword_match else ""
        if statement == "WITH":
            depth = 0
            for token in re.finditer(r"[A-Za-z]+|[()]", cleaned_sql[4:]):
                if token.group() == "(":
                    depth += 1
                elif token.group() == ")":
                    depth = max(0, depth - 1)
                elif depth == 0 and token.group().upper() in {
                    "SELECT",
                    "INSERT",
                    "UPDATE",
                    "DELETE",
                    "REPLACE",
                    "COMMIT",
                    "ROLLBACK",
                }:
                    statement = token.group().upper()
                    break
        if statement in {"BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE"}:
            raise StoreError("transaction controls are owned by transaction()")
        if statement == "PRAGMA" and "=" in cleaned_sql and not self._transaction_active:
            raise StoreError("mutable PRAGMA requires an active transaction()")
        if (
            statement in {"INSERT", "UPDATE", "DELETE", "REPLACE"}
            and not self._transaction_active
            and self.profile.mode not in {StoreMode.READ_ONLY, StoreMode.BACKUP}
        ):
            raise StoreError("DML requires an active transaction()")

    def _assert_active_fence(self) -> None:
        if self._active_fence is not None:
            self._active_fence.assert_current()

    @property
    def connection(self) -> ConnectionView:
        return self._view

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True

    def __enter__(self) -> StoreConnection:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()
