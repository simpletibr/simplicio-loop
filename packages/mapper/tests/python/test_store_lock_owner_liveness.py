"""A lock owner that exists under another user is live, never stale.

``os.kill(pid, 0)`` raises ``PermissionError`` (EPERM) when the pid exists but
belongs to another user. Only ``ProcessLookupError`` (ESRCH) proves the owner is
gone, so only ESRCH may mark a store lock stale or inactive.
"""

from __future__ import annotations

import errno
import json
import os
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

import pytest

from simplicio_mapper.store import MemoryStore, MigrationCoordinator, MigrationEngine, doctor_store

OTHER_USER_PID = 4242
Kill = Callable[[int, int], None]


def _eperm(pid: int, sig: int) -> None:
    raise PermissionError(errno.EPERM, "Operation not permitted")


def _esrch(pid: int, sig: int) -> None:
    raise ProcessLookupError(errno.ESRCH, "No such process")


LIVENESS = pytest.mark.parametrize(
    ("kill", "alive"),
    [(_eperm, True), (_esrch, False)],
    ids=["eperm-owner-alive", "esrch-owner-gone"],
)


@LIVENESS
def test_migration_writer_lock_liveness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kill: Kill, alive: bool
) -> None:
    source = tmp_path / "legacy.sqlite"
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.commit()
    source.with_name(source.name + ".writer.lock").write_text(
        json.dumps({"pid": OTHER_USER_PID, "owner": "legacy-writer"}), encoding="utf-8"
    )
    monkeypatch.setattr(os, "kill", kill)
    report = MigrationCoordinator(tmp_path / "mapper.sqlite", {"legacy": source}).discover(dry_run=True)
    writers = report["sources"][0]["writers"]
    assert writers["active"] is alive
    assert writers["stale"] is (not alive)
    assert any(item["code"] == "WRITER_ACTIVE" for item in report["blockers"]) is alive


@LIVENESS
def test_registry_lock_liveness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kill: Kill, alive: bool
) -> None:
    engine = MigrationEngine(tmp_path / "catalog.sqlite")
    engine.lock_path.write_text(
        json.dumps({"owner": "other-user", "pid": OTHER_USER_PID}) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(os, "kill", kill)
    assert engine.status()["lock"]["stale"] is (not alive)


@LIVENESS
def test_health_store_lock_liveness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kill: Kill, alive: bool
) -> None:
    database = tmp_path / "store.sqlite"
    MemoryStore(database).initialize()
    for suffix in (".writer.lock", ".migration.lock"):
        database.with_name(database.name + suffix).write_text(
            json.dumps({"owner": "other-user", "pid": OTHER_USER_PID}), encoding="utf-8"
        )
    monkeypatch.setattr(os, "kill", kill)
    locks = doctor_store(database)["checks"]["locks"]
    for name in ("writer", "migration"):
        assert locks[name]["active"] is alive, name
        assert locks[name]["stale"] is (not alive), name
