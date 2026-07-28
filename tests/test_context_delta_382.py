import pytest
from simplicio_mapper.context_graph_v1 import (
    ContextGraphError, Provenance, apply_delta, batch_events, build_graph,
    context_delta, fact, relation,
)


def p(path):
    return Provenance(path, 1, 2, path.encode().hex().ljust(64, "0")[:64], "parser", "1")


def make(generation, specs, edges=()):
    facts = [fact("repo", generation, kind, key, value, p(f"{key}.py"))
             for kind, key, value in specs]
    by_key = {f["key"]: f for f in facts}
    relations = [relation("repo", generation, kind, by_key[a]["fact_id"],
                          by_key[b]["fact_id"], p("edge.py"))
                 for kind, a, b in edges]
    return build_graph(repo_id="repo", generation=generation, config_hash="c",
                       facts=facts, relations=relations)


def test_create_update_delete_and_apply_equals_full():
    base = make("g1", [("symbol", "a", 1), ("symbol", "gone", 1)])
    target = make("g2", [("symbol", "a", 2), ("test", "new", 1)],
                  [("VERIFIES", "new", "a")])
    delta = context_delta(base, target)
    assert len(delta["created"]) == len(delta["updated"]) == len(delta["deleted"]) == 1
    assert apply_delta(base, delta) == target
    assert delta["affected_relation_ids"]


def test_rename_has_explicit_lineage():
    base = make("g1", [("symbol", "old", 1)])
    target = make("g2", [("symbol", "new", 1)])
    delta = context_delta(base, target, renames={"old": "new"})
    assert delta["renamed"][0]["from_key"] == "old"
    assert not delta["created"] and not delta["deleted"]


def test_wrong_generation_or_hash_rejected():
    base = make("g1", [("symbol", "a", 1)])
    target = make("g2", [("symbol", "a", 2)])
    other = make("gx", [("symbol", "a", 1)])
    with pytest.raises(ContextGraphError) as error:
        apply_delta(other, context_delta(base, target))
    assert error.value.reason_code == "delta_base_mismatch"


def test_event_batch_last_sequence_wins_and_is_deterministic():
    events = [{"key": "b", "sequence": 1, "value": 1},
              {"key": "a", "sequence": 2, "value": 2},
              {"key": "b", "sequence": 3, "value": 3}]
    assert batch_events(events) == [
        {"key": "a", "sequence": 2, "value": 2},
        {"key": "b", "sequence": 3, "value": 3},
    ]


def test_delta_is_deterministic_and_unchanged_content_omitted():
    base = make("g1", [("symbol", "a", 1)])
    target = make("g2", [("symbol", "a", 1)])
    left = context_delta(base, target)
    assert left == context_delta(base, target)
    assert not left["created"] and not left["updated"] and not left["deleted"]
