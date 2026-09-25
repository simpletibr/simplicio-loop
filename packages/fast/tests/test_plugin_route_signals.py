from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio_fast.hbp_codec import seal_receipt
from simplicio_fast.plugin_route_signals import (
    HBP_SCHEMA,
    SIGNALS_SCHEMA,
    PluginRouteRequest,
    PluginRouteSignalsError,
    _digest,
    compile_route_signals,
    contract_manifest,
    decode_hbp,
    encode_hbp,
    measure_route_signals,
    verify_route_signals,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "plugin-route-signals" / "v1"


def _hash(label: str) -> str:
    return (label * 64)[:64]


def _request(**overrides: object) -> PluginRouteRequest:
    payload = {
        "generation": "g1",
        "source_hashes": {"src/app.py": _hash("a")},
        "targets": ["src/app.py"],
        "phase": "pre_route",
        "graph": {
            "nodes": ["src/app.py", "src/cli.py"],
            "edges": [{"from": "src/cli.py", "to": "src/app.py"}],
        },
        "packet_metadata": {"encoded_bytes": 1694},
        "cache_state": {"hits": 3, "misses": 1},
        "diff": None,
        "previous_promotion": None,
    }
    payload.update(overrides)
    return PluginRouteRequest(**payload)  # type: ignore[arg-type]


def test_single_file_fan_in_one_is_evidence_not_decision() -> None:
    packet = compile_route_signals(_request())
    assert packet["schema"] == SIGNALS_SCHEMA
    assert packet["signals"]["file_count"]["value"] == 1
    assert packet["signals"]["fan_in"]["value"] == 1
    assert packet["signals"]["fan_in"]["kind"] == "measured"
    assert packet["decision"] is None
    assert packet["decision_null_reason"] == "FAST_NOT_POLICY_AUTHORITY"
    assert packet["route"] is None
    assert packet["skills"] is None
    assert packet["savings"] is None
    assert packet["promotion_evidence"]["decides_policy"] is False
    assert packet["promotion_evidence"]["rank"] == "fast_path_candidate"


def test_hub_sensitive_vague_and_missing_map() -> None:
    hub_edges = [{"from": f"src/dep_{index}.py", "to": "src/app.py"} for index in range(8)]
    hub = compile_route_signals(
        _request(
            graph={
                "nodes": ["src/app.py", *[f"src/dep_{index}.py" for index in range(8)]],
                "edges": hub_edges,
            }
        )
    )
    assert hub["signals"]["hub"]["value"] == 8
    assert hub["promotion_evidence"]["rank"] == "review_recommended"
    sensitive = compile_route_signals(
        _request(
            targets=["src/auth.py"],
            source_hashes={"src/auth.py": _hash("s")},
            graph={"nodes": ["src/auth.py"], "edges": []},
        )
    )
    assert sensitive["signals"]["sensitive"]["value"] == 1
    assert sensitive["promotion_evidence"]["rank"] == "full_path_recommended"
    vague = compile_route_signals(_request(targets=["src/*"], graph=None))
    assert vague["signals"]["file_count"]["kind"] == "unknown"
    assert vague["signals"]["file_count"]["value"] is None
    assert vague["signals"]["file_count"]["unknown_reason"] == "targets_vague"
    missing = compile_route_signals(
        _request(targets=["src/app.py", "src/cli.py"], graph=None)
    )
    assert missing["signals"]["fan_in"]["kind"] == "unknown"
    assert missing["signals"]["fan_in"]["value"] is None
    assert "missing_map" in missing["promotion_evidence"]["reasons"]


def test_diff_overshoot_and_monotonic_escalation() -> None:
    pre = compile_route_signals(_request())
    assert pre["promotion_evidence"]["rank"] == "fast_path_candidate"
    overshoot = compile_route_signals(
        _request(
            phase="post_diff",
            diff={"bytes": 5000},
            packet_metadata={"encoded_bytes": 100},
            previous_promotion=pre["promotion_evidence"]["rank"],
        )
    )
    assert overshoot["signals"]["diff_size"]["value"] == 5000
    assert overshoot["promotion_evidence"]["rank"] == "full_path_recommended"
    assert "diff_overshoot" in overshoot["promotion_evidence"]["reasons"]
    held = compile_route_signals(
        _request(
            phase="post_diff",
            diff={"bytes": 10},
            previous_promotion="full_path_recommended",
        )
    )
    assert held["promotion_evidence"]["rank"] == "full_path_recommended"
    assert "monotonic_hold" in held["promotion_evidence"]["reasons"]
    assert held["promotion_evidence"]["monotonic"] is True


def test_cache_hit_miss_and_locality() -> None:
    warm = compile_route_signals(_request(cache_state={"hits": 9, "misses": 1}))
    assert warm["signals"]["cache_locality"]["kind"] == "measured"
    assert warm["signals"]["cache_locality"]["value"] == pytest.approx(0.9)
    missing = compile_route_signals(_request(cache_state=None))
    assert missing["signals"]["cache_locality"]["value"] is None
    assert missing["signals"]["cache_locality"]["unknown_reason"] == "cache_state_missing"
    empty = compile_route_signals(_request(cache_state={"hits": 0, "misses": 0}))
    assert empty["signals"]["cache_locality"]["value"] is None
    assert empty["signals"]["cache_locality"]["unknown_reason"] == "cache_empty"


def test_unknown_fields_never_become_zero() -> None:
    packet = compile_route_signals(
        _request(
            targets=[],
            graph=None,
            packet_metadata=None,
            cache_state=None,
            diff=None,
        )
    )
    for name in ("file_count", "fan_in", "fan_out", "hub", "sensitive", "diff_size", "cache_locality", "packet_bytes"):
        signal = packet["signals"][name]
        assert signal["kind"] == "unknown"
        assert signal["value"] is None
        assert signal["unknown_reason"]
        assert signal["value"] != 0
    verify_route_signals(packet)


def test_determinism_across_runs() -> None:
    first = compile_route_signals(_request())
    second = compile_route_signals(_request())
    assert first["signals_hash"] == second["signals_hash"]
    assert encode_hbp(first) == encode_hbp(second)


def test_python_hbp_parity_and_golden_vectors() -> None:
    packet = compile_route_signals(_request())
    decoded = decode_hbp(encode_hbp(packet))
    assert decoded["signals_hash"] == packet["signals_hash"]
    golden = json.loads((CONTRACT / "golden-vectors.json").read_text(encoding="utf-8"))
    assert packet["signals_hash"] == golden["vectors"]["signals_hash"]
    assert encode_hbp(packet) == golden["vectors"]["hbp_row"]
    fixture = json.loads((CONTRACT / "runtime-r05-loop-l01.json").read_text(encoding="utf-8"))
    verify_route_signals(fixture)
    assert fixture["decision"] is None
    assert fixture["consumers"] == ["runtime-r05", "loop-l01"]


def test_adversarial_path_and_large_graph_fail_closed_or_bound() -> None:
    with pytest.raises(PluginRouteSignalsError, match="path_escape"):
        compile_route_signals(_request(targets=["../secret"]))
    with pytest.raises(PluginRouteSignalsError, match="path_escape"):
        compile_route_signals(
            _request(graph={"nodes": ["src/app.py", "../outside"], "edges": []})
        )
    with pytest.raises(PluginRouteSignalsError, match="path_escape"):
        PluginRouteRequest(
            generation="g1",
            source_hashes={"C:/Windows/system32": _hash("x")},
            targets=["src/app.py"],
        )
    nodes = [f"src/n{index}.py" for index in range(20)]
    edges = [{"from": nodes[0], "to": node} for node in nodes[1:]]
    bounded = compile_route_signals(
        _request(
            targets=[nodes[0]],
            source_hashes={nodes[0]: _hash("n")},
            graph={"nodes": nodes, "edges": edges, "truncated": True},
        )
    )
    assert bounded["signals"]["fan_out"]["kind"] == "bounded_estimate"
    assert bounded["graph_truncated"] is True


def test_latency_rss_and_throughput_are_raw() -> None:
    report = measure_route_signals(_request(), iterations=21, batch_size=8)
    assert report["iterations"] == 21
    assert report["cold_ns"] > 0
    assert report["warm_p95_ns"] >= report["warm_p50_ns"]
    assert report["batch_ns"] > 0
    assert report["throughput_per_s"] is None or report["throughput_per_s"] > 0
    assert len(report["raw_warm_ns"]) == 21
    assert report["tokens"] is None
    assert report["tokens_null_reason"] == "NO_LLM_USED"
    if report["rss_kib"] is None:
        assert report["rss_kib_null_reason"] == "RSS_UNAVAILABLE"


def test_manifest_and_verification_fail_closed() -> None:
    manifest = contract_manifest()
    assert manifest["decides_policy"] is False
    assert manifest["fabricates_savings"] is False
    packet = compile_route_signals(_request())
    unsigned = dict(packet)
    unsigned.pop("signals_hash")
    unsigned["decision"] = "allow"
    forged = dict(unsigned)
    forged["signals_hash"] = _digest(unsigned)
    with pytest.raises(PluginRouteSignalsError, match="policy_decision_forbidden"):
        verify_route_signals(forged)
    with pytest.raises(PluginRouteSignalsError, match="signals_corrupt"):
        verify_route_signals(packet | {"signals_hash": "0" * 64})
    with pytest.raises(PluginRouteSignalsError, match="phase_invalid"):
        _request(phase="decide")
    with pytest.raises(PluginRouteSignalsError, match="signals_schema_invalid"):
        decode_hbp(seal_receipt("schema=other|kind=signals|digest=x|payload=e30="))
    assert HBP_SCHEMA in encode_hbp(packet)
    unsigned = dict(packet)
    unsigned.pop("signals_hash")
    unsigned["savings"] = 12.5
    savings = dict(unsigned)
    savings["signals_hash"] = _digest(unsigned)
    with pytest.raises(PluginRouteSignalsError, match="savings_fabricated"):
        verify_route_signals(savings)
    with pytest.raises(PluginRouteSignalsError, match="graph_invalid"):
        compile_route_signals(_request(graph="nope"))
    with pytest.raises(PluginRouteSignalsError, match="cache_state_invalid"):
        compile_route_signals(_request(cache_state={"hits": -1, "misses": 0}))
    with pytest.raises(PluginRouteSignalsError, match="diff_invalid"):
        compile_route_signals(_request(diff={"bytes": -3}))
    lines = compile_route_signals(_request(phase="post_diff", diff={"added_lines": 4, "removed_lines": 1}))
    assert lines["signals"]["diff_size"]["value"] == 5
    with pytest.raises(PluginRouteSignalsError, match="benchmark_invalid"):
        measure_route_signals(_request(), iterations=0)
