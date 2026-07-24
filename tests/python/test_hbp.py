from __future__ import annotations

import struct

import pytest

from simplicio.hbp import HBP_MAGIC, HBP_FILE_NAME, HbpError, HbpEvidenceLedger, row_content_hash


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
