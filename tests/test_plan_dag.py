from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from simplicio_loop.plan_dag import (
    PlanError, bind_slots, compile_plan, detect_drift, replan,
)


INTENT = {
    "goal": "  finish   issue 809 ",
    "acceptance_criteria": ["tests pass", "DAG valid"],
    "risks": [{"id": "R1", "mitigation": "fail closed"}],
    "non_goals": ["invoke LLM"],
    "oracle": {"command": "pytest"},
}


def node(node_id, **kwargs):
    return {
        "node_id": node_id,
        "logical_task_id": f"task:{node_id}",
        "capability": kwargs.pop("capability", "edit.apply"),
        "tests": kwargs.pop("tests", [f"test:{node_id}"]),
        "acceptance_criteria_refs": kwargs.pop(
            "acceptance_criteria_refs", ["tests pass"]
        ),
        **kwargs,
    }


def compile(nodes):
    return compile_plan(
        plan_id="plan-809", goal_id="goal-809", intent=INTENT, nodes=nodes,
        context_snapshot_id="snapshot-1", context_hash="context-1",
        mapper_generation="mapper-1", evidence_refs=["issue:809"],
    )


def test_valid_dag_infers_io_dependencies_and_is_acyclic():
    plan = compile([
        node("test", inputs=["source"], read_set=["file:src/a.py"]),
        node("edit", outputs=["source"], write_set=["file:src/a.py"]),
    ])
    assert plan["topological_order"] == ["edit", "test"]
    assert plan["nodes"][1]["depends_on"] == ["edit"]
    assert plan["planner"] == "deterministic-python-compiler"
    assert plan["llm_calls_after_compile"] == 0


def test_cycle_fails_closed_with_reason_code():
    with pytest.raises(PlanError) as error:
        compile([
            node("a", depends_on=["b"]),
            node("b", depends_on=["a"]),
        ])
    assert error.value.reason_code == "dag_cycle"


def test_semantic_and_directory_write_collisions_never_share_wave():
    plan = compile([
        node("a", write_set=["symbol:pkg.User.save"]),
        node("b", write_set=["symbol:pkg.User.save"]),
        node("c", write_set=["dir:src/pkg"]),
        node("d", write_set=["file:src/pkg/model.py"]),
        node("safe", write_set=["file:README.md"]),
    ])
    pairs = {(row["left"], row["right"]) for row in plan["conflicts"]}
    assert ("a", "b") in pairs
    assert ("c", "d") in pairs
    for wave in plan["execution_waves"]:
        assert not {"a", "b"}.issubset(wave)
        assert not {"c", "d"}.issubset(wave)


def test_generation_and_context_drift_invalidate_only_affected_descendants():
    plan = compile([
        node("map", context_refs=["mapper:symbol:a"]),
        node("index", generation_sensitive=True),
        node("edit", depends_on=["map"]),
        node("docs", context_refs=["docs:readme"]),
    ])
    drift = detect_drift(
        plan, current_context_hash="context-2", current_generation="mapper-2",
        changed_context_refs=["mapper:symbol:a"], evidence=["mapper:diff:1"],
    )
    assert drift.directly_affected == ("index", "map")
    assert set(drift.invalidated_nodes) == {"index", "map", "edit"}
    assert "docs" not in drift.invalidated_nodes


def test_replan_preserves_history_and_unaffected_node_hash():
    original_nodes = [
        node("edit", context_refs=["src:a"], write_set=["src/a.py"]),
        node("docs", context_refs=["docs:readme"], write_set=["README.md"]),
    ]
    original = compile(original_nodes)
    drift = detect_drift(
        original, current_context_hash="context-2", current_generation="mapper-1",
        changed_context_refs=["src:a"], evidence=["git:sha:new"],
    )
    revised_nodes = [
        node("edit", context_refs=["src:a"], write_set=["src/a.py"], tests=["new"]),
        original_nodes[1],
    ]
    revised = replan(
        original, drift=drift, replacement_nodes=revised_nodes,
        current_context_hash="context-2", current_generation="mapper-1",
    )
    old_hashes = {n["node_id"]: n["node_hash"] for n in original["nodes"]}
    new_hashes = {n["node_id"]: n["node_hash"] for n in revised["nodes"]}
    assert revised["revision"] == 2
    assert revised["history"][0]["plan_hash"] == original["plan_hash"]
    assert old_hashes["docs"] == new_hashes["docs"]
    assert old_hashes["edit"] != new_hashes["edit"]


def test_replan_without_observable_evidence_is_rejected():
    plan = compile([node("a")])
    drift = detect_drift(
        plan, current_context_hash="context-1", current_generation="mapper-1",
        changed_context_refs=[], evidence=[],
    )
    with pytest.raises(PlanError) as error:
        replan(
            plan, drift=drift, replacement_nodes=[node("a")],
            current_context_hash="context-1", current_generation="mapper-1",
        )
    assert error.value.reason_code == "replan_without_observable_cause"


def test_determinism_under_input_permutations_property():
    nodes = [
        node("a", outputs=["a"]),
        node("b", inputs=["a"], outputs=["b"]),
        node("c", inputs=["a"]),
        node("d", inputs=["b"]),
    ]
    expected = compile(nodes)["plan_hash"]
    rng = random.Random(809)
    for _ in range(100):
        shuffled = list(nodes)
        rng.shuffle(shuffled)
        assert compile(shuffled)["plan_hash"] == expected


def test_slots_are_receipts_not_logical_plan_identity():
    plan = compile([node("a"), node("b")])
    receipt = bind_slots(plan, {"a": "slot-7", "b": "device-b/slot-2"})
    assert receipt["logical_tasks_unchanged"] is True
    assert receipt["plan_hash"] == plan["plan_hash"]
    assert all(node["assigned_slot"] is None for node in plan["nodes"])
    assert receipt["receipt_hash"].startswith("sha256:")


def test_slot_receipt_fixture_is_reproducible():
    plan = compile_plan(
        plan_id="plan-fixture", goal_id="goal-fixture",
        intent={
            "goal": "fixture", "acceptance_criteria": ["AC1"],
            "oracle": {"command": "pytest"},
        },
        nodes=[{
            "node_id": "a", "logical_task_id": "task:a",
            "capability": "edit.apply",
        }],
        context_snapshot_id="snapshot-fixture",
        context_hash="context-fixture", mapper_generation="mapper-fixture",
        evidence_refs=["fixture:evidence"],
    )
    receipt = bind_slots(plan, {"a": "slot-1"})
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "plan_dag_receipt.json").read_text()
    )
    assert receipt == fixture
