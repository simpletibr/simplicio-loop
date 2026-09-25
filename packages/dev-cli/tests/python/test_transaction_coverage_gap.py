"""Additional unit coverage for simplicio/transaction.py helpers."""

from __future__ import annotations

import pytest

from simplicio import transaction as tx_mod
from simplicio.transaction import (
    ReceiptError,
    UnsafePathError,
    VerificationReceipt,
    begin_transaction,
    sha256_bytes,
)


def test_validated_receipt_commands_length_mismatch():
    with pytest.raises(ReceiptError, match="length mismatch"):
        tx_mod._validated_receipt_commands(["pytest"], [0, 1], require_promotable=False)


def test_validated_receipt_commands_empty_command():
    with pytest.raises(ReceiptError, match="empty command"):
        tx_mod._validated_receipt_commands([""], [0], require_promotable=False)


def test_validated_receipt_commands_requires_promotable_nonempty():
    with pytest.raises(ReceiptError, match="cannot promote without"):
        tx_mod._validated_receipt_commands([], [], require_promotable=True)


def test_validated_receipt_commands_rejects_placeholder():
    with pytest.raises(ReceiptError, match="placeholder"):
        tx_mod._validated_receipt_commands(
            ["echo 'configure SIMPLICIO_TEST_CMD'"], [0], require_promotable=True
        )


def test_validated_receipt_commands_ok_not_promotable():
    commands, codes = tx_mod._validated_receipt_commands(["pytest"], ["0"], require_promotable=False)
    assert commands == ("pytest",)
    assert codes == (0,)


def test_relative_rejects_windows_drive_path():
    with pytest.raises(UnsafePathError):
        tx_mod._relative("C:/secret/file.py")


def test_relative_rejects_unc_path():
    with pytest.raises(UnsafePathError):
        tx_mod._relative("//server/share/file.py")


def test_relative_rejects_absolute_posix_path():
    with pytest.raises(UnsafePathError):
        tx_mod._relative("/etc/passwd")


def test_relative_rejects_traversal():
    with pytest.raises(UnsafePathError):
        tx_mod._relative("../secret.py")


def test_relative_rejects_empty_path():
    with pytest.raises(UnsafePathError):
        tx_mod._relative(".")


def test_relative_normalizes_backslashes():
    assert tx_mod._relative("a\\b\\c.py") == "a/b/c.py"


def test_inside_rejects_symlink_component(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real_dir)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable on this machine: {exc}")
    with pytest.raises(UnsafePathError, match="symlink"):
        tx_mod._inside(tmp_path, "link/file.py")


def test_git_dirty_returns_false_on_oserror(monkeypatch, tmp_path):
    def _boom(*a, **k):
        raise OSError("no git")

    monkeypatch.setattr(tx_mod.subprocess, "run", _boom)
    assert tx_mod._git_dirty(tmp_path) is False


def test_sha256_bytes_matches_hashlib():
    import hashlib

    assert sha256_bytes(b"hello") == hashlib.sha256(b"hello").hexdigest()


def test_verification_receipt_from_dict_wrong_schema():
    with pytest.raises(ReceiptError, match="unsupported"):
        VerificationReceipt.from_dict({"schema": "wrong/v1"})


def test_verification_receipt_from_dict_malformed_files_type():
    payload = {
        "schema": tx_mod.SCHEMA,
        "files": "not-a-list",
        "commands": [],
        "exit_codes": [],
    }
    with pytest.raises(ReceiptError, match="malformed"):
        VerificationReceipt.from_dict(payload)


def test_verification_receipt_from_dict_malformed_exit_codes_type():
    payload = {
        "schema": tx_mod.SCHEMA,
        "files": [],
        "commands": [],
        "exit_codes": "not-a-list",
    }
    with pytest.raises(ReceiptError, match="malformed"):
        VerificationReceipt.from_dict(payload)


def test_verification_receipt_from_dict_digest_mismatch(tmp_path):
    (tmp_path / "app.py").write_bytes(b"old\n")
    tx = begin_transaction(tmp_path, dirty_policy="preserve", transaction_id="tx-test")
    (tx.candidate / "app.py").write_bytes(b"new\n")
    receipt = tx.receipt(["app.py"], commands=["pytest -q"], exit_codes=[0])
    tampered = receipt.to_dict()
    tampered["receipt_digest"] = "0" * 64
    with pytest.raises(ReceiptError, match="digest mismatch"):
        VerificationReceipt.from_dict(tampered)


def test_begin_transaction_rejects_invalid_dirty_policy(tmp_path):
    with pytest.raises(ValueError, match="dirty_policy"):
        begin_transaction(tmp_path, dirty_policy="bogus")
