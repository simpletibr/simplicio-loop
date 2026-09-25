from __future__ import annotations

from simplicio_mapper.context_graph_v1 import Provenance, build_graph, fact, relation
from simplicio_mapper.prism_task_facts import build_prism_task_facts
from simplicio_mapper.prism_work_delta import WORK_DELTA_SCHEMA, build_prism_work_delta, validate_prism_work_delta


def _graph(generation: str = "g1"):
    p = Provenance("src/app.py", 1, 2, "a" * 64, "parser", "1")
    facts = [fact("repo", generation, "symbol", "Service", {}, p)]
    edges = []
    return build_graph(repo_id="repo", generation=generation, config_hash="c", facts=facts, relations=edges), facts


def test_delta_detects_fact_change_and_safe_reuse_false():
    g1, f1 = _graph("g1")
    g2, f2 = _graph("g2")
    base = [
        build_prism_task_facts(
            g1,
            task_id="T1",
            declared_write_set=["src/app.py"],
            seed_fact_ids=[f1[0]["fact_id"]],
        )
    ]
    target = [
        build_prism_task_facts(
            g2,
            task_id="T1",
            declared_write_set=["src/app.py", "src/other.py"],
            seed_fact_ids=[f2[0]["fact_id"]],
        )
    ]
    delta = build_prism_work_delta(
        base_facts=base,
        target_facts=target,
        base_generation="g1",
        target_generation="g2",
        base_graph_digest=g1["graph_digest"],
        target_graph_digest=g2["graph_digest"],
        change_kinds=["source", "task_text"],
    )
    assert delta["schema"] == WORK_DELTA_SCHEMA
    assert delta["safe_to_reuse_context"] is False
    assert delta["authority"] is None
    assert "T1" in delta["affected_task_ids"]
    assert validate_prism_work_delta(delta)["delta_digest"] == delta["delta_digest"]


def test_identical_generations_are_safe_to_reuse():
    g1, f1 = _graph("g1")
    facts = [
        build_prism_task_facts(
            g1,
            task_id="T1",
            declared_write_set=["src/app.py"],
            seed_fact_ids=[f1[0]["fact_id"]],
        )
    ]
    delta = build_prism_work_delta(
        base_facts=facts,
        target_facts=facts,
        base_generation="g1",
        target_generation="g1",
        base_graph_digest=g1["graph_digest"],
        target_graph_digest=g1["graph_digest"],
    )
    assert delta["safe_to_reuse_context"] is True
    assert delta["affected_task_ids"] == []
