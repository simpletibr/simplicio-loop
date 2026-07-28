from __future__ import annotations

import pytest

from simplicio_mapper.context_graph_v1 import Provenance, build_graph, fact
from simplicio_mapper.hbp_codec import (
    MAGIC,
    decode_hbp,
    encode_hbp,
    from_external_json,
    negotiate_capability,
    to_external_json,
)
from simplicio_mapper.prism_task_facts import PrismFactsError, build_prism_task_facts
from simplicio_mapper.prism_work_delta import build_prism_work_delta


def _facts():
    p = Provenance("src/app.py", 1, 2, "a" * 64, "parser", "1")
    facts = [fact("repo", "g1", "symbol", "Service", {}, p)]
    graph = build_graph(repo_id="repo", generation="g1", config_hash="c", facts=facts, relations=[])
    payload = build_prism_task_facts(
        graph,
        task_id="T1",
        declared_write_set=["src/app.py"],
        seed_fact_ids=[facts[0]["fact_id"]],
    )
    return graph, payload


def test_round_trip_and_byte_parity():
    _graph, payload = _facts()
    blob1 = encode_hbp(payload)
    blob2 = encode_hbp(payload)
    assert blob1 == blob2
    assert blob1.startswith(MAGIC)
    decoded = decode_hbp(blob1)
    assert decoded == payload


def test_tamper_rejection():
    _graph, payload = _facts()
    blob = bytearray(encode_hbp(payload))
    blob[-1] ^= 0xFF
    with pytest.raises(PrismFactsError, match="hbp_tamper_detected|hbp_body_invalid|hbp_length"):
        decode_hbp(bytes(blob))


def test_external_json_boundary_and_delta():
    graph, payload = _facts()
    text = to_external_json(payload)
    assert from_external_json(text) == payload
    delta = build_prism_work_delta(
        base_facts=[payload],
        target_facts=[payload],
        base_generation="g1",
        target_generation="g1",
        base_graph_digest=graph["graph_digest"],
        target_graph_digest=graph["graph_digest"],
    )
    assert decode_hbp(encode_hbp(delta)) == delta
    cap = negotiate_capability({"want": "hbp"})
    assert cap["accepted"] is True
    assert payload["schema"] in cap["schemas"]
