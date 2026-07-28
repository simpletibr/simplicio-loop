from simplicio_mapper.context_graph_v1 import (
    Provenance, build_graph, fact, impact_query, relation,
)


def graph():
    p = Provenance("src/app.py", 1, 2, "a" * 64, "parser", "1")
    facts = [
        fact("repo", "g1", "symbol", "service", {}, p),
        fact("repo", "g1", "route", "/api", {}, p),
        fact("repo", "g1", "screen", "home", {}, p),
        fact("repo", "g1", "rule", "auth", {}, p),
        fact("repo", "g1", "test", "test_auth", {}, p),
    ]
    edges = [
        relation("repo", "g1", "ROUTES", facts[0]["fact_id"], facts[1]["fact_id"], p),
        relation("repo", "g1", "RENDERS", facts[1]["fact_id"], facts[2]["fact_id"], p),
        relation("repo", "g1", "ENFORCES", facts[2]["fact_id"], facts[3]["fact_id"], p),
        relation("repo", "g1", "VERIFIES", facts[3]["fact_id"], facts[4]["fact_id"], p),
        relation("repo", "g1", "CYCLE", facts[3]["fact_id"], facts[0]["fact_id"], p),
    ]
    return build_graph(repo_id="repo", generation="g1", config_hash="c", facts=facts, relations=edges), facts


def test_symbol_change_returns_cross_layer_test_and_write_set():
    value, facts = graph()
    result = impact_query(value, [facts[0]["fact_id"]], max_depth=10)
    assert result["verification_hints"]["test_fact_ids"] == [facts[4]["fact_id"]]
    assert "src/app.py" in result["write_set_hints"]
    assert any(item["classification"] == "transitive" for item in result["impacted"])


def test_cycles_do_not_loop_and_query_is_deterministic():
    value, facts = graph()
    first = impact_query(value, [facts[0]["fact_id"]], max_depth=20)
    assert first == impact_query(value, [facts[0]["fact_id"]], max_depth=20)
    assert len(first["impacted"]) == 5


def test_budget_truncates_explicitly():
    value, facts = graph()
    result = impact_query(value, [facts[0]["fact_id"]], max_depth=20, max_nodes=2)
    assert result["truncated"] is True and len(result["impacted"]) == 2


def test_reverse_query_finds_upstream_symbol():
    value, facts = graph()
    result = impact_query(value, [facts[4]["fact_id"]], direction="reverse", max_depth=10)
    assert facts[0]["fact_id"] in {item["fact_id"] for item in result["impacted"]}


def test_native_result_never_claims_fallback():
    value, facts = graph()
    result = impact_query(value, [facts[0]["fact_id"]])
    assert result["native_resolution"] is True and result["fallback_reason"] is None
