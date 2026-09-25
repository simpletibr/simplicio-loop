from __future__ import annotations

from scripts.mapper_perf_gate import build_evidence, compare


def test_evidence_has_percentiles_and_explicit_unavailable_metrics(tmp_path) -> None:
    evidence = build_evidence(root=tmp_path, corpus={"id": "tiny", "sha": "c"}, profile="sync",
                              phase="cold", samples=[{"wall_ms": 10}, {"wall_ms": 12}, {"wall_ms": 14}],
                              fingerprint={"commit": "abc", "machine": "m1"})
    assert evidence["metrics"]["wall_ms"]["p50"] == 12
    assert evidence["optional_metrics"]["peak_rss_bytes"] is None
    assert evidence["evidence_hash"].startswith("sha256:")


def test_gate_rejects_fingerprint_mismatch_and_p95_regression(tmp_path) -> None:
    baseline = build_evidence(root=tmp_path, corpus={"id": "tiny"}, profile="sync", phase="warm",
                              samples=[{"wall_ms": 10}] * 10, fingerprint={"commit": "a", "machine": "m"})
    candidate = build_evidence(root=tmp_path, corpus={"id": "tiny"}, profile="sync", phase="warm",
                               samples=[{"wall_ms": 12}] * 10, fingerprint={"commit": "a", "machine": "m"})
    report = compare(baseline, candidate, p50_limit=0.05, p95_limit=0.10)
    assert report["status"] == "fail"
    mismatch = dict(candidate, fingerprint={"commit": "b", "machine": "m"})
    assert compare(baseline, mismatch)["compatible"] is False
