import pytest
from simplicio_fast.slot_executor import (
    FastExecutorError,
    consume_context_packet,
    digest,
)


def packet():
    value = {
        "schema": "simplicio.context-packet/v1",
        "repo_id": "repo",
        "generation": "g1",
        "graph_digest": "g" * 64,
        "items": [
            {
                "fact_id": "f",
                "kind": "symbol",
                "value": {"signature": "x()"},
                "content_sha256": "c" * 64,
                "provenance": {},
                "handle": f"fast://context/{'g' * 64}/f",
            }
        ],
        "coverage": 1.0,
        "truncated": False,
        "omitted_items": 0,
        "budget": {
            "max_bytes": 8192,
            "max_items": 64,
            "token_count": None,
            "token_count_null_reason": "TOKENIZER_UNAVAILABLE",
        },
        "ancestor_packet_hash": None,
        "lineage_reason": "INITIAL",
    }
    value["packet_hash"] = digest(value)
    value["encoded_bytes"] = 1
    return value


def test_consumes_public_handles_without_offsets_or_completion_authority():
    result = consume_context_packet(packet(), expected_generation="g1")
    assert result["handles"][0].startswith("fast://context/")
    assert result["completion_authority"] == "LOOP_ONLY"


def test_rejects_corrupt_or_stale_packets():
    value = packet()
    value["coverage"] = 0
    with pytest.raises(FastExecutorError) as corrupt:
        consume_context_packet(value)
    assert corrupt.value.reason_code == "packet_corrupt"
    with pytest.raises(FastExecutorError) as stale:
        consume_context_packet(packet(), expected_generation="g2")
    assert stale.value.reason_code == "packet_generation_stale"
