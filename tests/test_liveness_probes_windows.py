"""Every liveness probe asks the shared, Windows-safe probe and never calls ``os.kill(pid, 0)``.

On Windows ``os.kill`` with any signal other than the console events calls TerminateProcess, so ``os.kill(pid, 0)``
kills the process it was meant to check. Each site below runs with ``os.name`` patched to ``nt``: it must route the
question through ``simplicio_mapper.mapper.process_liveness.process_exists`` and must never send signal 0 itself.

The modules are imported up front: under the patched ``os.name`` a first import would run Windows-only module code
(``ctypes``) and ``pathlib`` would refuse to build a path.
"""
from __future__ import annotations

import ctypes  # noqa: F401 - loaded before os.name is faked
import json
import os
import time
from types import SimpleNamespace

import pytest

from simplicio.changeset_transaction import _lock_owned_by_live_process
from simplicio.plan_compiler.mapper_context import ContextBindingCache
from simplicio_loop import author_isolation, cli_impl, process_enforcement, quality_process  # noqa: F401 (cli_impl)
from simplicio_loop.cli_commands import orient_mapper
from simplicio_mapper.mapper import process_liveness  # the shared probe; no site may bypass it
from simplicio_mapper.store import health, migration
from simplicio_mapper.store.registry import MigrationEngine

PID = 4242


@pytest.fixture
def windows(monkeypatch):
    """Pretend to be Windows; record every kill, and answer the shared probe ``alive`` for PID."""
    kills: list = []
    probed: list = []

    def fake_probe(pid):
        probed.append(pid)
        return True

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(os, "kill", lambda pid, sig: kills.append((pid, sig)))
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: kills.append((pgid, sig)), raising=False)
    monkeypatch.setattr(process_liveness, "process_exists", fake_probe, raising=False)
    return SimpleNamespace(kills=kills, probed=probed)


def _assert_asked_the_shared_probe_and_never_signalled(windows) -> None:
    assert windows.probed and set(windows.probed) == {PID}
    assert [call for call in windows.kills if call[1] == 0] == []


def test_loop_pid_alive_asks_the_shared_probe(windows):
    assert process_enforcement._pid_alive(PID) is True
    _assert_asked_the_shared_probe_and_never_signalled(windows)


def test_loop_author_owner_alive_asks_the_shared_probe(tmp_path, windows):
    (tmp_path / author_isolation.OWNER).write_text(str(PID), encoding="utf-8")
    assert author_isolation._owner_alive(tmp_path) is True
    _assert_asked_the_shared_probe_and_never_signalled(windows)


def test_loop_quality_pid_is_running_asks_the_shared_probe(windows):
    quality_process._pid_is_running(PID)
    _assert_asked_the_shared_probe_and_never_signalled(windows)


def test_loop_mapper_index_running_info_asks_the_shared_probe(tmp_path, windows):
    lock = tmp_path / "index.lock"
    lock.write_text(json.dumps({"pid": PID, "started_at": time.time()}), encoding="utf-8")
    assert orient_mapper._mapper_index_running_info(lock) is not None
    _assert_asked_the_shared_probe_and_never_signalled(windows)


def test_store_health_lock_info_asks_the_shared_probe(tmp_path, windows):
    lock = tmp_path / "store.lock"
    lock.write_text(json.dumps({"pid": PID}), encoding="utf-8")
    assert health._lock_info(lock)["active"] is True
    _assert_asked_the_shared_probe_and_never_signalled(windows)


def test_store_migration_writer_status_asks_the_shared_probe(tmp_path, windows):
    (tmp_path / "store.sqlite.writer.lock").write_text(json.dumps({"pid": PID}), encoding="utf-8")
    assert migration._writer_status(tmp_path / "store.sqlite")["active"] is True
    _assert_asked_the_shared_probe_and_never_signalled(windows)


def test_store_registry_lock_snapshot_asks_the_shared_probe(tmp_path, windows):
    lock = tmp_path / "migration.lock"
    lock.write_text(json.dumps({"pid": PID}), encoding="utf-8")
    snapshot = MigrationEngine._lock_snapshot(SimpleNamespace(lock_path=lock))
    assert snapshot["stale"] is False
    _assert_asked_the_shared_probe_and_never_signalled(windows)


def test_dev_cli_changeset_lock_owner_asks_the_shared_probe(tmp_path, windows):
    lock = tmp_path / "changeset.lock"
    lock.write_text(f"pid={PID}\n", encoding="utf-8")
    assert _lock_owned_by_live_process(lock) is True
    _assert_asked_the_shared_probe_and_never_signalled(windows)


def test_dev_cli_mapper_context_stale_writer_lock_asks_the_shared_probe(tmp_path, windows):
    lock = tmp_path / "writer.lock"
    lock.write_text(str(PID), encoding="ascii")
    assert ContextBindingCache._remove_stale_writer_lock(SimpleNamespace(lock_path=lock)) is False
    assert lock.exists(), "a live writer's lock must be kept"
    _assert_asked_the_shared_probe_and_never_signalled(windows)
