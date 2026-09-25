from __future__ import annotations

import base64
import hashlib
import json
from types import SimpleNamespace

import pytest
import simplicio_fast.binary_changeset as changeset_module

from simplicio_fast.binary_changeset import (
    BinaryChangeJournal,
    BinaryChangeSet,
    BinaryChangeSetError,
    ChangeOperation,
    FRAME,
    HEADER,
    JOURNAL_MAGIC,
    MAGIC,
    decode_binary,
    read_binary,
    sha256,
)


def delete_operation(path: str = "item.txt", before: bytes = b"old\n") -> ChangeOperation:
    return ChangeOperation.from_dict(
        {"op": "delete", "path": path, "before_sha256": sha256(before)}
    )


def changeset(root, operation: ChangeOperation) -> BinaryChangeSet:
    return BinaryChangeSet(
        repository=str(root.resolve()),
        base_generation="b" * 64,
        overlay_generation="o" * 64,
        attempt="attempt-241",
        worktree_id="worktree-241",
        lease_id="lease-241",
        fencing_token="fence-241",
        allowed_paths=(operation.path, *(x for x in (operation.dest,) if x)),
        operations=(operation,),
    )


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ({"op": "unknown", "path": "item.txt"}, "operation_type_invalid"),
        ({"op": True, "path": "item.txt"}, "operation_type_invalid"),
        ({"op": "delete", "path": 1, "before_sha256": "a" * 64}, "path_invalid"),
        ({"op": "delete", "path": "../item.txt", "before_sha256": "a" * 64}, "path_outside_repository"),
        ({"op": "delete", "path": "item.txt", "before_sha256": "bad"}, "sha256_invalid"),
        ({"op": "create", "path": "item.txt"}, "create_payload_missing"),
        ({"op": "rename", "path": "item.txt", "before_sha256": "a" * 64, "after_sha256": "a" * 64}, "rename_payload_missing"),
        ({"op": "delete", "path": "item.txt", "before_sha256": "a" * 64, "content_b64": "%%%"}, "content_encoding_invalid"),
        ({"op": "delete", "path": "item.txt", "before_sha256": "a" * 64, "content_b64": True}, "content_encoding_invalid"),
    ],
)
def test_change_operation_rejects_invalid_contracts(value, reason) -> None:
    with pytest.raises(BinaryChangeSetError, match=reason):
        ChangeOperation.from_dict(value)


def test_replace_range_rejects_ambiguous_or_invalid_line_contracts() -> None:
    base = {
        "op": "replace-range",
        "path": "item.txt",
        "before_sha256": "a" * 64,
        "after_sha256": "b" * 64,
        "content": "new",
        "encoding": "utf-8",
    }
    with pytest.raises(BinaryChangeSetError, match="ambiguous_byte_offset"):
        ChangeOperation.from_dict({**base, "byte_start": 0})
    with pytest.raises(BinaryChangeSetError, match="line_map_required"):
        ChangeOperation.from_dict({key: value for key, value in base.items() if key != "content"})
    with pytest.raises(BinaryChangeSetError, match="line_map_invalid"):
        ChangeOperation.from_dict({**base, "line_map": {"start_line": 0, "end_line": 1}})
    with pytest.raises(BinaryChangeSetError, match="line_map_invalid"):
        ChangeOperation.from_dict({**base, "line_map": {"start_line": True, "end_line": 1}})
    with pytest.raises(BinaryChangeSetError, match="line_map_invalid"):
        ChangeOperation.from_dict({**base, "line_map": {"start_line": "1", "end_line": 1}})
    with pytest.raises(BinaryChangeSetError, match="line_map_hash_mismatch"):
        ChangeOperation.from_dict({**base, "line_map": {"start_line": 1, "end_line": 1}, "line_map_sha256": "bad"})
    with pytest.raises(BinaryChangeSetError, match="replace_payload_missing"):
        ChangeOperation.from_dict({key: value for key, value in {**base, "line_map": {"start_line": 1, "end_line": 1}}.items() if key != "content"})


def test_changeset_scope_and_identity_contracts_fail_closed(tmp_path) -> None:
    operation = delete_operation()
    with pytest.raises(BinaryChangeSetError, match="schema_invalid"):
        BinaryChangeSet("repo", "base", "overlay", "attempt", "worktree", "lease", "fence", ("item.txt",), (operation,), schema="wrong")
    with pytest.raises(BinaryChangeSetError, match="binding_missing"):
        BinaryChangeSet("", "base", "overlay", "attempt", "worktree", "lease", "fence", ("item.txt",), (operation,))
    with pytest.raises(BinaryChangeSetError, match="worktree_invalid"):
        BinaryChangeSet(str(tmp_path), "base", "overlay", "attempt", "../bad", "lease", "fence", ("item.txt",), (operation,))
    with pytest.raises(BinaryChangeSetError, match="allowed_paths_missing"):
        BinaryChangeSet(str(tmp_path), "base", "overlay", "attempt", "worktree", "lease", "fence", (), (operation,))
    with pytest.raises(BinaryChangeSetError, match="path_not_allowed"):
        BinaryChangeSet(str(tmp_path), "base", "overlay", "attempt", "worktree", "lease", "fence", ("other.txt",), (operation,))
    exported = changeset(tmp_path, operation).to_dict()
    exported["changeset_id"] = "0" * 64
    with pytest.raises(BinaryChangeSetError, match="changeset_id_mismatch"):
        BinaryChangeSet.from_dict(exported)


def test_validate_rejects_scope_authority_and_mutation_conflicts(tmp_path) -> None:
    path = tmp_path / "item.txt"
    path.write_bytes(b"old\n")
    item = changeset(tmp_path, delete_operation())
    with pytest.raises(BinaryChangeSetError, match="repository_mismatch"):
        item.validate(tmp_path / "other")
    with pytest.raises(BinaryChangeSetError, match="lease_mismatch"):
        item.validate(tmp_path, lease_id="other")
    with pytest.raises(BinaryChangeSetError, match="fence_mismatch"):
        item.validate(tmp_path, fencing_token="other")
    path.write_bytes(b"changed\n")
    with pytest.raises(BinaryChangeSetError, match="stale_source"):
        item.validate(tmp_path)

    create = ChangeOperation.from_dict({"op": "create", "path": "item.txt", "content": "new\n", "after_sha256": sha256(b"new\n")})
    with pytest.raises(BinaryChangeSetError, match="target_exists"):
        changeset(tmp_path, create).validate(tmp_path)


def test_validate_covers_missing_and_rename_destination_conflicts(tmp_path) -> None:
    missing = changeset(tmp_path, delete_operation("missing.txt"))
    result = missing.validate(tmp_path)
    assert result["idempotent"] is True

    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_bytes(b"source\n")
    destination.write_bytes(b"destination\n")
    rename = ChangeOperation.from_dict({"op": "rename", "path": "source.txt", "dest": "destination.txt", "before_sha256": sha256(b"source\n"), "after_sha256": sha256(b"source\n")})
    with pytest.raises(BinaryChangeSetError, match="rename_destination_exists"):
        changeset(tmp_path, rename).validate(tmp_path)


def test_replace_range_and_binary_decoder_reject_bad_boundaries(tmp_path) -> None:
    path = tmp_path / "item.txt"
    path.write_bytes(b"one\n")
    replacement = ChangeOperation.from_dict({"op": "replace-range", "path": "item.txt", "before_sha256": sha256(b"one\n"), "after_sha256": sha256(b"two\n"), "content": "two", "encoding": "utf-8", "line_map": {"start_line": 2, "end_line": 2}})
    with pytest.raises(BinaryChangeSetError, match="line_map_out_of_range"):
        changeset(tmp_path, replacement).validate(tmp_path)
    raw = changeset(tmp_path, delete_operation()).encode()
    with pytest.raises(BinaryChangeSetError, match="binary_truncated"):
        decode_binary(raw[: HEADER.size - 1])
    invalid_header = bytearray(raw)
    invalid_header[0] ^= 1
    with pytest.raises(BinaryChangeSetError, match="binary_header_invalid"):
        decode_binary(bytes(invalid_header))
    invalid_checksum = bytearray(raw)
    invalid_checksum[-1] ^= 1
    with pytest.raises(BinaryChangeSetError, match="binary_checksum_mismatch"):
        decode_binary(bytes(invalid_checksum))
    with pytest.raises(BinaryChangeSetError, match="binary_missing"):
        read_binary(tmp_path / "missing.sfc")


def test_journal_authority_and_header_fail_closed(tmp_path) -> None:
    journal_path = tmp_path / "journal.bin"
    journal_path.write_bytes(b"bad")
    journal = BinaryChangeJournal(journal_path, worktree_id="worktree-241", lease_id="lease-241", fencing_token="fence-241")
    with pytest.raises(BinaryChangeSetError, match="journal_header_invalid"):
        journal.read()
    empty = BinaryChangeJournal(tmp_path / "empty.bin", worktree_id="worktree-241", lease_id="lease-241", fencing_token="fence-241")
    assert empty.recover()["records"] == 0
    assert empty.inspect()["records"] == 0


def test_operation_and_changeset_contract_edges(tmp_path) -> None:
    with pytest.raises(BinaryChangeSetError, match="operation_invalid"):
        ChangeOperation.from_dict([])
    for path, reason in (("", "path_invalid"), ("a:b", "path_invalid"), ("a//b", "path_invalid"), ("a/./b", "path_outside_repository"), ("a/", "path_invalid")):
        with pytest.raises(BinaryChangeSetError, match=reason):
            ChangeOperation.from_dict({"op": "delete", "path": path, "before_sha256": "a" * 64})
    with pytest.raises(BinaryChangeSetError, match="content_invalid"):
        ChangeOperation.from_dict({"op": "create", "path": "x", "content": 1, "after_sha256": "a" * 64})
    with pytest.raises(BinaryChangeSetError, match="encoding_required"):
        ChangeOperation.from_dict({"op": "replace-range", "path": "x", "before_sha256": "a" * 64, "after_sha256": "b" * 64, "content": "x", "encoding": "", "line_map": {"start_line": 1, "end_line": 1}})
    with pytest.raises(BinaryChangeSetError, match="line_map_invalid"):
        ChangeOperation.from_dict({"op": "replace-range", "path": "x", "before_sha256": "a" * 64, "after_sha256": "b" * 64, "content": "x", "line_map": []})
    via_alias = ChangeOperation.from_dict({"op": "replace-range", "path": "x", "before_sha256": "a" * 64, "after_sha256": "b" * 64, "content": "x", "start_line": 1, "end_line": 1})
    assert via_alias.line_map == {"start_line": 1, "end_line": 1}
    with pytest.raises(BinaryChangeSetError, match="delete_payload_missing"):
        ChangeOperation.from_dict({"op": "delete", "path": "x"})
    with pytest.raises(BinaryChangeSetError, match="rename_destination_invalid"):
        ChangeOperation.from_dict({"op": "rename", "path": "x", "dest": "x", "before_sha256": "a" * 64, "after_sha256": "a" * 64})
    undecodable = ChangeOperation("create", "bytes.bin", content_b64="AP8=", encoding="utf-8")
    assert "content" not in undecodable.to_dict()
    assert changeset_module._normalized_sha(b"\xff") == sha256(b"\xff")
    with pytest.raises(BinaryChangeSetError, match="operations_missing"):
        BinaryChangeSet(str(tmp_path), "b", "o", "a", "w", "l", "f", ("x",), ())
    with pytest.raises(BinaryChangeSetError, match="schema_invalid"):
        BinaryChangeSet.from_dict({"schema": "wrong"})
    with pytest.raises(BinaryChangeSetError, match="changeset_invalid"):
        BinaryChangeSet.from_dict([])
    exported = changeset(tmp_path, delete_operation()).to_dict()
    exported["repository"] = 1
    with pytest.raises(BinaryChangeSetError, match="binding_missing"):
        BinaryChangeSet.from_dict(exported)
    exported = changeset(tmp_path, delete_operation()).to_dict()
    exported["worktree_id"] = 1
    with pytest.raises(BinaryChangeSetError, match="worktree_invalid"):
        BinaryChangeSet.from_dict(exported)
    exported = changeset(tmp_path, delete_operation()).to_dict()
    exported["verification_commands"] = "pytest"
    with pytest.raises(BinaryChangeSetError, match="verification_commands_invalid"):
        BinaryChangeSet.from_dict(exported)
    exported = changeset(tmp_path, delete_operation()).to_dict()
    exported["allowed_paths"] = "item.txt"
    with pytest.raises(BinaryChangeSetError, match="allowed_paths_invalid"):
        BinaryChangeSet.from_dict(exported)


def test_direct_changeset_constructor_rejects_untyped_sequences(tmp_path) -> None:
    operation = delete_operation()
    args = (str(tmp_path), "b", "o", "a", "w", "l", "f")
    with pytest.raises(BinaryChangeSetError, match="allowed_paths_invalid"):
        BinaryChangeSet(*args, allowed_paths="item.txt", operations=(operation,))
    with pytest.raises(BinaryChangeSetError, match="operations_invalid"):
        BinaryChangeSet(*args, allowed_paths=("item.txt",), operations=(object(),))
    with pytest.raises(BinaryChangeSetError, match="verification_commands_invalid"):
        BinaryChangeSet(
            *args,
            allowed_paths=("item.txt",),
            operations=(operation,),
            verification_commands=(1,),
        )


def test_validation_covers_missing_sources_hashes_and_newlines(tmp_path) -> None:
    replacement = ChangeOperation.from_dict({"op": "replace-range", "path": "missing.txt", "before_sha256": "a" * 64, "after_sha256": "b" * 64, "content": "x", "line_map": {"start_line": 1, "end_line": 1}})
    with pytest.raises(BinaryChangeSetError, match="source_missing"):
        changeset(tmp_path, replacement).validate(tmp_path)
    source = tmp_path / "source.txt"
    source.write_bytes(b"one\n")
    wrong_after = ChangeOperation.from_dict({"op": "replace-range", "path": "source.txt", "before_sha256": sha256(b"one\n"), "after_sha256": "b" * 64, "content": "two", "line_map": {"start_line": 1, "end_line": 1}})
    with pytest.raises(BinaryChangeSetError, match="after_hash_mismatch"):
        changeset(tmp_path, wrong_after).validate(tmp_path)
    direct_missing = ChangeOperation("replace-range", "source.txt", sha256(b"one\n"))
    with pytest.raises(BinaryChangeSetError, match="line_map_required"):
        changeset(tmp_path, direct_missing).validate(tmp_path)
    bad_encoding = ChangeOperation("replace-range", "source.txt", sha256(b"one\n"), sha256(b"two\n"), content_b64=base64.b64encode(b"\xff").decode(), encoding="utf-8", line_map={"start_line": 1, "end_line": 1})
    with pytest.raises(BinaryChangeSetError, match="encoding_mismatch"):
        changeset(tmp_path, bad_encoding).validate(tmp_path)
    crlf = tmp_path / "crlf.txt"
    crlf.write_bytes(b"one\r\ntwo\r\n")
    crlf_op = ChangeOperation.from_dict({"op": "replace-range", "path": "crlf.txt", "before_sha256": sha256(b"one\r\ntwo\r\n"), "after_sha256": sha256(b"one\r\nthree\r\n"), "content": "three", "line_map": {"start_line": 2, "end_line": 2}})
    assert changeset(tmp_path, crlf_op).validate(tmp_path)["status"] == "valid"
    rename = ChangeOperation.from_dict({"op": "rename", "path": "missing.txt", "dest": "new.txt", "before_sha256": "a" * 64, "after_sha256": "a" * 64})
    with pytest.raises(BinaryChangeSetError, match="source_missing"):
        changeset(tmp_path, rename).validate(tmp_path)
    source.write_bytes(b"changed\n")
    stale_rename = ChangeOperation.from_dict({"op": "rename", "path": "source.txt", "dest": "new.txt", "before_sha256": sha256(b"one\n"), "after_sha256": sha256(b"one\n")})
    with pytest.raises(BinaryChangeSetError, match="stale_source"):
        changeset(tmp_path, stale_rename).validate(tmp_path)


def _repack_binary(raw: bytes, metadata: bytes, section: bytes, record_count: int) -> bytes:
    return HEADER.pack(MAGIC, 1, 0, len(metadata), record_count, len(section), hashlib.sha256(metadata + section).digest()) + metadata + section


def test_binary_decoder_rejects_metadata_records_and_sections(tmp_path) -> None:
    raw = changeset(tmp_path, delete_operation()).encode()
    metadata = raw[HEADER.size : HEADER.size + HEADER.unpack(raw[: HEADER.size])[3]]
    with pytest.raises(BinaryChangeSetError, match="metadata_invalid"):
        decode_binary(_repack_binary(raw, b"{", b"", 0))
    with pytest.raises(BinaryChangeSetError, match="record_truncated"):
        decode_binary(_repack_binary(raw, metadata, b"\x00\x01\x02", 1))
    with pytest.raises(BinaryChangeSetError, match="record_truncated"):
        decode_binary(_repack_binary(raw, metadata, FRAME.pack(10), 1))
    record = b"{}"
    bad_checksum = FRAME.pack(len(record)) + record + b"0" * 32
    with pytest.raises(BinaryChangeSetError, match="record_checksum_mismatch"):
        decode_binary(_repack_binary(raw, metadata, bad_checksum, 1))
    invalid_record = b"{"
    invalid_record_section = FRAME.pack(len(invalid_record)) + invalid_record + hashlib.sha256(invalid_record).digest()
    with pytest.raises(BinaryChangeSetError, match="record_invalid"):
        decode_binary(_repack_binary(raw, metadata, invalid_record_section, 1))
    with pytest.raises(BinaryChangeSetError, match="section_length_mismatch"):
        decode_binary(_repack_binary(raw, metadata, raw[HEADER.size + len(metadata) :], 0))


def test_journal_rejects_tail_chain_and_authority_edges(tmp_path) -> None:
    item = changeset(tmp_path, delete_operation())
    path = tmp_path / "journal.bin"
    journal = BinaryChangeJournal(path, worktree_id="worktree-241", lease_id="lease-241", fencing_token="fence-241")
    journal.append(item, "sealed")
    assert journal.append(item, "sealed")["idempotent"] is True
    with pytest.raises(BinaryChangeSetError, match="journal_authority_mismatch"):
        BinaryChangeJournal(path, worktree_id="worktree-241", lease_id="other", fencing_token="fence-241").read()
    with pytest.raises(BinaryChangeSetError, match="journal_authority_mismatch"):
        BinaryChangeJournal(path, worktree_id="other", lease_id="lease-241", fencing_token="fence-241").read()
    corrupted = path.read_bytes()
    path.write_bytes(corrupted[:-1] + bytes([corrupted[-1] ^ 1]))
    with pytest.raises(BinaryChangeSetError, match="journal_chain_mismatch"):
        journal.read()
    path.write_bytes(JOURNAL_MAGIC + b"\x01" + FRAME.pack(1) + b"{" + b"0" * 32)
    with pytest.raises(BinaryChangeSetError, match="journal_record_invalid"):
        journal.read()
    path.write_bytes(JOURNAL_MAGIC + b"\x01" + FRAME.pack(100))
    assert journal.read(recover=True) == []
    with pytest.raises(BinaryChangeSetError, match="journal_truncated_tail"):
        journal.read()
    with pytest.raises(BinaryChangeSetError, match="lease_mismatch"):
        BinaryChangeJournal(tmp_path / "other.bin", worktree_id="worktree-241", lease_id="other", fencing_token="fence-241").append(item, "sealed")
    with pytest.raises(BinaryChangeSetError, match="fence_mismatch"):
        BinaryChangeJournal(tmp_path / "other2.bin", worktree_id="worktree-241", lease_id="lease-241", fencing_token="other").append(item, "sealed")


def test_adapter_and_refresh_fail_closed(monkeypatch, tmp_path) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(b"one\n")
    operation = ChangeOperation.from_dict({"op": "delete", "path": "source.txt", "before_sha256": sha256(b"one\n")})
    item = changeset(tmp_path, operation)
    adapter = changeset_module.DevCliAdapter()
    monkeypatch.setattr(changeset_module.shutil, "which", lambda _: None)
    with pytest.raises(BinaryChangeSetError, match="dev_cli_unavailable"):
        adapter.materialize(item, tmp_path)
    monkeypatch.setattr(changeset_module.shutil, "which", lambda _: "fake-cli")
    monkeypatch.setattr(changeset_module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="{", stderr=""))
    with pytest.raises(BinaryChangeSetError, match="dev_cli_invalid_receipt"):
        adapter.materialize(item, tmp_path)
    monkeypatch.setattr(changeset_module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=json.dumps({"status": "rejected", "applied": False}), stderr=""))
    with pytest.raises(BinaryChangeSetError, match="dev_cli_rejected"):
        adapter.materialize(item, tmp_path)
    monkeypatch.setattr(changeset_module.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(__import__("subprocess").TimeoutExpired("fake", 1)))
    with pytest.raises(BinaryChangeSetError, match="dev_cli_TimeoutExpired"):
        adapter.materialize(item, tmp_path)
    monkeypatch.setattr(changeset_module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="failure"))
    failed = changeset_module.refresh_semantic_inputs(tmp_path, ["source.txt"])
    assert failed["status"] == "unverified"
    monkeypatch.setattr(changeset_module.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(__import__("subprocess").TimeoutExpired("fake", 1)))
    assert changeset_module.refresh_semantic_inputs(tmp_path, ["source.txt"])["status"] == "unverified"
    monkeypatch.setattr(changeset_module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="not-json", stderr=""))
    assert changeset_module.refresh_semantic_inputs(tmp_path, ["source.txt"])["status"] == "refreshed"


def test_unknown_dev_cli_effect_is_durable_and_locks_replay(tmp_path) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(b"one\n")
    item = changeset(tmp_path, delete_operation("source.txt", b"one\n"))
    journal = BinaryChangeJournal(
        tmp_path / "journal.bin",
        worktree_id="worktree-241",
        lease_id="lease-241",
        fencing_token="fence-241",
    )
    calls = []

    class TimeoutAdapter:
        def materialize(self, changeset, root):
            calls.append((changeset.changeset_id, root))
            raise changeset_module.BinaryChangeSetUnknownEffect("dev_cli_TimeoutExpired")

    first = changeset_module.materialize(
        item,
        tmp_path,
        journal,
        adapter=TimeoutAdapter(),
        refresh=lambda *_: {"status": "unexpected"},
    )
    assert first["status"] == "locked", first
    assert first["reason_code"] == "unknown_effect"
    assert first["reconcile_required"] is True
    assert journal.read()[-1]["state"] == "unknown"

    second = changeset_module.materialize(
        item,
        tmp_path,
        journal,
        adapter=TimeoutAdapter(),
        refresh=lambda *_: {"status": "unexpected"},
    )
    assert second["status"] == "locked"
    assert second["reason_code"] == "unknown_effect"
    assert len(calls) == 1
    assert source.read_bytes() == b"one\n"


def test_unknown_effect_reconciliation_allows_only_proven_retry(tmp_path) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(b"one\n")
    item = changeset(tmp_path, delete_operation("source.txt", b"one\n"))
    journal = BinaryChangeJournal(
        tmp_path / "journal.bin",
        worktree_id="worktree-241",
        lease_id="lease-241",
        fencing_token="fence-241",
    )

    class AppliedTimeoutAdapter:
        def materialize(self, changeset, root):
            source.unlink()
            raise changeset_module.BinaryChangeSetUnknownEffect("dev_cli_TimeoutExpired")

    first = changeset_module.materialize(
        item, tmp_path, journal, adapter=AppliedTimeoutAdapter(), refresh=lambda *_: {}
    )
    assert first["status"] == "locked"
    applied = changeset_module.reconcile_unknown_effect(item, tmp_path, journal)
    assert applied["status"] == "reconciled"
    assert applied["reconciliation"] == "already_applied"
    assert applied["retry_allowed"] is False

    class MustNotRetryAdapter:
        def materialize(self, changeset, root):
            raise AssertionError("reconciliation must prevent blind retry")

    replay = changeset_module.materialize(
        item, tmp_path, journal, adapter=MustNotRetryAdapter(), refresh=lambda *_: {}
    )
    assert replay["status"] == "idempotent"

    source.write_bytes(b"one\n")
    second_item = changeset(tmp_path, delete_operation("source.txt", b"one\n"))
    second_journal = BinaryChangeJournal(
        tmp_path / "second-journal.bin",
        worktree_id="worktree-241",
        lease_id="lease-241",
        fencing_token="fence-241",
    )

    class NotAppliedTimeoutAdapter:
        def materialize(self, changeset, root):
            raise changeset_module.BinaryChangeSetUnknownEffect("dev_cli_TimeoutExpired")

    changeset_module.materialize(
        second_item,
        tmp_path,
        second_journal,
        adapter=NotAppliedTimeoutAdapter(),
        refresh=lambda *_: {},
    )
    not_applied = changeset_module.reconcile_unknown_effect(
        second_item, tmp_path, second_journal
    )
    assert not_applied["reconciliation"] == "not_applied"
    assert not_applied["retry_allowed"] is True

    class DeleteAdapter:
        def materialize(self, changeset, root):
            source.unlink()
            return {"status": "ok"}

    retried = changeset_module.materialize(
        second_item,
        tmp_path,
        second_journal,
        adapter=DeleteAdapter(),
        refresh=lambda *_: {"status": "refreshed"},
    )
    assert retried["status"] == "applied"
    assert not source.exists()


def test_unknown_effect_reconciliation_keeps_ambiguous_state_locked(tmp_path) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(b"one\n")
    item = changeset(tmp_path, delete_operation("source.txt", b"one\n"))
    journal = BinaryChangeJournal(
        tmp_path / "journal.bin",
        worktree_id="worktree-241",
        lease_id="lease-241",
        fencing_token="fence-241",
    )

    class TimeoutAdapter:
        def materialize(self, changeset, root):
            raise changeset_module.BinaryChangeSetUnknownEffect("dev_cli_TimeoutExpired")

    changeset_module.materialize(
        item, tmp_path, journal, adapter=TimeoutAdapter(), refresh=lambda *_: {}
    )
    source.write_bytes(b"unexpected\n")
    reconciled = changeset_module.reconcile_unknown_effect(item, tmp_path, journal)
    assert reconciled["status"] == "locked"
    assert reconciled["reconcile_required"] is True
    assert reconciled["evidence"]["reconciliation"] == "ambiguous"
    assert journal.read()[-1]["state"] == "unknown"
