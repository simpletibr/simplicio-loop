import pytest
from simplicio_mapper.context_graph_v1 import (
    ContextGraphError, Provenance, build_context_packet, build_graph,
    expand_context_packet, fact, validate_context_packet,
)


def packet_graph():
    p = Provenance("a.py", 1, 2, "a" * 64, "parser", "1")
    fs = [
        fact("repo", "g1", "body", "body", {"text": "large"}, p),
        fact("repo", "g1", "test", "test", {"name": "test_x"}, p),
        fact("repo", "g1", "symbol", "sig", {"signature": "x()"}, p),
        fact("repo", "g1", "rule", "rule", {"rule": "auth"}, p),
    ]
    return build_graph(repo_id="repo", generation="g1", config_hash="c",
                       facts=fs, relations=[])


def test_priority_puts_signature_rule_test_before_body():
    packet = build_context_packet(packet_graph(), max_bytes=10000)
    assert [i["kind"] for i in packet["items"]] == ["symbol", "rule", "test", "body"]


def test_budget_truncates_with_explicit_metrics_and_handles():
    packet = build_context_packet(packet_graph(), max_bytes=10000, max_items=2)
    assert packet["truncated"] and packet["omitted_items"] == 2
    assert all(i["handle"].startswith("fast://context/") for i in packet["items"])
    assert packet["budget"]["token_count"] is None
    assert packet["budget"]["token_count_null_reason"] == "TOKENIZER_UNAVAILABLE"


def test_receipt_is_deterministic_and_validates_integrity():
    left = build_context_packet(packet_graph())
    assert left == build_context_packet(packet_graph())
    assert validate_context_packet(left) == left
    left["items"][0]["value"] = "tampered"
    with pytest.raises(ContextGraphError) as error:
        validate_context_packet(left)
    assert error.value.reason_code == "packet_corrupt"


def test_lazy_expansion_preserves_lineage():
    first = build_context_packet(packet_graph(), max_items=1)
    second = expand_context_packet(packet_graph(), first, max_items=4)
    assert second["ancestor_packet_hash"] == first["packet_hash"]
    assert second["lineage_reason"] == "EXPANSION"
    assert len(second["items"]) == 4


def test_stale_generation_is_rejected():
    packet = build_context_packet(packet_graph())
    with pytest.raises(ContextGraphError) as error:
        validate_context_packet(packet, expected_generation="g2")
    assert error.value.reason_code == "packet_generation_stale"
