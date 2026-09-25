from __future__ import annotations

from simplicio_mapper.context_graph_v1 import Provenance, build_graph, fact, relation
from simplicio_mapper.prism_task_facts import (
    TASK_FACTS_SCHEMA,
    build_prism_task_facts,
    project_task_batch,
    validate_prism_task_facts,
)


def _graph():
    p = Provenance("src/app.py", 1, 2, "a" * 64, "parser", "1")
    pt = Provenance("tests/test_app.py", 1, 2, "b" * 64, "parser", "1")
    facts = [
        fact("repo", "g1", "symbol", "Service", {"name": "Service"}, p),
        fact("repo", "g1", "route", "/api", {}, p),
        fact("repo", "g1", "test", "test_service", {}, pt),
    ]
    edges = [
        relation("repo", "g1", "ROUTES", facts[0]["fact_id"], facts[1]["fact_id"], p),
        relation("repo", "g1", "VERIFIES", facts[0]["fact_id"], facts[2]["fact_id"], p),
    ]
    graph = build_graph(repo_id="repo", generation="g1", config_hash="c", facts=facts, relations=edges)
    return graph, facts


def test_prism_task_facts_deterministic_and_namespaces():
    graph, facts = _graph()
    first = build_prism_task_facts(
        graph,
        task_id="T1",
        task_text="Update Service in src/app.py and tests/test_app.py",
        declared_write_set=["src/app.py"],
        declared_dependencies=["T0"],
        seed_fact_ids=[facts[0]["fact_id"]],
    )
    second = build_prism_task_facts(
        graph,
        task_id="T1",
        task_text="Update Service in src/app.py and tests/test_app.py",
        declared_write_set=["src/app.py"],
        declared_dependencies=["T0"],
        seed_fact_ids=[facts[0]["fact_id"]],
    )
    assert first == second
    assert first["schema"] == TASK_FACTS_SCHEMA
    assert first["write_set_declared"] == ["src/app.py"]
    assert first["authority"] if False else first.get("authority") is None  # no authority field on body
    assert all(h.get("source") in {"measured", "declared", "inferred"} for h in first["write_set_hints"])
    assert first["dependency_hints"][0]["value"] == "T0"
    assert validate_prism_task_facts(first)["facts_digest"] == first["facts_digest"]


def test_batch_order_independent():
    graph, facts = _graph()
    a = {"task_id": "T2", "task_text": "src/app.py", "seed_fact_ids": [facts[0]["fact_id"]]}
    b = {"task_id": "T1", "task_text": "src/app.py", "seed_fact_ids": [facts[0]["fact_id"]]}
    left = project_task_batch(graph, [a, b])
    right = project_task_batch(graph, [b, a])
    assert [item["task_id"] for item in left] == ["T1", "T2"]
    assert left == right


def test_abstention_without_seeds():
    graph, _facts = _graph()
    payload = build_prism_task_facts(graph, task_id="T9", task_text="vague work")
    assert payload["abstained"] is True
    assert payload["reason_code"]
