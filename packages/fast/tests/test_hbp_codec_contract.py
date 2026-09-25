import json
from pathlib import Path
import pytest
from simplicio_fast.hbp_codec import (
    HbpError,
    LogicalPointer,
    seal_receipt,
    sha256_hex,
    verified_alias,
    verify_chain,
)

VECTORS = json.loads(
    (Path(__file__).parents[1] / "contracts/hbp/v1/golden-vectors.json").read_text(
        encoding="utf-8"
    )
)["vectors"]


def test_runtime_fast_golden_parity_without_runtime_process():
    assert sha256_hex(b"abc") == VECTORS["sha256_abc"]
    assert verified_alias(b"abc", VECTORS["sha256_abc"]) == VECTORS["alias_abc"]
    assert seal_receipt("EVENT|name=α|json=0") == VECTORS["first_receipt"]
    assert verify_chain([VECTORS["first_receipt"]]) == VECTORS["first_receipt"][-64:]


def test_alias_pointer_tamper_and_partial_fail_closed():
    with pytest.raises(HbpError, match="ALIAS_UNVERIFIED"):
        verified_alias(b"x", VECTORS["sha256_abc"])
    LogicalPointer(VECTORS["sha256_abc"], 2, 3).validate(5)
    with pytest.raises(HbpError, match="HBI_OUT_OF_BOUNDS"):
        LogicalPointer(VECTORS["sha256_abc"], 2, 4).validate(5)
    with pytest.raises(HbpError, match="HBP_INVALID_CHAIN"):
        verify_chain([VECTORS["first_receipt"].replace("name=α", "name=x")])
    with pytest.raises(HbpError, match="HBP_PARTIAL_APPEND"):
        verify_chain(["partial"])


def test_lf_crlf_and_unverified_identity_are_rejected():
    for row in ("bad\nrow", "bad\r\nrow"):
        with pytest.raises(HbpError, match="HBP_MALFORMED_ROW"):
            seal_receipt(row)
