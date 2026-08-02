from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from simplicio.changeset_transaction import (
    ChangesetTransactionError,
    _acquire_recovery_lock,
    _hash,
    _lock_owned_by_live_process,
    _mode,
    _paths,
    _pause_for_fault_injection,
    _rollback_after_commit_failure,
    _safe_path,
    _state_path,
    execute_changeset_transaction,
    existing_transaction_result,
    recover_changeset_transaction,
)
from simplicio.changeset_v2 import adapt_changeset, execute_changeset


def _changeset(*, content: str = "new\n") -> dict:
    return {
        "schema": "simplicio.fast.changeset/v2",
        "changeset_id": "cs-416",
        "correlation_id": "idem-416",
        "generation": "gen-416",
        "allowlist": ["a.txt", "b.txt"],
        "operations": [
            {"kind": "replace_range", "path": "a.txt", "start_line": 1, "end_line": 1, "text": content},
            {"kind": "create", "path": "b.txt", "content": "created\n"},
        ],
    }


def test_multifile_changeset_stages_once_and_replays_without_rewrite(tmp_path):
    (tmp_path / "a.txt").write_text("old\n", encoding="utf-8")

    first = execute_changeset(_changeset(), root=tmp_path, apply=True)
    first_mtime = (tmp_path / "a.txt").stat().st_mtime_ns
    replay = execute_changeset(_changeset(), root=tmp_path, apply=True)

    assert first["status"] == "ok"
    assert first["applied"] is True
    assert len(first["effects"]) == 2
    assert first["transaction"]["state"] == "COMMITTED"
    assert set(first["transaction"]["timings_ms"]) == {"stage", "commit", "total"}
    assert all(value >= 0 for value in first["transaction"]["timings_ms"].values())
    assert replay["status"] == "ok"
    assert replay["replayed"] is True
    assert (tmp_path / "a.txt").stat().st_mtime_ns == first_mtime
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "created\n"


def test_transaction_receipt_contains_operation_hash_validation_timing_and_causal_metadata(tmp_path):
    (tmp_path / "a.txt").write_text("old\n", encoding="utf-8")
    before_a = _hash(tmp_path / "a.txt")

    result = execute_changeset(_changeset(), root=tmp_path, apply=True)

    transaction = result["transaction"]
    assert transaction["operation"] == {
        "count": 2,
        "kinds": ["replace_range", "create_file"],
        "paths": ["a.txt", "b.txt"],
    }
    assert transaction["before_sha256"]["a.txt"] == before_a
    assert transaction["before_sha256"]["b.txt"] is None
    assert transaction["after_sha256"]["a.txt"] == result["effects"][0]["after_sha256"]
    assert transaction["after_sha256"]["b.txt"] == result["effects"][1]["after_sha256"]
    assert transaction["restored_sha256"] is None
    assert transaction["validation"] == []
    assert set(transaction["timings_ms"]) == {"stage", "commit", "total"}
    assert transaction["causal_ids"] == {
        "changeset_id": "cs-416",
        "correlation_id": "idem-416",
        "generation": "gen-416",
    }


def test_existing_file_mode_is_preserved_and_recorded_in_receipt(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    original_mode = stat.S_IMODE(target.stat().st_mode)
    target.chmod(original_mode | stat.S_IXUSR)
    expected_mode = stat.S_IMODE(target.stat().st_mode)

    result = execute_changeset(_changeset(), root=tmp_path, apply=True)

    assert result["status"] == "ok"
    changed = {row["path"]: row for row in result["transaction"]["files"]}
    assert changed["a.txt"]["before_mode"] == expected_mode
    assert changed["a.txt"]["after_mode"] == expected_mode
    assert stat.S_IMODE(target.stat().st_mode) == expected_mode


def test_same_idempotency_key_with_different_digest_is_rejected(tmp_path):
    (tmp_path / "a.txt").write_text("old\n", encoding="utf-8")

    assert execute_changeset(_changeset(), root=tmp_path, apply=True)["status"] == "ok"
    conflict = execute_changeset(_changeset(content="other\n"), root=tmp_path, apply=True)

    assert conflict["status"] == "refused"
    assert conflict["errors"][0]["code"] == "REPLAY_CONFLICT"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "new\n"


def test_staging_does_not_touch_final_files(tmp_path, monkeypatch):
    from simplicio import changeset_transaction

    (tmp_path / "a.txt").write_text("old\n", encoding="utf-8")
    original = changeset_transaction.execute_plan

    def observe(plan, *, root, apply, allow_native):
        assert root != tmp_path
        assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "old\n"
        return original(plan, root=root, apply=apply, allow_native=allow_native)

    monkeypatch.setattr(changeset_transaction, "execute_plan", observe)
    result = execute_changeset(_changeset(), root=tmp_path, apply=True)

    assert result["status"] == "ok"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "new\n"


def test_same_idempotency_key_is_serialized(tmp_path):
    state_path = _state_path(tmp_path, "busy-416")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_path.with_suffix(".lock")
    lock_path.write_text("pid=1\n", encoding="utf-8")

    with pytest.raises(ChangesetTransactionError, match="another process"):
        execute_changeset_transaction(
            {"operations": []},
            root=tmp_path,
            idempotency_key="busy-416",
            changeset_digest_value="digest-416",
        )


def test_recover_committing_journal_restores_before_hashes(tmp_path):
    original = b"old\n"
    target = tmp_path / "a.txt"
    target.write_bytes(b"partial\n")
    backup = tmp_path / ".simplicio-tx-crash.backup"
    backup.mkdir()
    (backup / "a.txt").write_bytes(original)
    state_path = _state_path(tmp_path, "recover-416")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "schema": "simplicio.fast.changeset-transaction/v1",
                "idempotency_key": "recover-416",
                "changeset_digest": "digest-416",
                "state": "COMMITTING",
                "receipt_path": str(state_path),
                "backup": str(backup),
                "before": {"a.txt": hashlib.sha256(original).hexdigest()},
            }
        ),
        encoding="utf-8",
    )
    recovered = recover_changeset_transaction(
        tmp_path,
        idempotency_key="recover-416",
        changeset_digest_value="digest-416",
    )

    assert recovered["status"] == "recovered"
    assert target.read_bytes() == original
    assert json.loads(state_path.read_text(encoding="utf-8"))["state"] == "ROLLED_BACK"


def test_real_child_crash_after_backup_is_recovered(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    key = "child-crash-416"
    digest = "child-crash-digest"
    plan = adapt_changeset(_changeset(content="crashed\n"))
    worker = (
        "import json, sys; "
        "from simplicio.changeset_transaction import execute_changeset_transaction; "
        "execute_changeset_transaction(json.loads(sys.argv[2]), root=sys.argv[1], "
        "idempotency_key=sys.argv[3], changeset_digest_value=sys.argv[4])"
    )
    env = os.environ.copy()
    repo_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = os.pathsep.join(item for item in (repo_root, env.get("PYTHONPATH", "")) if item)
    env["SIMPLICIO_TRANSACTION_PAUSE_AT"] = "after_backup"
    env["SIMPLICIO_TRANSACTION_PAUSE_SECONDS"] = "30"
    process = subprocess.Popen(
        [sys.executable, "-c", worker, str(tmp_path), json.dumps(plan), key, digest],
        cwd=repo_root,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    state_path = _state_path(tmp_path, key)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if state_path.is_file():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            backup = Path(str(state.get("backup", "")))
            if state.get("state") == "COMMITTING" and (backup / "a.txt").is_file():
                break
        time.sleep(0.05)
    else:
        process.kill()
        process.communicate(timeout=5)
        pytest.fail("child did not reach the post-backup crash window")
    process.kill()
    process.communicate(timeout=5)

    recovered = recover_changeset_transaction(tmp_path, idempotency_key=key, changeset_digest_value=digest)

    assert recovered["status"] == "recovered"
    assert target.read_text(encoding="utf-8") == "old\n"
    assert json.loads(state_path.read_text(encoding="utf-8"))["state"] == "ROLLED_BACK"
    restored = recovered["transaction"]["restored_sha256"]
    assert restored["a.txt"] == _hash(target)


def test_concurrent_change_is_journaled_as_precommit_refusal_and_replayable(tmp_path, monkeypatch):
    from simplicio import changeset_transaction

    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    original = changeset_transaction.execute_plan

    def mutate_source_then_stage(plan, *, root, apply, allow_native):
        target.write_text("external\n", encoding="utf-8")
        return original(plan, root=root, apply=apply, allow_native=allow_native)

    monkeypatch.setattr(changeset_transaction, "execute_plan", mutate_source_then_stage)
    result = execute_changeset_transaction(
        {
            "schema": "simplicio.mechanical-edit/v1",
            "touched_files": ["a.txt"],
            "operations": [],
        },
        root=tmp_path,
        idempotency_key="concurrent-refusal",
        changeset_digest_value="digest",
    )

    assert result["status"] == "refused"
    assert result["errors"][0]["code"] == "CONCURRENT_MODIFICATION"
    assert result["transaction"]["state"] == "FAILED_BEFORE_COMMIT"
    replay = existing_transaction_result(
        tmp_path,
        idempotency_key="concurrent-refusal",
        changeset_digest_value="digest",
    )
    assert replay["status"] == "refused"
    assert replay["replayed"] is True
    assert target.read_text(encoding="utf-8") == "external\n"


def test_typed_commit_filesystem_failure_enters_rollback_path(tmp_path, monkeypatch):
    from simplicio import changeset_transaction

    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    real_replace = changeset_transaction.os.replace

    def fail_replace(source, destination):
        if Path(source).name.startswith(".a.txt.") and Path(destination).name == "a.txt":
            raise changeset_transaction.ChangesetTransactionError(
                "WINDOWS_SHARING_VIOLATION", "target is locked"
            )
        return real_replace(source, destination)

    monkeypatch.setattr(changeset_transaction.os, "replace", fail_replace)
    with pytest.raises(ChangesetTransactionError, match="rolled back"):
        execute_changeset_transaction(
            adapt_changeset(_changeset()),
            root=tmp_path,
            idempotency_key="locked-target",
            changeset_digest_value="digest-locked",
        )
    assert target.read_text(encoding="utf-8") == "old\n"


@pytest.mark.parametrize("workers", [2, 10, 50])
def test_process_concurrency_serializes_one_idempotency_key(tmp_path, workers):
    """Real child processes must serialize the same transaction key."""
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    worker = tmp_path / "worker.py"
    worker.write_text(
        """
from __future__ import annotations
import json
import sys
import time
from pathlib import Path
from simplicio.changeset_transaction import ChangesetTransactionError, execute_changeset_transaction

root = Path(sys.argv[1])
key = sys.argv[2]
plan = json.loads(sys.argv[3])
gate = Path(sys.argv[4])
while not gate.exists():
    time.sleep(0.01)
try:
    result = execute_changeset_transaction(
        plan, root=root, idempotency_key=key, changeset_digest_value="digest-concurrent"
    )
except ChangesetTransactionError as exc:
    print(json.dumps({"error": exc.code}), flush=True)
    raise SystemExit(2)
print(json.dumps(result), flush=True)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    plan = {
        "schema": "simplicio.mechanical-edit/v1",
        "touched_files": ["a.txt"],
        "operations": [
            {"op": "replace_range", "path": "a.txt", "start_line": 1, "end_line": 1, "text": "new\n"}
        ],
        "validation": [{"cmd": [sys.executable, "-c", "import time; time.sleep(0.5)"]}],
    }
    env = os.environ.copy()
    repo_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
    encoded_plan = json.dumps(plan, separators=(",", ":"))
    gate = tmp_path / "start.flag"
    log_handles = []
    processes = []
    for index in range(workers):
        log_handle = (tmp_path / f"worker-{index}.log").open("w", encoding="utf-8")
        log_handles.append(log_handle)
        processes.append(
            subprocess.Popen(
                [sys.executable, str(worker), str(tmp_path), "process-concurrent", encoded_plan, str(gate)],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=log_handle,
            )
        )
    gate.write_text("go\n", encoding="utf-8")
    for process in processes:
        process.wait(timeout=30)
    for log_handle in log_handles:
        log_handle.close()

    assert sum(process.returncode == 0 for process in processes) == 1
    assert sum(process.returncode == 2 for process in processes) == workers - 1
    assert target.read_text(encoding="utf-8") == "new\n"


def test_transaction_path_and_hash_guards_fail_closed(tmp_path):
    missing = tmp_path / "missing.txt"
    assert _hash(missing) is None
    with pytest.raises(ChangesetTransactionError, match="unsafe"):
        _safe_path(tmp_path, "../escape.txt")
    with pytest.raises(ChangesetTransactionError, match="unsafe"):
        _safe_path(tmp_path, "")
    with pytest.raises(ChangesetTransactionError, match="unsafe"):
        _safe_path(tmp_path, str((tmp_path / "absolute.txt").resolve()))
    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    assert _hash(file_path)
    with pytest.raises(ChangesetTransactionError, match="regular file"):
        _hash(tmp_path)


def test_transaction_paths_ignore_malformed_operations_and_deduplicate():
    assert _paths(
        {
            "touched_files": ["b.txt", 3, "a.txt"],
            "operations": [None, {"path": "c.txt", "dest": "d.txt"}, {"path": 4}],
        }
    ) == ["a.txt", "b.txt", "c.txt", "d.txt"]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("{broken", "unreadable"),
        (json.dumps({"changeset_digest": "other"}), "another changeset"),
        (json.dumps({"changeset_digest": "digest", "state": "STAGED"}), "requires recovery"),
    ],
)
def test_existing_transaction_result_requires_recovery_or_rejects_conflict(tmp_path, payload, message):
    state_path = _state_path(tmp_path, "existing")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(payload, encoding="utf-8")
    with pytest.raises(ChangesetTransactionError, match=message):
        existing_transaction_result(
            tmp_path,
            idempotency_key="existing",
            changeset_digest_value="digest",
        )


def test_existing_transaction_result_returns_committed_replay(tmp_path):
    state_path = _state_path(tmp_path, "existing-ok")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"changeset_digest": "digest", "state": "COMMITTED", "result": {"status": "ok"}}),
        encoding="utf-8",
    )
    result = existing_transaction_result(
        tmp_path,
        idempotency_key="existing-ok",
        changeset_digest_value="digest",
    )
    assert result == {"status": "ok", "replayed": True}


def test_transaction_records_failed_before_commit_without_mutating_root(tmp_path, monkeypatch):
    from simplicio import changeset_transaction

    (tmp_path / "a.txt").write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(
        changeset_transaction,
        "execute_plan",
        lambda *args, **kwargs: {"status": "refused", "applied": False, "errors": [{"code": "bad"}]},
    )
    result = execute_changeset_transaction(
        {"operations": [{"path": "a.txt"}]},
        root=tmp_path,
        idempotency_key="failed-before-commit",
        changeset_digest_value="digest",
    )
    assert result["status"] == "refused"
    assert result["transaction"]["state"] == "FAILED_BEFORE_COMMIT"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "old\n"


def _write_journal(tmp_path, key, payload):
    path = _state_path(tmp_path, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_recovery_rejects_busy_malformed_conflict_and_nonrecoverable_journals(tmp_path):
    key = "recovery-errors"
    path = _state_path(tmp_path, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".lock").write_text("busy", encoding="utf-8")
    with pytest.raises(ChangesetTransactionError, match="another process"):
        recover_changeset_transaction(tmp_path, idempotency_key=key, changeset_digest_value="digest")
    path.with_suffix(".lock").unlink()
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ChangesetTransactionError, match="unreadable"):
        recover_changeset_transaction(tmp_path, idempotency_key=key, changeset_digest_value="digest")
    path.write_text(json.dumps({"changeset_digest": "other"}), encoding="utf-8")
    with pytest.raises(ChangesetTransactionError, match="another changeset"):
        recover_changeset_transaction(tmp_path, idempotency_key=key, changeset_digest_value="digest")
    path.write_text(json.dumps({"changeset_digest": "digest", "state": "INTENT"}), encoding="utf-8")
    with pytest.raises(ChangesetTransactionError, match="no recoverable"):
        recover_changeset_transaction(tmp_path, idempotency_key=key, changeset_digest_value="digest")


def test_recovery_rejects_invalid_before_backup_and_missing_saved_file(tmp_path):
    key = "recovery-shape"
    path = _write_journal(tmp_path, key, {"changeset_digest": "digest", "state": "STAGED"})
    with pytest.raises(ChangesetTransactionError, match="no before"):
        recover_changeset_transaction(tmp_path, idempotency_key=key, changeset_digest_value="digest")
    path.write_text(
        json.dumps({"changeset_digest": "digest", "state": "STAGED", "before": {}, "backup": "relative"}),
        encoding="utf-8",
    )
    with pytest.raises(ChangesetTransactionError, match="backup path"):
        recover_changeset_transaction(tmp_path, idempotency_key=key, changeset_digest_value="digest")
    backup = tmp_path / "backup"
    backup.mkdir()
    path.write_text(
        json.dumps(
            {
                "changeset_digest": "digest",
                "state": "STAGED",
                "before": {"missing.txt": "a" * 64},
                "backup": str(backup),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ChangesetTransactionError, match="missing backup"):
        recover_changeset_transaction(tmp_path, idempotency_key=key, changeset_digest_value="digest")


def test_recovery_removes_new_file_and_rejects_hash_mismatch(tmp_path):
    key = "recovery-hashes"
    target = tmp_path / "new.txt"
    target.write_text("new", encoding="utf-8")
    backup = tmp_path / "backup"
    backup.mkdir()
    path = _write_journal(
        tmp_path,
        key,
        {
            "changeset_digest": "digest",
            "state": "ROLLING_BACK",
            "before": {"new.txt": None},
            "backup": str(backup),
        },
    )
    recovered = recover_changeset_transaction(tmp_path, idempotency_key=key, changeset_digest_value="digest")
    assert recovered["status"] == "recovered"
    assert not target.exists()
    path.write_text(
        json.dumps(
            {
                "changeset_digest": "digest",
                "state": "ROLLING_BACK",
                "before": {"bad.txt": "b" * 64},
                "backup": str(backup),
            }
        ),
        encoding="utf-8",
    )
    (backup / "bad.txt").write_text("actual", encoding="utf-8")
    with pytest.raises(ChangesetTransactionError, match="hashes"):
        recover_changeset_transaction(tmp_path, idempotency_key=key, changeset_digest_value="digest")


def test_recovery_returns_committed_result_as_replay(tmp_path):
    key = "recovery-committed"
    _write_journal(
        tmp_path,
        key,
        {
            "changeset_digest": "digest",
            "state": "COMMITTED",
            "result": {"status": "ok", "applied": True},
        },
    )

    result = recover_changeset_transaction(tmp_path, idempotency_key=key, changeset_digest_value="digest")

    assert result == {"status": "ok", "applied": True, "replayed": True}


def test_execute_transaction_replays_and_rejects_existing_journal_shapes(tmp_path):
    from simplicio import changeset_transaction

    key = "execute-existing"
    _write_journal(tmp_path, key, {"changeset_digest": "other"})
    with pytest.raises(ChangesetTransactionError, match="another changeset"):
        execute_changeset_transaction({}, root=tmp_path, idempotency_key=key, changeset_digest_value="digest")
    _write_journal(tmp_path, key, {"changeset_digest": "digest", "state": "STAGED"})
    with pytest.raises(ChangesetTransactionError, match="requires recovery"):
        execute_changeset_transaction({}, root=tmp_path, idempotency_key=key, changeset_digest_value="digest")
    _write_journal(
        tmp_path, key, {"changeset_digest": "digest", "state": "COMMITTED", "result": {"status": "ok"}}
    )
    result = execute_changeset_transaction(
        {}, root=tmp_path, idempotency_key=key, changeset_digest_value="digest"
    )
    assert result == {"status": "ok", "replayed": True}
    assert (
        changeset_transaction.existing_transaction_result(
            tmp_path, idempotency_key=key, changeset_digest_value="digest"
        )["replayed"]
        is True
    )


def test_transaction_commit_path_can_remove_deleted_target(tmp_path, monkeypatch):
    from simplicio import changeset_transaction

    target = tmp_path / "delete.txt"
    target.write_text("old", encoding="utf-8")

    def remove_from_candidate(*args, **kwargs):
        (Path(kwargs["root"]) / "delete.txt").unlink()
        return {"status": "ok", "applied": True, "validation": [], "planned_diff": ""}

    monkeypatch.setattr(changeset_transaction, "execute_plan", remove_from_candidate)
    result = execute_changeset_transaction(
        {"touched_files": ["delete.txt"]},
        root=tmp_path,
        idempotency_key="delete-target",
        changeset_digest_value="digest",
    )
    assert result["status"] == "ok"
    assert not target.exists()


def test_transaction_exception_is_recorded_as_commit_partial(tmp_path, monkeypatch):
    from simplicio import changeset_transaction

    target = tmp_path / "a.txt"
    target.write_text("old", encoding="utf-8")
    monkeypatch.setattr(
        changeset_transaction,
        "execute_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(ChangesetTransactionError, match="rolled back"):
        execute_changeset_transaction(
            {"touched_files": ["a.txt"]},
            root=tmp_path,
            idempotency_key="partial",
            changeset_digest_value="digest",
        )


def test_transaction_path_and_mode_guards_cover_non_regular_and_symlink(tmp_path):
    regular = tmp_path / "regular.txt"
    regular.write_text("value", encoding="utf-8")
    assert _mode(regular) == stat.S_IMODE(regular.stat().st_mode)
    assert _mode(tmp_path / "missing.txt") is None

    with pytest.raises(ChangesetTransactionError, match="regular file"):
        _mode(tmp_path)
    with pytest.raises(ChangesetTransactionError, match="unsafe transaction path"):
        _safe_path(tmp_path, "")
    with pytest.raises(ChangesetTransactionError, match="unsafe transaction path"):
        _safe_path(tmp_path, "../escape.txt")

    link = tmp_path / "link"
    try:
        link.symlink_to(regular)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ChangesetTransactionError, match="symlink target"):
        _safe_path(tmp_path, "link/child.txt")


def test_transaction_fault_pause_and_lock_pid_shapes(tmp_path, monkeypatch):
    slept: list[float] = []
    monkeypatch.setenv("SIMPLICIO_TRANSACTION_PAUSE_AT", "stage")
    monkeypatch.setenv("SIMPLICIO_TRANSACTION_PAUSE_SECONDS", "0.25")
    monkeypatch.setattr(time, "sleep", slept.append)
    _pause_for_fault_injection("other")
    _pause_for_fault_injection("stage")
    assert slept == [0.25]

    malformed = tmp_path / "malformed.lock"
    malformed.write_text("not-a-pid", encoding="utf-8")
    assert _lock_owned_by_live_process(malformed) is True
    malformed.write_text("pid=0", encoding="utf-8")
    assert _lock_owned_by_live_process(malformed) is True


def test_transaction_recovery_lock_reclaims_dead_pid(tmp_path, monkeypatch):
    from simplicio import changeset_transaction

    lock = tmp_path / "recovery.lock"
    lock.write_text("pid=999999999", encoding="utf-8")
    monkeypatch.setattr(changeset_transaction, "_lock_owned_by_live_process", lambda _path: False)
    descriptor = changeset_transaction._acquire_recovery_lock(lock)
    assert isinstance(descriptor, int)
    assert lock.read_text(encoding="utf-8").startswith("pid=")
    lock.unlink()


def test_transaction_rollback_handles_created_file_and_restores_mode(tmp_path):
    root = tmp_path / "root"
    backup = tmp_path / "backup"
    root.mkdir()
    backup.mkdir()
    created = root / "created.txt"
    created.write_text("new", encoding="utf-8")
    state_path = tmp_path / "state.json"
    with pytest.raises(ChangesetTransactionError, match="rolled back"):
        _rollback_after_commit_failure(
            root_path=root,
            before={"created.txt": None},
            before_modes={},
            backup=backup,
            state={"state": "COMMITTING"},
            state_path=state_path,
            cause=RuntimeError("commit failed"),
        )
    assert not created.exists()

    target = root / "existing.txt"
    saved = backup / "existing.txt"
    target.write_text("changed", encoding="utf-8")
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text("original", encoding="utf-8")
    with pytest.raises(ChangesetTransactionError, match="rolled back"):
        _rollback_after_commit_failure(
            root_path=root,
            before={"existing.txt": _hash(saved)},
            before_modes={"existing.txt": stat.S_IMODE(saved.stat().st_mode)},
            backup=backup,
            state={"state": "COMMITTING"},
            state_path=state_path,
            cause=RuntimeError("commit failed"),
        )
    assert target.read_text(encoding="utf-8") == "original"


def test_transaction_rollback_reports_mismatch_and_internal_failure(tmp_path, monkeypatch):
    root = tmp_path / "root"
    backup = tmp_path / "backup"
    root.mkdir()
    backup.mkdir()
    (backup / "a.txt").write_text("original", encoding="utf-8")
    state_path = tmp_path / "state.json"

    monkeypatch.setattr("simplicio.changeset_transaction._hash", lambda _path: "wrong")
    with pytest.raises(ChangesetTransactionError, match="could not be proven"):
        _rollback_after_commit_failure(
            root_path=root,
            before={"a.txt": "expected"},
            before_modes={},
            backup=backup,
            state={"state": "COMMITTING"},
            state_path=state_path,
            cause=RuntimeError("commit failed"),
        )

    monkeypatch.setattr(
        "simplicio.changeset_transaction._safe_path",
        lambda *_args: (_ for _ in ()).throw(OSError("locked")),
    )
    with pytest.raises(ChangesetTransactionError, match="could not be proven"):
        _rollback_after_commit_failure(
            root_path=root,
            before={"a.txt": "expected"},
            before_modes={},
            backup=backup,
            state={"state": "COMMITTING"},
            state_path=state_path,
            cause=RuntimeError("commit failed"),
        )


def test_transaction_recovery_lock_reclaim_failure_and_windows_probe(tmp_path, monkeypatch):
    from simplicio import changeset_transaction

    lock = tmp_path / "busy.lock"
    lock.write_text("pid=123", encoding="utf-8")
    monkeypatch.setattr(changeset_transaction, "_lock_owned_by_live_process", lambda _path: False)
    real_unlink = Path.unlink

    def fail_busy_lock(path, *args, **kwargs):
        if path == lock:
            raise OSError("locked")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(
        Path,
        "unlink",
        fail_busy_lock,
    )
    with pytest.raises(ChangesetTransactionError, match="could not be reclaimed"):
        _acquire_recovery_lock(lock)

    class _Kernel:
        def OpenProcess(self, *_args):
            return 0

    monkeypatch.setattr(changeset_transaction.os, "name", "nt")
    monkeypatch.setattr(changeset_transaction.ctypes, "windll", type("W", (), {"kernel32": _Kernel()})())
    lock.write_text("pid=123", encoding="utf-8")
    assert _lock_owned_by_live_process(lock) is False


def test_transaction_replay_rejects_corrupt_journal(tmp_path):
    key = "corrupt-journal"
    path = _state_path(tmp_path.resolve(), key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ChangesetTransactionError, match="unreadable"):
        execute_changeset_transaction({}, root=tmp_path, idempotency_key=key, changeset_digest_value="digest")
