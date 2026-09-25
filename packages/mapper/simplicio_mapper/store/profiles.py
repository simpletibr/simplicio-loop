"""Connection profiles and effective SQLite settings."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class StoreMode(str, Enum):
    READ_ONLY = "read-only"
    READ_WRITE = "read-write"
    MIGRATION = "migration"
    BACKUP = "backup"


@dataclass(frozen=True)
class StoreProfile:
    """Explicit policy for one SQLite connection."""

    mode: StoreMode = StoreMode.READ_WRITE
    journal_mode: str = "WAL"
    synchronous: str = "NORMAL"
    foreign_keys: bool = True
    busy_timeout_ms: int = 5_000
    timeout_seconds: float = 5.0
    transaction_mode: str = "IMMEDIATE"
    create: bool = True
    query_only: bool = False

    def __post_init__(self) -> None:
        try:
            normalized_mode = StoreMode(self.mode)
        except ValueError as error:
            raise ValueError("mode must be read-only, read-write, migration, or backup") from error
        object.__setattr__(self, "mode", normalized_mode)
        if self.busy_timeout_ms < 0 or self.busy_timeout_ms > 120_000:
            raise ValueError("busy_timeout_ms must be between 0 and 120000")
        if self.timeout_seconds < 0 or self.timeout_seconds > 120:
            raise ValueError("timeout_seconds must be between 0 and 120")
        if self.transaction_mode.upper() not in {"DEFERRED", "IMMEDIATE", "EXCLUSIVE"}:
            raise ValueError("transaction_mode must be DEFERRED, IMMEDIATE, or EXCLUSIVE")
        if self.journal_mode.upper() not in {"WAL", "DELETE", "TRUNCATE", "PERSIST", "MEMORY", "OFF"}:
            raise ValueError("unsupported journal_mode")
        if self.synchronous.upper() not in {"OFF", "NORMAL", "FULL", "EXTRA"}:
            raise ValueError("unsupported synchronous level")
        if self.mode == StoreMode.READ_ONLY and self.create:
            object.__setattr__(self, "create", False)
        if self.mode == StoreMode.READ_ONLY and not self.query_only:
            object.__setattr__(self, "query_only", True)
        if self.mode == StoreMode.BACKUP:
            object.__setattr__(self, "create", False)
            object.__setattr__(self, "query_only", True)
        if self.mode == StoreMode.MIGRATION:
            object.__setattr__(self, "transaction_mode", "EXCLUSIVE")

    @classmethod
    def read_only(cls, **overrides: object) -> StoreProfile:
        return cls(mode=StoreMode.READ_ONLY, create=False, query_only=True, **overrides)

    @classmethod
    def read_write(cls, **overrides: object) -> StoreProfile:
        return cls(mode=StoreMode.READ_WRITE, **overrides)

    @classmethod
    def migration(cls, **overrides: object) -> StoreProfile:
        return cls(mode=StoreMode.MIGRATION, transaction_mode="EXCLUSIVE", **overrides)

    @classmethod
    def backup(cls, **overrides: object) -> StoreProfile:
        return cls(mode=StoreMode.BACKUP, create=False, query_only=True, **overrides)

    def with_mode(self, mode: StoreMode, **overrides: object) -> StoreProfile:
        return replace(self, mode=mode, **overrides)
