from __future__ import annotations

import json
import struct

import pytest

from simplicio import hbp
from simplicio.hbp import HBP_FILE_NAME, HBP_MAGIC, HbpError, HbpEvidenceLedger, row_content_hash


def test_hbp_evidence_matches_runtime_layout_and_chain(tmp_path) -> None:
    ledger = HbpEvidenceLedger(tmp_path)

    first = ledger.record("edit", "diff-patch-001", "agent-01", timestamp=1)
    second = ledger.record("edit", "diff-patch-002", "agent-01", timestamp=2)

    raw = (tmp_path / HBP_FILE_NAME).read_bytes()
    assert raw[:4] == HBP_MAGIC
    assert raw[4:8] == struct.pack("<HH", 1, 0)
    assert first.seq == 0
    assert first.prev_hash == "genesis"
    assert first.hash == row_content_hash(0, "genesis", first.topic, first.payload, first.provenance, None)
    assert second.prev_hash == first.hash
    assert second.payload == "hbp-fields/v1:4:edit:14:diff-patch-002:8:agent-01"
    assert [row.timestamp for row in ledger.verify()] == [1, 2]


def test_hbp_rejects_legacy_json_and_tampering(tmp_path) -> None:
    path = tmp_path / HBP_FILE_NAME
    path.write_text('{"seq":0}\n', encoding="utf-8")
    with pytest.raises(HbpError, match="explicit migration"):
        HbpEvidenceLedger(tmp_path).verify()

    path.unlink()
    ledger = HbpEvidenceLedger(tmp_path)
    ledger.record("edit", "evidence", "agent", timestamp=1)
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 1
    path.write_bytes(raw)
    with pytest.raises(HbpError, match="hash mismatch"):
        ledger.verify()


def test_hbp_rejects_truncation_and_unknown_optional_marker(tmp_path) -> None:
    ledger = HbpEvidenceLedger(tmp_path)
    ledger.append("edit", "evidence", "agent", "token", timestamp=1)
    path = tmp_path / HBP_FILE_NAME
    raw = path.read_bytes()
    assert ledger.verify()[0].crypto_token == "token"
    path.write_bytes(raw[:-1])
    with pytest.raises(HbpError, match="truncated|record"):
        ledger.verify()


@pytest.mark.parametrize(
    ("offset", "value", "message"),
    [(4, 2, "version or flags"), (6, 1, "version or flags")],
)
def test_hbp_rejects_unknown_header_contract(tmp_path, offset, value, message) -> None:
    ledger = HbpEvidenceLedger(tmp_path)
    ledger.record("edit", "evidence", "agent", timestamp=1)
    path = tmp_path / HBP_FILE_NAME
    raw = bytearray(path.read_bytes())
    raw[offset] = value
    path.write_bytes(raw)

    with pytest.raises(HbpError, match=message):
        ledger.verify()


def test_hbp_migrates_legacy_jsonl_atomically_and_idempotently(tmp_path) -> None:
    legacy = tmp_path / "events.jsonl"
    legacy.write_text(
        json.dumps({"event": "task_complete", "payload": {"files": 2}}) + "\n",
        encoding="utf-8",
    )
    ledger = HbpEvidenceLedger(tmp_path / "hbp", file_name="events.hbp")

    assert ledger.migrate_jsonl(legacy) == 1
    assert not legacy.exists()
    assert (tmp_path / "events.jsonl.migrated").is_file()
    assert ledger.verify()[0].payload.startswith("hbp-fields/v1")
    assert "payload.files=2" in ledger.verify()[0].payload

    # A retry after the post-replace/pre-rename window cannot duplicate rows.
    assert ledger.migrate_jsonl(legacy) == 0
    assert len(ledger.verify()) == 1


def test_hbp_migration_validates_before_creating_target(tmp_path) -> None:
    legacy = tmp_path / "events.jsonl"
    legacy.write_text('{"ok": true}\nnot-json\n', encoding="utf-8")
    ledger = HbpEvidenceLedger(tmp_path / "hbp", file_name="events.hbp")

    with pytest.raises(ValueError, match="invalid legacy JSONL"):
        ledger.migrate_jsonl(legacy)
    assert not ledger.path.exists()
    assert legacy.exists()


def test_hbp_rejects_unsafe_file_names_and_scalar_violations(tmp_path) -> None:
    for file_name in ("", "nested/ledger.bin", "ledger.lock"):
        with pytest.raises(ValueError, match="plain file name"):
            HbpEvidenceLedger(tmp_path, file_name=file_name)

    ledger = HbpEvidenceLedger(tmp_path)
    with pytest.raises(HbpError, match="field names"):
        ledger.record_fields("topic", {"": "value"}, "agent:test")
    with pytest.raises(HbpError, match="scalar"):
        ledger.record_fields("topic", {"value": {"nested": True}}, "agent:test")


def test_hbp_rejects_existing_lock_and_handles_missing_migration_source(tmp_path) -> None:
    ledger = HbpEvidenceLedger(tmp_path)
    ledger.directory.mkdir(parents=True, exist_ok=True)
    ledger.lock_path.write_text("held", encoding="ascii")
    with pytest.raises(HbpError, match="locked"):
        ledger.append("topic", "payload", "agent:test")
    ledger.lock_path.unlink()
    assert ledger.migrate_jsonl(tmp_path / "missing.jsonl") == 0


def test_hbp_rejects_malformed_record_shapes() -> None:
    with pytest.raises(HbpError, match="exceeds"):
        hbp._put_string(bytearray(), "x" * (hbp.MAX_FIELD_BYTES + 1), "topic")
    with pytest.raises(HbpError, match="truncated"):
        hbp._take(b"x", 0, 2)
    with pytest.raises(HbpError, match="exceeds"):
        hbp._take_string(struct.pack("<I", hbp.MAX_FIELD_BYTES + 1), 0, "topic")
    with pytest.raises(HbpError, match="UTF-8"):
        hbp._take_string(struct.pack("<I", 1) + b"\xff", 0, "topic")
    with pytest.raises(HbpError, match="record exceeds"):
        hbp._decode_record(b"x" * (hbp.MAX_RECORD_BYTES + 1))


def test_hbp_rejects_marker_trailing_chain_and_hash_errors() -> None:
    ledger = HbpEvidenceLedger(".")
    row = hbp.HbpRow(0, 1, "topic", "payload", "agent", "token", hbp.HBP_GENESIS, "hash")
    body = bytearray(hbp._encode_record(row)[4:])
    marker_offset = (
        16 + 4 + len(row.topic.encode()) + 4 + len(row.payload.encode()) + 4 + len(row.provenance.encode())
    )
    body[marker_offset] = 2
    with pytest.raises(HbpError, match="optional-token"):
        hbp._decode_record(bytes(body))
    with pytest.raises(HbpError, match="trailing"):
        hbp._decode_record(hbp._encode_record(row)[4:] + b"x")

    path = ledger.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(HBP_MAGIC + struct.pack("<HH", hbp.HBP_VERSION, hbp.HBP_FLAGS) + hbp._encode_record(row))
    with pytest.raises(HbpError, match="content hash"):
        ledger.verify()


def test_hbp_rejects_bad_file_header_and_sequence(tmp_path) -> None:
    path = tmp_path / HBP_FILE_NAME
    path.write_bytes(b"bad")
    with pytest.raises(HbpError, match="explicit migration"):
        HbpEvidenceLedger(tmp_path).verify()

    ledger = HbpEvidenceLedger(tmp_path)
    row = hbp.HbpRow(1, 1, "topic", "payload", "agent", None, hbp.HBP_GENESIS, "hash")
    path.write_bytes(HBP_MAGIC + struct.pack("<HH", hbp.HBP_VERSION, hbp.HBP_FLAGS) + hbp._encode_record(row))
    with pytest.raises(HbpError, match="sequence gap"):
        ledger.verify()


def test_hbp_migration_completes_existing_target_and_timestamp_default(tmp_path) -> None:
    legacy = tmp_path / "events.jsonl"
    legacy.write_text(json.dumps({"event": "done"}) + "\n", encoding="utf-8")
    ledger = HbpEvidenceLedger(tmp_path / "hbp", file_name="events.hbp")
    ledger.record("edit", "evidence", "agent")
    assert ledger.migrate_jsonl(legacy) == 1
    assert not legacy.exists()
    assert (tmp_path / "events.jsonl.migrated").exists()


def test_hbp_empty_file_and_oversized_ledger_are_rejected(tmp_path, monkeypatch) -> None:
    ledger = HbpEvidenceLedger(tmp_path)
    ledger.path.write_bytes(b"")
    assert ledger.verify() == ()
    monkeypatch.setattr(hbp, "MAX_LEDGER_BYTES", 1)
    with pytest.raises(HbpError, match="ledger exceeds"):
        ledger.record("edit", "evidence", "agent", timestamp=1)
