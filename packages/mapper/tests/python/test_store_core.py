"""Integration tests for the MapperStore/v1 connection foundation."""

from __future__ import annotations

import json
import multiprocessing
import sqlite3
import threading
from pathlib import Path

import pytest

from simplicio_mapper.store import (
    FenceValidator,
    FenceViolationError,
    StoreConnection,
    StoreError,
    StoreFileLock,
    StoreLocation,
    StoreLockError,
    StoreMissingError,
    StoreMode,
    StorePathError,
    StoreProfile,
    TransactionError,
    WriterIdentity,
    assert_within_root,
    inspect_store,
    is_busy_error,
    resolve_store_location,
    run_with_retry,
    transaction,
)


def _hold_lock_in_child(path: str, ready: object, release: object) -> None:
    with StoreFileLock(path, owner="child"):
        ready.set()
        release.wait(5)


def test_resolver_precedence_is_side_effect_free(tmp_path: Path) -> None:
    flag = tmp_path / "flag"
    configured = tmp_path / "configured"
    location = resolve_store_location(
        data_dir=flag,
        environ={"SIMPLICIO_DATA_DIR": str(configured)},
        home=tmp_path / "home",
    )

    assert location.root == flag
    assert location.source == "flag"
    assert not flag.exists()
    assert not configured.exists()


def test_resolver_supports_env_repo_scope_and_location_guards(tmp_path: Path) -> None:
    configured = tmp_path / "configured"
    assert resolve_store_location(environ={"SIMPLICIO_DATA_DIR": str(configured)}).source == "env"
    repo = tmp_path / "repo"
    repo.mkdir()
    repo_location = resolve_store_location(
        environ={"SIMPLICIO_STORE_SCOPE": "repo"}, repo_root=repo, home=tmp_path / "home"
    )
    assert repo_location.root == repo / ".simplicio-loop" / "data"
    assert repo_location.source == "repo"
    assert repo_location.database("semantic.sqlite").name == "semantic.sqlite"
    with pytest.raises(StorePathError):
        repo_location.database("../escape.sqlite")
    repo_location.ensure_root()
    assert repo_location.root.stat().st_mode & 0o777 == 0o700
    assert (
        assert_within_root(repo_location.root, repo_location.root / "semantic.sqlite")
        == repo_location.root / "semantic.sqlite"
    )
    with pytest.raises(StorePathError):
        assert_within_root(repo_location.root, tmp_path / "outside.sqlite")
    with pytest.raises(StorePathError):
        resolve_store_location(data_dir="/")
    link = repo_location.root / "linked.sqlite"
    link.symlink_to(tmp_path / "outside.sqlite")
    with pytest.raises(StorePathError):
        repo_location.database("linked.sqlite")
    with pytest.raises(StorePathError):
        assert_within_root(repo_location.root, link)


def test_resolver_rejects_empty_and_symlink_escape(tmp_path: Path) -> None:
    with pytest.raises(StorePathError):
        resolve_store_location(data_dir=" ")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(StorePathError):
        resolve_store_location(data_dir=link)
    temporary = resolve_store_location(environ={}, allow_temp=True, temp_dir=tmp_path / "temporary")
    assert temporary.source == "temp"
    assert not temporary.root.exists()
    root_link = tmp_path / "root-link"
    root_link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(StorePathError):
        StoreLocation(root_link, "test", True).ensure_root()


def test_profiles_validate_modes_and_limits() -> None:
    assert StoreProfile.read_only().mode == StoreMode.READ_ONLY
    assert StoreProfile.migration().transaction_mode == "EXCLUSIVE"
    assert StoreProfile.backup().query_only is True
    assert StoreProfile.read_write().with_mode(StoreMode.MIGRATION).mode == StoreMode.MIGRATION
    assert StoreProfile.read_write().with_mode(StoreMode.BACKUP, create=False).create is False
    assert StoreProfile(mode="read-only", create=True).mode == StoreMode.READ_ONLY  # type: ignore[arg-type]
    assert StoreProfile(mode=StoreMode.BACKUP).query_only is True
    assert StoreProfile(mode=StoreMode.MIGRATION).transaction_mode == "EXCLUSIVE"
    with pytest.raises(ValueError):
        StoreProfile(mode="not-a-mode")  # type: ignore[arg-type]
    for kwargs in (
        {"busy_timeout_ms": -1},
        {"timeout_seconds": 121},
        {"transaction_mode": "bad"},
        {"journal_mode": "bad"},
        {"synchronous": "bad"},
    ):
        with pytest.raises(ValueError):
            StoreProfile(**kwargs)


def test_read_only_status_on_missing_store_has_no_side_effect(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "semantic.sqlite"
    before = set(tmp_path.rglob("*"))

    status = inspect_store(path)

    assert status["status"] == "missing"
    assert status["reason_code"] == "STORE_MISSING"
    assert status["journal_mode"] is None
    assert status["schema_version"] is None
    assert set(tmp_path.rglob("*")) == before
    with pytest.raises(Exception):
        StoreConnection.open(path, StoreProfile.read_only())


def test_status_contract_shape_for_missing_and_ready(tmp_path: Path) -> None:
    from simplicio_mapper.contract import validate_instance

    schema = json.loads(
        (Path(__file__).parents[2] / "simplicio_mapper/contracts/mapper-store/v1/schemas/status.schema.json").read_text()
    )
    missing = inspect_store(tmp_path / "missing.sqlite")
    assert validate_instance(missing, schema) == []
    database = tmp_path / "ready.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY)")
    finally:
        connection.close()
    ready = inspect_store(database)
    assert validate_instance(ready, schema) == []
    assert ready["status"] == "ready"
    fixture = json.loads(
        (Path(__file__).parents[2] / "simplicio_mapper/contracts/mapper-store/v1/fixtures/status/ready.json").read_text()
    )
    assert validate_instance(fixture, schema) == []


def test_status_reports_corrupt_database(tmp_path: Path) -> None:
    database = tmp_path / "corrupt.sqlite"
    database.write_bytes(b"not sqlite")
    status = inspect_store(database)
    assert status["status"] == "corrupt"
    assert status["reason_code"] == "STORE_OPEN_FAILED"


def test_status_reports_unsafe_symlink(tmp_path: Path) -> None:
    target = tmp_path / "outside.sqlite"
    target.write_bytes(b"not sqlite")
    link = tmp_path / "linked.sqlite"
    link.symlink_to(target)
    status = inspect_store(link)
    assert status["status"] == "unsafe"
    assert status["reason_code"] == "STORE_UNSAFE_PATH"


def test_status_is_immutable_and_rejects_write_profiles(tmp_path: Path) -> None:
    database = tmp_path / "wal.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE vector_cache (id INTEGER PRIMARY KEY)")
        connection.execute("PRAGMA user_version=42")
        connection.commit()
        before = {item.name for item in tmp_path.iterdir()}
        status = inspect_store(database, path_source="env")
        with StoreConnection.open(database, StoreProfile.read_only(), immutable=False) as store:
            assert store.effective_settings()["journal_mode"] == "wal"
            assert store.execute("SELECT COUNT(*) FROM vector_cache").fetchone()[0] == 0
        after = {item.name for item in tmp_path.iterdir()}
    finally:
        connection.close()
    assert before == after
    assert status["status"] == "ready"
    assert status["path_source"] == "env"
    assert status["journal_mode"] == "wal"
    assert status["schema_version"] == 42
    assert status["capabilities"]["sqlite_vec"] is False

    with pytest.raises(ValueError):
        inspect_store(database, profile=StoreProfile.read_write())
    with pytest.raises(ValueError):
        inspect_store(database, path_source="bad")
    assert inspect_store("//server/share/store.sqlite")["reason_code"] == "STORE_UNSAFE_PATH"


def test_status_reports_directory_and_dangling_symlink_as_unsafe(tmp_path: Path) -> None:
    directory = tmp_path / "directory.sqlite"
    directory.mkdir()
    dangling = tmp_path / "dangling.sqlite"
    dangling.symlink_to(tmp_path / "does-not-exist.sqlite")
    assert inspect_store(directory)["status"] == "unsafe"
    assert inspect_store(dangling)["reason_code"] == "STORE_UNSAFE_PATH"


def test_status_detects_closed_wal_from_sqlite_header(tmp_path: Path) -> None:
    database = tmp_path / "closed-wal.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY)")
        connection.commit()
    finally:
        connection.close()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(database) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    status = inspect_store(database)
    assert status["status"] == "ready"
    assert status["journal_mode"] == "wal"
    before = {item.name for item in tmp_path.iterdir()}
    with StoreConnection.open(database, StoreProfile.read_only()):
        pass
    assert {item.name for item in tmp_path.iterdir()} == before


def test_status_rejects_empty_wal_sidecars(tmp_path: Path) -> None:
    database = tmp_path / "invalid-wal.sqlite"
    sqlite3.connect(database).close()
    Path(str(database) + "-wal").write_bytes(b"")
    Path(str(database) + "-shm").write_bytes(b"")
    status = inspect_store(database)
    assert status["status"] == "unsafe"
    assert status["reason_code"] == "STORE_WAL_INVALID"


def test_connection_applies_effective_pragmas_and_transactions_rollback(tmp_path: Path) -> None:
    database = tmp_path / "operations.sqlite"
    with StoreConnection.open(database, StoreProfile.read_write()) as store:
        settings = store.effective_settings()
        assert settings["journal_mode"] == "wal"
        assert settings["foreign_keys"] is True
        store.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, value TEXT)")
        with pytest.raises(RuntimeError):
            with transaction(store, "IMMEDIATE"):
                store.execute("INSERT INTO facts(value) VALUES (?)", ("rolled-back",))
                raise RuntimeError("abort")
        with transaction(store, "IMMEDIATE"):
            store.execute("INSERT INTO facts(value) VALUES (?)", ("committed",))
        assert store.execute("SELECT value FROM facts").fetchall() == [("committed",)]


def test_read_only_connection_cannot_write_and_status_reports_ready(tmp_path: Path) -> None:
    database = tmp_path / "semantic.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY)")
    finally:
        connection.close()
    before = database.stat().st_mtime_ns

    with StoreConnection.open(database, StoreProfile.read_only()) as store:
        assert store.effective_settings()["query_only"] is True
        assert store.effective_settings()["foreign_keys"] is True
        with pytest.raises(sqlite3.OperationalError):
            store.execute("INSERT INTO facts DEFAULT VALUES")
    status = inspect_store(database)
    assert status["status"] == "ready"
    assert status["journal_mode"] == "delete"
    assert database.stat().st_mtime_ns == before
    assert not Path(str(database) + "-wal").exists()
    assert not Path(str(database) + "-shm").exists()


def test_connection_identity_closed_state_and_missing_readonly(tmp_path: Path) -> None:
    database = tmp_path / "identity.sqlite"
    identity = WriterIdentity.create("test")
    store = StoreConnection.open(
        database, StoreProfile.read_write(), writer_identity=identity, correlation_id="corr"
    )
    assert store.writer_identity == identity
    assert store.correlation_id == "corr"
    store.close()
    with pytest.raises(StoreError):
        store.execute("SELECT 1")
    with pytest.raises(StoreMissingError):
        StoreConnection.open(tmp_path / "absent.sqlite", StoreProfile.backup())
    with pytest.raises(ValueError):
        WriterIdentity.create("")
    with pytest.raises(StorePathError):
        StoreConnection.open(Path("."))
    escaped = tmp_path / "escaped.sqlite"
    escaped.symlink_to(tmp_path / "outside.sqlite")
    with pytest.raises(StorePathError):
        StoreConnection.open(escaped)
    with pytest.raises(StorePathError):
        StoreConnection.open(tmp_path / "inside.sqlite", root=tmp_path / "authorized")
    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(StorePathError):
        StoreConnection.open(parent_link / "through-parent.sqlite")
    with pytest.raises(StoreMissingError):
        StoreConnection.open(tmp_path / "not-created.sqlite", StoreProfile.read_write(create=False))
    symlink_root = tmp_path / "root-link"
    symlink_root.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(StorePathError):
        StoreConnection.open(tmp_path / "through-link.sqlite", root=symlink_root)
    with pytest.raises(StorePathError):
        StoreConnection.open("//server/share/store.sqlite")


def test_public_dml_requires_transaction_and_controls_are_owned(tmp_path: Path) -> None:
    database = tmp_path / "guarded-dml.sqlite"
    with StoreConnection.open(database, StoreProfile.read_write()) as store:
        assert store.writer_identity is not None
        store.execute("CREATE TABLE facts (value TEXT)")
        with pytest.raises(StoreError):
            store.execute("BEGIN")
        with pytest.raises(StoreError):
            store.execute("SAVEPOINT external")
        with pytest.raises(StoreError):
            store.execute("PRAGMA journal_mode=DELETE")
        with pytest.raises(StoreError):
            store.execute("INSERT INTO facts VALUES ('outside')")
        with transaction(store):
            with pytest.raises(StoreError):
                store.execute("COMMIT")
            store.execute("INSERT INTO facts VALUES ('inside')")
        with pytest.raises(StoreError):
            store.execute("-- comment\nINSERT INTO facts VALUES ('comment')")
        with pytest.raises(StoreError):
            store.execute("WITH x(v) AS (SELECT 'cte') INSERT INTO facts SELECT v FROM x")
        assert store.execute("SELECT 'INSERT'").fetchone()[0] == "INSERT"
        assert store.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1


def test_resolver_rejects_network_paths(tmp_path: Path) -> None:
    with pytest.raises(StorePathError):
        resolve_store_location(data_dir="//server/share")
    with pytest.raises(StorePathError):
        resolve_store_location(data_dir=r"\\server\share")
    assert resolve_store_location(data_dir="/tmp/mapper-store-test").source == "flag"


def test_fence_is_checked_before_dml(tmp_path: Path) -> None:
    database = tmp_path / "fenced.sqlite"
    with StoreConnection.open(database, StoreProfile.read_write()) as store:
        store.execute("CREATE TABLE facts (value TEXT)")
        with pytest.raises(FenceViolationError):
            with transaction(store, fence=FenceValidator(lambda: False, "fence-1")):
                store.execute("INSERT INTO facts VALUES ('never')")
        assert store.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0
    with StoreConnection.open(database, StoreProfile.read_only()) as store:
        with pytest.raises(Exception):
            with transaction(store):
                pass
    with StoreConnection.open(database, StoreProfile.read_write()) as store:
        with pytest.raises(Exception):
            with transaction(store, "invalid"):
                pass


def test_fence_is_rechecked_before_each_dml(tmp_path: Path) -> None:
    database = tmp_path / "fenced-again.sqlite"
    checks = iter((True, False))
    with StoreConnection.open(database, StoreProfile.read_write()) as store:
        store.execute("CREATE TABLE facts (value TEXT)")
        with pytest.raises(FenceViolationError):
            with transaction(store, fence=FenceValidator(lambda: next(checks), "fence-2")):
                store.execute("INSERT INTO facts VALUES ('never')")
        assert store.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0


def test_nested_transaction_is_rejected_without_closing_outer(tmp_path: Path) -> None:
    database = tmp_path / "nested.sqlite"
    with StoreConnection.open(database, StoreProfile.read_write()) as store:
        store.execute("CREATE TABLE facts (value TEXT)")
        with transaction(store, fence=FenceValidator(lambda: True, "outer")):
            with pytest.raises(TransactionError):
                with transaction(store):
                    pass
            store.execute("INSERT INTO facts VALUES ('outer')")
        assert store.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1


def test_transaction_connection_facade_rechecks_bulk_sql(tmp_path: Path) -> None:
    database = tmp_path / "bulk.sqlite"
    with StoreConnection.open(database, StoreProfile.read_write()) as store:
        store.execute("CREATE TABLE facts (value TEXT)")
        with transaction(store) as connection:
            connection.executemany("INSERT INTO facts VALUES (?)", [("one",), ("two",)])
        with pytest.raises(TransactionError):
            with transaction(store) as connection:
                connection.execute("INSERT INTO facts VALUES ('three')")
                connection.executescript("INSERT INTO facts VALUES ('four');")
        assert store.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 2


def test_transaction_rolls_back_base_exception_and_cte_identifiers_are_safe(tmp_path: Path) -> None:
    database = tmp_path / "base-exception.sqlite"
    with StoreConnection.open(database, StoreProfile.read_write()) as store:
        store.execute("CREATE TABLE facts (value TEXT)")
        with pytest.raises(KeyboardInterrupt):
            with transaction(store):
                store.execute("INSERT INTO facts VALUES ('interrupt')")
                raise KeyboardInterrupt
        assert store.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0
        assert store.execute("WITH c([replace]) AS (SELECT 'safe') SELECT * FROM c").fetchone() == ("safe",)


def test_transaction_cursor_preserves_fence_guard(tmp_path: Path) -> None:
    database = tmp_path / "cursor-fenced.sqlite"
    checks = iter((True, True, False))
    with StoreConnection.open(database, StoreProfile.read_write()) as store:
        store.execute("CREATE TABLE facts (value TEXT)")
        with pytest.raises(FenceViolationError):
            with transaction(store, fence=FenceValidator(lambda: next(checks), "cursor-fence")) as connection:
                connection.cursor().execute("INSERT INTO facts VALUES ('never')")
        assert store.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0


def test_public_store_cursor_keeps_fence_guard(tmp_path: Path) -> None:
    database = tmp_path / "public-cursor.sqlite"
    checks = iter((True, True, True, False))
    with StoreConnection.open(database, StoreProfile.read_write()) as store:
        store.execute("CREATE TABLE facts (value TEXT)")
        with pytest.raises(FenceViolationError):
            with transaction(store, fence=FenceValidator(lambda: next(checks), "public-cursor")):
                cursor = store.execute("INSERT INTO facts VALUES ('one')")
                cursor.execute("INSERT INTO facts VALUES ('two')")
                cursor.executemany("INSERT INTO facts VALUES (?)", [("three",)])
                cursor.execute("INSERT INTO facts VALUES ('four')")
        assert store.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0
        with transaction(store) as connection:
            with pytest.raises(TransactionError):
                _ = connection.connection
            with pytest.raises(TransactionError):
                _ = connection.cursor().connection
            with pytest.raises(StoreError):
                store.connection.commit()
            with pytest.raises(StoreError):
                store.connection.executescript("SELECT 1")
            with pytest.raises(StoreError):
                store.connection.iterdump()
            with pytest.raises(StoreError):
                connection.execute("SELECT 1").execute("COMMIT")
        with transaction(store, fence=FenceValidator(lambda: True, "view-fence")):
            assert store.connection.in_transaction is True
            public_cursor = store.connection.cursor()
            public_cursor.execute("SELECT 1").fetchone()
            store.connection.executemany("INSERT INTO facts VALUES (?)", [("view",)])
            with pytest.raises(StoreError):
                _ = public_cursor.connection
            guarded = store.execute("SELECT 1")
            with pytest.raises(StoreError):
                _ = guarded.connection


def test_retry_is_bounded_and_only_retries_busy_errors() -> None:
    now = [0.0]
    attempts = [0]
    sleeps: list[float] = []

    def operation() -> str:
        attempts[0] += 1
        if attempts[0] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    result = run_with_retry(
        operation,
        deadline_seconds=1,
        max_attempts=4,
        base_delay_seconds=0.1,
        jitter_seconds=0,
        clock=lambda: now[0],
        sleeper=lambda delay: (sleeps.append(delay), now.__setitem__(0, now[0] + delay)),
    )
    assert result == "ok"
    assert attempts[0] == 3
    assert sleeps == [0.1, 0.2]


def test_retry_rethrows_nonbusy_and_stops_at_deadline() -> None:
    with pytest.raises(ValueError):
        run_with_retry(lambda: None, deadline_seconds=-1)
    with pytest.raises(ValueError):
        run_with_retry(lambda: None, max_attempts=0)
    with pytest.raises(RuntimeError):
        run_with_retry(lambda: (_ for _ in ()).throw(RuntimeError("no retry")))
    assert not is_busy_error(sqlite3.OperationalError("no such table: locked"))
    busy = sqlite3.OperationalError("synthetic busy")
    busy.sqlite_errorcode = getattr(sqlite3, "SQLITE_BUSY", 5)
    assert is_busy_error(busy)
    snapshot = sqlite3.OperationalError("synthetic snapshot busy")
    snapshot.sqlite_errorcode = 517
    assert is_busy_error(snapshot)
    now = [0.0]

    def locked() -> None:
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError):
        run_with_retry(
            locked,
            deadline_seconds=0.05,
            max_attempts=10,
            base_delay_seconds=0.1,
            jitter_seconds=0,
            clock=lambda: now[0],
            sleeper=lambda delay: now.__setitem__(0, now[0] + delay),
        )
    assert now[0] == 0.05


def test_file_lock_reports_contention_and_releases(tmp_path: Path) -> None:
    path = tmp_path / "catalog.lock"
    first = StoreFileLock(path, owner="first").acquire()
    try:
        with pytest.raises(StoreLockError):
            StoreFileLock(path, owner="second").acquire()
    finally:
        first.release()
    with StoreFileLock(path, owner="second"):
        pass
    assert path.read_text(encoding="utf-8").find('"owner": "second"') >= 0
    with pytest.raises(ValueError):
        StoreFileLock(path, owner="")
    target = tmp_path / "lock-target.txt"
    target.write_text("preserve", encoding="utf-8")
    symlink = tmp_path / "lock-link"
    try:
        symlink.symlink_to(target)
    except OSError as error:
        if getattr(error, "winerror", None) != 1314:
            raise
        pytest.skip("symlink tests require the Windows SeCreateSymbolicLink privilege")
    with pytest.raises(StoreLockError):
        StoreFileLock(symlink, owner="unsafe").acquire()
    assert target.read_text(encoding="utf-8") == "preserve"
    lock_parent = tmp_path / "lock-parent"
    lock_parent.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(StoreLockError):
        StoreFileLock(lock_parent / "through-parent.lock", owner="unsafe").acquire()
    parent_file = tmp_path / "parent-file"
    parent_file.write_text("not a directory", encoding="utf-8")
    with pytest.raises(StoreLockError):
        StoreFileLock(parent_file / "child.lock", owner="unsafe").acquire()


def test_blocking_file_lock_waits_for_sibling_thread(tmp_path: Path) -> None:
    path = tmp_path / "thread.lock"
    held = threading.Event()
    release = threading.Event()
    acquired = threading.Event()
    errors: list[BaseException] = []

    def holder() -> None:
        try:
            with StoreFileLock(path, owner="holder", blocking=True):
                held.set()
                release.wait(5)
        except BaseException as error:  # pragma: no cover - failure evidence
            errors.append(error)

    def waiter() -> None:
        try:
            with StoreFileLock(path, owner="waiter", blocking=True):
                acquired.set()
        except BaseException as error:  # pragma: no cover - failure evidence
            errors.append(error)

    holding_thread = threading.Thread(target=holder, daemon=True)
    waiting_thread = threading.Thread(target=waiter, daemon=True)
    holding_thread.start()
    assert held.wait(5)
    waiting_thread.start()
    assert not acquired.wait(0.1)
    release.set()
    assert acquired.wait(5), errors
    holding_thread.join(5)
    waiting_thread.join(5)
    assert not holding_thread.is_alive()
    assert not waiting_thread.is_alive()
    assert errors == []


@pytest.mark.skipif("fork" not in multiprocessing.get_all_start_methods(), reason="requires POSIX fork")
def test_file_lock_is_process_safe(tmp_path: Path) -> None:
    context = multiprocessing.get_context("fork")
    path = tmp_path / "process.lock"
    ready = context.Event()
    release = context.Event()
    child = context.Process(target=_hold_lock_in_child, args=(str(path), ready, release))
    child.start()
    try:
        assert ready.wait(5)
        with pytest.raises(StoreLockError):
            StoreFileLock(path, owner="parent").acquire()
    finally:
        release.set()
        child.join(5)
    assert child.exitcode == 0
    idle = StoreFileLock(path, owner="idle")
    idle.release()
    with pytest.raises(StoreLockError):
        idle.acquire()
        idle.acquire()
    idle.release()
