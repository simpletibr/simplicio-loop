from __future__ import annotations

import json

import pytest

from simplicio.transaction import (
    ConcurrentModificationError,
    DirtyWorktreeError,
    ReceiptError,
    UnsafePathError,
    VerificationReceipt,
    begin_transaction,
)


def _candidate(tx, relative: str, content: str) -> None:
    path = tx.candidate / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))


def test_receipt_round_trip_and_digest_is_bound(tmp_path):
    (tmp_path / "app.py").write_bytes(b"old\n")
    tx = begin_transaction(tmp_path, dirty_policy="preserve", transaction_id="tx-test")
    _candidate(tx, "app.py", "new\n")
    receipt = tx.receipt(["app.py"], commands=["pytest -q"], exit_codes=[0])

    restored = VerificationReceipt.from_dict(json.loads(json.dumps(receipt.to_dict())))

    assert restored.digest == receipt.digest
    assert restored.transaction_id == "tx-test"


def test_receipt_digest_tamper_is_rejected(tmp_path):
    tx = begin_transaction(tmp_path, dirty_policy="preserve")
    _candidate(tx, "new.txt", "new\n")
    payload = tx.receipt(["new.txt"], commands=["pytest -q"], exit_codes=[0]).to_dict()
    payload["candidate_sha"] = "tampered"

    with pytest.raises(ReceiptError, match="digest mismatch"):
        VerificationReceipt.from_dict(payload)


def test_dirty_reject_and_explicit_preserve(tmp_path, monkeypatch):
    monkeypatch.setattr("simplicio.transaction._git_dirty", lambda root: True)

    with pytest.raises(DirtyWorktreeError):
        begin_transaction(tmp_path)
    tx = begin_transaction(tmp_path, dirty_policy="preserve")
    assert tx.dirty_policy == "preserve"


def test_candidate_mutation_after_receipt_is_fail_closed(tmp_path):
    (tmp_path / "app.py").write_text("old\n", encoding="utf-8")
    tx = begin_transaction(tmp_path, dirty_policy="preserve")
    _candidate(tx, "app.py", "new\n")
    receipt = tx.receipt(["app.py"], commands=["pytest -q"], exit_codes=[0])
    (tx.candidate / "app.py").write_bytes(b"changed-after-test\n")

    with pytest.raises(ReceiptError, match="candidate changed"):
        tx.promote(receipt)
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "old\n"


def test_concurrent_root_change_is_rejected(tmp_path):
    (tmp_path / "app.py").write_text("old\n", encoding="utf-8")
    tx = begin_transaction(tmp_path, dirty_policy="preserve")
    _candidate(tx, "app.py", "new\n")
    receipt = tx.receipt(["app.py"], commands=["pytest -q"], exit_codes=[0])
    (tmp_path / "app.py").write_text("concurrent\n", encoding="utf-8")

    with pytest.raises(ConcurrentModificationError):
        tx.promote(receipt)


def test_promotion_ignores_unrelated_worktree_changes(tmp_path):
    (tmp_path / "app.py").write_text("old\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("draft\n", encoding="utf-8")
    tx = begin_transaction(tmp_path, dirty_policy="preserve")
    _candidate(tx, "app.py", "new\n")
    receipt = tx.receipt(["app.py"], commands=["pytest -q"], exit_codes=[0])
    (tmp_path / "notes.md").write_text("updated draft\n", encoding="utf-8")

    tx.promote(receipt)

    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\n"
    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "updated draft\n"


@pytest.mark.parametrize(
    "relative",
    [
        "../escape.txt",
        "C:/escape.txt",
        r"C:\\escape.txt",
        r"\\server\share\escape.txt",
        "C:relative.txt",
        "/tmp/escape.txt",
        "",
    ],
)
def test_paths_cannot_escape_root(tmp_path, relative):
    tx = begin_transaction(tmp_path, dirty_policy="preserve")
    with pytest.raises(UnsafePathError):
        tx.receipt([relative])


def test_promotion_and_rollback_are_byte_for_byte(tmp_path):
    (tmp_path / "app.py").write_bytes(b"old\r\n")
    tx = begin_transaction(tmp_path, dirty_policy="preserve", transaction_id="tx-promote")
    _candidate(tx, "app.py", "new\r\n")
    receipt = tx.receipt(["app.py"], commands=["pytest -q"], exit_codes=[0])
    tx.promote(receipt)
    assert (tmp_path / "app.py").read_bytes() == b"new\r\n"
    tx.rollback(receipt)
    assert (tmp_path / "app.py").read_bytes() == b"old\r\n"


def test_journal_can_recover_receipt_for_rollback(tmp_path):
    (tmp_path / "app.py").write_bytes(b"old\n")
    tx = begin_transaction(tmp_path, dirty_policy="preserve", transaction_id="tx-recover")
    _candidate(tx, "app.py", "new\n")
    receipt = tx.receipt(["app.py"], commands=["pytest -q"], exit_codes=[0])
    tx.promote(receipt)

    recovered = begin_transaction(tmp_path, dirty_policy="preserve", transaction_id="tx-recover")
    recovered.rollback()

    assert (tmp_path / "app.py").read_bytes() == b"old\n"


def test_receipt_rejects_command_exit_code_length_mismatch(tmp_path):
    tx = begin_transaction(tmp_path, dirty_policy="preserve")
    _candidate(tx, "app.py", "new\n")

    with pytest.raises(ReceiptError, match="length mismatch"):
        tx.receipt(["app.py"], commands=["pytest -q"], exit_codes=[0, 1])


@pytest.mark.parametrize(
    ("commands", "match"),
    [
        ([], "verification command receipt"),
        (["echo 'configure SIMPLICIO_TEST_CMD'"], "placeholder verification command"),
    ],
)
def test_promotion_requires_concrete_verification_command(tmp_path, commands, match):
    (tmp_path / "app.py").write_text("old\n", encoding="utf-8")
    tx = begin_transaction(tmp_path, dirty_policy="preserve")
    _candidate(tx, "app.py", "new\n")
    receipt = tx.receipt(["app.py"], commands=commands, exit_codes=[0] if commands else [])

    with pytest.raises(ReceiptError, match=match):
        tx.promote(receipt)

    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "old\n"
