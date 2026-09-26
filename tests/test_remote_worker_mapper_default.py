from __future__ import annotations

from argparse import Namespace

from simplicio_loop import remote_worker_cli


class _FakeMapperQueue:
    def __init__(self, database, *, auto_create):
        self.database = database
        self.auto_create = auto_create
        self.initialized = False

    def initialize(self):
        self.initialized = True
        return {"status": "ready"}


def _args(**overrides):
    values = {
        "repo": ".",
        "db": None,
        "http": None,
        "mapper_db": None,
        "mapper_init": False,
        "token": None,
    }
    values.update(overrides)
    return Namespace(**values)


def test_worker_defaults_to_repo_scoped_mapper_without_implicit_creation(monkeypatch, tmp_path):
    resolved = tmp_path / ".simplicio-loop" / "data" / "operations.sqlite"
    monkeypatch.setattr(remote_worker_cli, "_default_mapper_db", lambda repo: resolved)
    monkeypatch.setattr(remote_worker_cli, "MapperRemoteQueue", _FakeMapperQueue)

    queue = remote_worker_cli._build_queue(_args(repo=str(tmp_path)))

    assert queue.database == resolved
    assert queue.auto_create is False
    assert queue.initialized is False
    assert not resolved.exists()


def test_worker_explicit_mapper_init_is_the_only_default_creation_transition(monkeypatch, tmp_path):
    resolved = tmp_path / ".simplicio-loop" / "data" / "operations.sqlite"
    monkeypatch.setattr(remote_worker_cli, "_default_mapper_db", lambda repo: resolved)
    monkeypatch.setattr(remote_worker_cli, "MapperRemoteQueue", _FakeMapperQueue)

    queue = remote_worker_cli._build_queue(_args(repo=str(tmp_path), mapper_init=True))

    assert queue.initialized is True


def test_worker_accepts_explicit_legacy_db_for_compatibility(monkeypatch, tmp_path):
    class _FakeLegacyQueue:
        def __init__(self, path):
            self.path = path

    monkeypatch.setattr(remote_worker_cli, "SQLiteRemoteQueue", _FakeLegacyQueue)

    queue = remote_worker_cli._build_queue(_args(db=str(tmp_path / "legacy.sqlite3")))

    assert queue.path.endswith("legacy.sqlite3")
