from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import simplicio.effect_transaction as effect_transaction
import simplicio.write_set_lock as write_set_lock
from simplicio.effect_transaction import EffectTransaction, EffectTransactionError
from simplicio.plan_compiler import ChangeSet
from simplicio.prism_transaction import PrismTransaction
from simplicio.store_adapter import StoreAdapterError
from simplicio.write_set_lock import LockError
from tests.python.test_effect_transaction_364 import change_set
from tests.python.test_execution_contracts_363 import changeset_payload
from tests.python.test_issue_drain_bundle import _envelope


def test_effect_store_failures_remain_typed(tmp_path, monkeypatch) -> None:
    transaction = EffectTransaction(tmp_path)
    monkeypatch.setattr(transaction.store, "read", lambda _key: (_ for _ in ()).throw(StoreAdapterError("STORE_CORRUPT")))
    with pytest.raises(EffectTransactionError, match="RECOVERY_REQUIRED"):
        transaction.transitions("broken")

    monkeypatch.setattr(transaction.store, "write", lambda _key, _value: (_ for _ in ()).throw(StoreAdapterError("STORE_WRITE_FAILED")))
    with pytest.raises(EffectTransactionError, match="STORE_WRITE_FAILED"):
        transaction._write_record("broken", {})


def test_effect_lock_retry_and_non_retry_paths(tmp_path, monkeypatch) -> None:
    transaction = EffectTransaction(tmp_path)
    calls = []

    def acquire(_key, *, operation):
        calls.append(operation)
        if len(calls) == 1:
            raise StoreAdapterError("STORE_LOCKED")
        return "handle"

    monkeypatch.setattr(transaction.store, "acquire", acquire)
    monkeypatch.setattr(effect_transaction.time, "sleep", lambda _delay: None)
    assert transaction._locked("key") == "handle"
    assert len(calls) == 2

    monkeypatch.setattr(
        transaction.store,
        "acquire",
        lambda _key, *, operation: (_ for _ in ()).throw(StoreAdapterError("STORE_LOCKED")),
    )
    with pytest.raises(EffectTransactionError, match="RECOVERY_REQUIRED"):
        transaction._locked("key", retry=False)

    monkeypatch.setattr(
        transaction.store,
        "acquire",
        lambda _key, *, operation: (_ for _ in ()).throw(StoreAdapterError("STORE_CORRUPT")),
    )
    with pytest.raises(EffectTransactionError, match="RECOVERY_REQUIRED"):
        transaction._locked("key")


def test_effect_transition_requires_record_and_releases_lock(tmp_path, monkeypatch) -> None:
    transaction = EffectTransaction(tmp_path)
    released = []
    monkeypatch.setattr(transaction, "_locked", lambda _key: "handle")
    monkeypatch.setattr(transaction, "_read_record", lambda _key: None)
    monkeypatch.setattr(transaction.store, "release", released.append)
    with pytest.raises(EffectTransactionError, match="RECOVERY_REQUIRED"):
        transaction._transition("key", "CHECKPOINTED")
    assert released == ["handle"]


def test_effect_checkpoint_without_hash_fails_before_apply(tmp_path) -> None:
    transaction = EffectTransaction(tmp_path)
    applied = []
    with pytest.raises(EffectTransactionError, match="CHECKPOINT_UNVERIFIED"):
        transaction.execute(
            change_set("missing-checkpoint"),
            checkpoint=lambda _change: {},
            apply=lambda _change: applied.append(True),
            verify=lambda *_args: {"status": "passed"},
            rollback=lambda *_args: {"status": "restored"},
        )
    assert applied == []
    assert transaction.transitions("missing-checkpoint")[-1] == "FAILED_BEFORE_WRITE"


def test_write_set_input_guards(tmp_path) -> None:
    manager = write_set_lock.WriteSetLockManager(tmp_path)
    for values in (("", "lease", "fence"), ("owner", "", "fence"), ("owner", "lease", "")):
        with pytest.raises(write_set_lock.LockError, match="LEASE_REQUIRED"):
            manager.acquire(["a.txt"], owner=values[0], lease_id=values[1], fencing_token=values[2])
    with pytest.raises(write_set_lock.LockError, match="STALE_FENCE"):
        manager.acquire(["a.txt"], owner="owner", lease_id="lease", fencing_token="new", active_fence="old")
    with pytest.raises(write_set_lock.LockError, match="EMPTY_WRITE_SET"):
        manager.acquire([], owner="owner", lease_id="lease", fencing_token="fence")
    for path in ("", "/absolute", "../escape", "a/../b"):
        with pytest.raises(write_set_lock.LockError, match="UNSAFE_PATH"):
            manager.acquire([path], owner="owner", lease_id="lease", fencing_token="fence")
    manager.validate_fence("fence", expected="fence")
    with pytest.raises(write_set_lock.LockError, match="STALE_FENCE"):
        manager.validate_fence("old", expected="new")


def test_write_set_mapper_unavailable_and_status_helpers(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(write_set_lock, "_MAPPER_IMPORT_ERROR", ImportError("missing"))
    with pytest.raises(write_set_lock.LockError, match="MAPPER_STORE_UNAVAILABLE"):
        write_set_lock.WriteSetLockManager(tmp_path)
    assert write_set_lock.WriteSetLockManager._record_path({}) is None
    assert write_set_lock.WriteSetLockManager._record_path({"owner": {}}) is None
    assert write_set_lock.WriteSetLockManager._record_path({"owner": {"write_set_path": 3}}) is None
    assert write_set_lock.WriteSetLockManager._handle_from_status(Path("x.lock"), {}) is None
    assert write_set_lock.WriteSetLockManager._handle_from_status(Path("x.lock"), {"owner": {}}) is None
    assert write_set_lock.WriteSetLockManager._handle_from_status(
        Path("x.lock"), {"owner": {"owner_token": "token"}}
    ) is not None


def test_write_set_active_status_and_malformed_owner(tmp_path, monkeypatch) -> None:
    manager = write_set_lock.WriteSetLockManager(tmp_path)
    status = {
        "active": True,
        "owner": {
            "owner": "owner",
            "lease_id": "lease",
            "fencing_token": "fence",
            "owner_token": "token",
            "write_set_path": "a.txt",
        },
    }
    monkeypatch.setattr(write_set_lock, "inspect_lock_at", lambda *_args, **_kwargs: status)
    monkeypatch.setattr(write_set_lock, "release_lock_at", lambda _handle: None)
    receipt = manager.acquire(["a.txt"], owner="owner", lease_id="lease", fencing_token="fence")
    manager._lock_path("a.txt").write_text("", encoding="utf-8")
    assert receipt["status"] == "acquired"
    assert manager.held_paths() == ["a.txt"]
    assert manager.release(owner="owner", lease_id="lease")["status"] == "released"

    malformed = {"active": True, "owner": {"owner": "owner", "lease_id": "lease"}}
    monkeypatch.setattr(write_set_lock, "inspect_lock_at", lambda *_args, **_kwargs: malformed)
    with pytest.raises(write_set_lock.LockError, match="MAPPER_STORE_PERSISTENCE_FAILED"):
        manager.acquire(["a.txt"], owner="owner", lease_id="lease", fencing_token="fence")


def test_write_set_conflict_acquire_and_partial_cleanup(tmp_path, monkeypatch) -> None:
    manager = write_set_lock.WriteSetLockManager(tmp_path)
    monkeypatch.setattr(write_set_lock, "inspect_lock_at", lambda *_args, **_kwargs: {"active": False})
    monkeypatch.setattr(write_set_lock, "acquire_lock_at", lambda *_args, **_kwargs: None)
    with pytest.raises(write_set_lock.LockError, match="CONFLICT_BLOCKED"):
        manager.acquire(["a.txt"], owner="owner", lease_id="lease", fencing_token="fence")

    handles = []
    def acquire_then_fail(_path, *, operation, extra_fields):
        if not handles:
            handle = object()
            handles.append(handle)
            return handle
        raise OSError("disk")

    released = []
    monkeypatch.setattr(write_set_lock, "acquire_lock_at", acquire_then_fail)
    monkeypatch.setattr(write_set_lock, "release_lock_at", released.append)
    with pytest.raises(write_set_lock.LockError, match="MAPPER_STORE_PERSISTENCE_FAILED"):
        manager.acquire(["a.txt", "b.txt"], owner="owner", lease_id="lease", fencing_token="fence")
    assert released == handles


def test_write_set_release_and_held_paths_ignore_inactive_and_missing_path(tmp_path, monkeypatch) -> None:
    manager = write_set_lock.WriteSetLockManager(tmp_path)
    first = manager.lock_root / "first.lock"
    second = manager.lock_root / "second.lock"
    first.write_text("", encoding="utf-8")
    second.write_text("", encoding="utf-8")
    statuses = {
        str(first): {"active": True, "owner": {"owner": "owner", "lease_id": "lease", "owner_token": "t"}},
        str(second): {"active": False},
    }
    released = []
    monkeypatch.setattr(write_set_lock, "inspect_lock_at", lambda path, **_kwargs: statuses[path])
    monkeypatch.setattr(write_set_lock, "release_lock_at", released.append)
    assert manager.held_paths() == []
    assert manager.release(owner="owner", lease_id="lease")["status"] == "released"
    assert len(released) == 1


def test_write_set_conflict_is_single_writer_across_processes(tmp_path) -> None:
    gate = tmp_path / "start.flag"
    worker = tmp_path / "writer.py"
    worker.write_text(
        """
import json
import sys
import time
from pathlib import Path
from simplicio.write_set_lock import LockError, WriteSetLockManager

root = Path(sys.argv[1])
gate = Path(sys.argv[2])
index = sys.argv[3]
while not gate.exists():
    time.sleep(0.01)
manager = WriteSetLockManager(root)
try:
    manager.acquire(["shared.txt"], owner=f"owner-{index}", lease_id=f"lease-{index}", fencing_token=f"fence-{index}")
except LockError as error:
    print(json.dumps({"status": "rejected", "reason": error.reason_code}), flush=True)
    raise SystemExit(0)
print(json.dumps({"status": "acquired"}), flush=True)
time.sleep(1.0)
manager.release(owner=f"owner-{index}", lease_id=f"lease-{index}")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    repo_root = str(Path(__file__).resolve().parents[2])
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (repo_root, environment.get("PYTHONPATH", "")) if item
    )
    processes = [
        subprocess.Popen(
            [sys.executable, str(worker), str(tmp_path), str(gate), str(index)],
            cwd=repo_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(10)
    ]
    gate.write_text("go\n", encoding="utf-8")
    outputs = [process.communicate(timeout=30) for process in processes]
    results = [json.loads(stdout) for _process, (stdout, _stderr) in zip(processes, outputs, strict=True)]
    acquired = [result for result in results if result["status"] == "acquired"]
    rejected = [result for result in results if result["status"] == "rejected"]
    assert len(acquired) == 1
    assert len(rejected) == 9
    assert {result["reason"] for result in rejected} == {"CONFLICT_BLOCKED"}


def _prism_inputs() -> tuple[object, ChangeSet]:
    payload = changeset_payload()
    payload["change_set_id"] = "coverage-prism"
    payload["idempotency_key"] = "coverage-prism"
    change = ChangeSet.from_dict(payload)
    return _envelope(change_set_hash=change.canonical_hash()), change


def test_prism_envelope_and_terminal_guards(tmp_path, monkeypatch) -> None:
    envelope, change = _prism_inputs()
    transaction = PrismTransaction(tmp_path)
    with pytest.raises(EffectTransactionError, match="ENVELOPE_CHANGESET_MISMATCH"):
        transaction.execute(
            replace(envelope, change_set_hash="f" * 64),
            change,
            active_fence="fence-1",
            checkpoint=lambda _change: {"checkpoint_hash": "x"},
            apply=lambda _change: {"status": "applied"},
            verify=lambda *_args: {"status": "passed"},
            rollback=lambda *_args: {"status": "restored"},
        )
    with pytest.raises(EffectTransactionError, match="FENCE_LOST"):
        transaction.execute(
            envelope,
            change,
            active_fence="wrong-fence",
            checkpoint=lambda _change: {"checkpoint_hash": "x"},
            apply=lambda _change: {"status": "applied"},
            verify=lambda *_args: {"status": "passed"},
            rollback=lambda *_args: {"status": "restored"},
        )
    monkeypatch.setattr(transaction, "_read", lambda _key: {"state": "COMMITTED", "receipt": {"ok": True}})
    assert transaction.execute(
        envelope,
        change,
        active_fence="fence-1",
        checkpoint=lambda _change: {},
        apply=lambda _change: {},
        verify=lambda *_args: {},
        rollback=lambda *_args: {},
    ) == {"ok": True}
    monkeypatch.setattr(transaction, "_read", lambda _key: {"state": "ROLLED_BACK"})
    with pytest.raises(EffectTransactionError, match="TRANSACTION_TERMINAL"):
        transaction.execute(
            envelope,
            change,
            active_fence="fence-1",
            checkpoint=lambda _change: {},
            apply=lambda _change: {},
            verify=lambda *_args: {},
            rollback=lambda *_args: {},
        )


def test_prism_conflict_fence_and_store_failures(tmp_path, monkeypatch) -> None:
    envelope, change = _prism_inputs()
    transaction = PrismTransaction(tmp_path)
    monkeypatch.setattr(
        transaction.locks,
        "acquire",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(LockError("CONFLICT_BLOCKED")),
    )
    with pytest.raises(EffectTransactionError, match="CONFLICT_BLOCKED"):
        transaction.execute(
            envelope,
            change,
            active_fence="fence-1",
            checkpoint=lambda _change: {},
            apply=lambda _change: {},
            verify=lambda *_args: {},
            rollback=lambda *_args: {},
        )
    assert transaction._read(transaction._tx_key(envelope))["state"] == "CONFLICT_BLOCKED"

    monkeypatch.setattr(
        transaction.store,
        "acquire",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(StoreAdapterError("STORE_LOCKED")),
    )
    with pytest.raises(EffectTransactionError, match="RECOVERY_REQUIRED"):
        transaction._store(envelope, "GATED", None)

    monkeypatch.setattr(transaction.store, "read", lambda _key: (_ for _ in ()).throw(StoreAdapterError("bad")))
    with pytest.raises(EffectTransactionError, match="RECOVERY_REQUIRED"):
        transaction._read("key")
    monkeypatch.setattr(transaction.store, "write", lambda _key, _value: (_ for _ in ()).throw(StoreAdapterError("bad")))
    with pytest.raises(EffectTransactionError, match="STORE_WRITE_FAILED"):
        transaction._write("key", {})
