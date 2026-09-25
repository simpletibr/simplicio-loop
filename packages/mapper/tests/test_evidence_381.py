from simplicio_mapper.context_graph_v1 import (
    ContextGraphError, Provenance, build_graph, evaluate_evidence, fact
)


def graph(count=2):
    return build_graph(repo_id="repo", generation="g3", config_hash="c", facts=[
        fact("repo", "g3", "symbol", f"s{i}", {"name": f"s{i}"},
             Provenance(f"a{i}.py", 1, 2, f"{i:064x}", "parser", "1"))
        for i in range(count)
    ], relations=[])


def test_measured_evidence_can_be_sufficient():
    g = graph()
    kinds = {f["fact_id"]: "measured" for f in g["facts"]}
    scores = {f["fact_id"]: .95 for f in g["facts"]}
    receipt = evaluate_evidence(g, risk="high", evidence_kinds=kinds, measured_scores=scores)
    assert receipt["verdict"] == "sufficient"
    assert receipt["confidence"] == .95


def test_inferred_and_asserted_are_capped():
    g = graph()
    ids = [f["fact_id"] for f in g["facts"]]
    receipt = evaluate_evidence(
        g, risk="medium",
        evidence_kinds={ids[0]: "inferred", ids[1]: "asserted"},
        measured_scores={ids[0]: 1, ids[1]: 1},
    )
    assert [row["score"] for row in receipt["facts"]] == [.75, .5]
    assert receipt["verdict"] == "partial"


def test_missing_measurement_is_null_and_explained():
    g = graph(1)
    fid = g["facts"][0]["fact_id"]
    receipt = evaluate_evidence(g, evidence_kinds={fid: "measured"})
    assert receipt["confidence"] is None
    assert receipt["verdict"] == "abstain"
    assert receipt["explain"]["excluded"] == [
        {"fact_id": fid, "reason": "MEASUREMENT_UNAVAILABLE"}
    ]


def test_empty_graph_abstains_not_success():
    receipt = evaluate_evidence(
        build_graph(repo_id="repo", generation="g1", config_hash="c",
                    facts=[], relations=[]),
        risk="low",
    )
    assert receipt["verdict"] == "abstain"
    assert receipt["coverage"] == 0


def test_threshold_and_receipt_are_deterministic():
    g = graph()
    assert evaluate_evidence(g, threshold=.4) == evaluate_evidence(g, threshold=.4)
    try:
        evaluate_evidence(g, risk="critical")
    except ContextGraphError as exc:
        assert exc.reason_code == "evidence_risk_invalid"
    else:
        raise AssertionError("invalid risk accepted")
