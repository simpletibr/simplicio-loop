from __future__ import annotations

import hashlib
import json

import pytest

from simplicio.changeset_v2 import execute_changeset
from simplicio.changeset_transaction import (
    ChangesetTransactionError,
    _state_path,
    recover_changeset_transaction,
    execute_changeset_transaction,
)


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
    assert replay["status"] == "ok"
    assert replay["replayed"] is True
    assert (tmp_path / "a.txt").stat().st_mtime_ns == first_mtime
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "created\n"


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
