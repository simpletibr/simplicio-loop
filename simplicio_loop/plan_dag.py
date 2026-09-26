"""Deterministic PlanDAG compilation, conflict analysis and selective replan."""
from __future__ import annotations

import hashlib
import json
import posixpath
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

PLAN_SCHEMA = "simplicio.plan-dag/v1"
RECEIPT_SCHEMA = "simplicio.plan-dag-receipt/v1"


class PlanError(ValueError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode()).hexdigest()


def _strings(values: Iterable[Any]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


def _target(value: str) -> str:
    raw = str(value).strip().replace("\\", "/")
    kind, separator, name = raw.partition(":")
    if separator and kind in {"file", "dir", "symbol", "config", "db", "api"}:
        if kind in {"file", "dir"}:
            name = posixpath.normpath("/" + name).lstrip("/")
        return f"{kind}:{name}"
    return "file:" + posixpath.normpath("/" + raw).lstrip("/")


def targets_conflict(left: str, right: str) -> bool:
    """Exact semantic ownership or explicit directory ancestry conflicts."""
    left, right = _target(left), _target(right)
    if left == right:
        return True
    lkind, lname = left.split(":", 1)
    rkind, rname = right.split(":", 1)
    if lkind == "dir" and rkind == "file":
        return rname == lname or rname.startswith(lname.rstrip("/") + "/")
    if rkind == "dir" and lkind == "file":
        return lname == rname or lname.startswith(rname.rstrip("/") + "/")
    return False


@dataclass(frozen=True)
class DriftResult:
    reason_code: str | None
    directly_affected: tuple[str, ...]
    invalidated_nodes: tuple[str, ...]
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "directly_affected": list(self.directly_affected),
            "invalidated_nodes": list(self.invalidated_nodes),
            "evidence": list(self.evidence),
        }


def _normalize_intent(intent: Mapping[str, Any]) -> dict[str, Any]:
    goal = " ".join(str(intent.get("goal") or "").split())
    acceptance = _strings(intent.get("acceptance_criteria") or ())
    oracle = dict(intent.get("oracle") or {})
    if not goal:
        raise PlanError("goal_missing")
    if not acceptance:
        raise PlanError("acceptance_criteria_missing")
    if not oracle:
        raise PlanError("oracle_missing")
    return {
        "goal": goal,
        "acceptance_criteria": acceptance,
        "risks": sorted(
            [dict(row) for row in intent.get("risks") or ()],
            key=lambda row: _canonical(row),
        ),
        "non_goals": _strings(intent.get("non_goals") or ()),
        "oracle": oracle,
    }


def _normalize_node(raw: Mapping[str, Any]) -> dict[str, Any]:
    node_id = str(raw.get("node_id") or "").strip()
    logical_task_id = str(raw.get("logical_task_id") or node_id).strip()
    capability = str(raw.get("capability") or "").strip()
    if not node_id or not logical_task_id or not capability:
        raise PlanError("node_identity_missing", node_id)
    node = {
        "node_id": node_id,
        "logical_task_id": logical_task_id,
        "capability": capability,
        "inputs": _strings(raw.get("inputs") or ()),
        "outputs": _strings(raw.get("outputs") or ()),
        "depends_on": _strings(raw.get("depends_on") or ()),
        "read_set": _strings(_target(v) for v in raw.get("read_set") or ()),
        "write_set": _strings(_target(v) for v in raw.get("write_set") or ()),
        "context_refs": _strings(raw.get("context_refs") or ()),
        "tests": _strings(raw.get("tests") or ()),
        "acceptance_criteria_refs": _strings(
            raw.get("acceptance_criteria_refs") or ()
        ),
        "generation_sensitive": bool(raw.get("generation_sensitive", False)),
        "risk": str(raw.get("risk") or "medium"),
        "rollback_strategy": str(raw.get("rollback_strategy") or "revert"),
        # Slots are execution resources, never logical task identity.
        "assigned_slot": None,
    }
    node["node_hash"] = _hash(node)
    return node


def _topological(nodes: Mapping[str, Mapping[str, Any]]) -> list[str]:
    indegree = {node_id: 0 for node_id in nodes}
    followers = {node_id: [] for node_id in nodes}
    for node_id, node in nodes.items():
        for dependency in node["depends_on"]:
            if dependency not in nodes:
                raise PlanError("dependency_missing", f"{node_id}->{dependency}")
            indegree[node_id] += 1
            followers[dependency].append(node_id)
    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    ordered: list[str] = []
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for follower in sorted(followers[current]):
            indegree[follower] -= 1
            if indegree[follower] == 0:
                ready.append(follower)
                ready.sort()
    if len(ordered) != len(nodes):
        cycle_nodes = sorted(node_id for node_id, degree in indegree.items() if degree)
        raise PlanError("dag_cycle", ",".join(cycle_nodes))
    return ordered


def _conflicts(nodes: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    ids = sorted(nodes)
    for index, left_id in enumerate(ids):
        for right_id in ids[index + 1 :]:
            collisions = sorted(
                {
                    f"{left}|{right}"
                    for left in nodes[left_id]["write_set"]
                    for right in nodes[right_id]["write_set"]
                    if targets_conflict(left, right)
                }
            )
            if collisions:
                result.append(
                    {
                        "left": left_id,
                        "right": right_id,
                        "reason_code": "write_set_conflict",
                        "targets": collisions,
                    }
                )
    return result


def _waves(
    nodes: Mapping[str, Mapping[str, Any]],
    ordered: Sequence[str],
    conflicts: Sequence[Mapping[str, Any]],
) -> list[list[str]]:
    conflict_pairs = {
        frozenset((row["left"], row["right"])) for row in conflicts
    }
    wave_of: dict[str, int] = {}
    waves: list[list[str]] = []
    for node_id in ordered:
        earliest = (
            max((wave_of[parent] + 1 for parent in nodes[node_id]["depends_on"]), default=0)
        )
        wave = earliest
        while True:
            if wave == len(waves):
                waves.append([])
            if all(
                frozenset((node_id, peer)) not in conflict_pairs
                for peer in waves[wave]
            ):
                waves[wave].append(node_id)
                wave_of[node_id] = wave
                break
            wave += 1
    return [sorted(wave) for wave in waves if wave]


def compile_plan(
    *,
    plan_id: str,
    goal_id: str,
    intent: Mapping[str, Any],
    nodes: Sequence[Mapping[str, Any]],
    context_snapshot_id: str,
    context_hash: str,
    mapper_generation: str,
    evidence_refs: Sequence[str],
    revision: int = 1,
    history: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    normalized_intent = _normalize_intent(intent)
    if not context_snapshot_id or not context_hash or not mapper_generation:
        raise PlanError("pinned_context_missing")
    if not evidence_refs:
        raise PlanError("planning_evidence_missing")
    normalized = [_normalize_node(node) for node in nodes]
    by_id = {node["node_id"]: node for node in normalized}
    if len(by_id) != len(normalized) or not by_id:
        raise PlanError("node_id_duplicate_or_empty")

    # Infer producer -> consumer dependencies from stable I/O handles.
    producers: dict[str, list[str]] = {}
    for node in normalized:
        for output in node["outputs"]:
            producers.setdefault(output, []).append(node["node_id"])
    for node in normalized:
        inferred = {
            producer
            for input_name in node["inputs"]
            for producer in producers.get(input_name, ())
            if producer != node["node_id"]
        }
        node["depends_on"] = sorted(set(node["depends_on"]) | inferred)
        node["node_hash"] = _hash(
            {key: value for key, value in node.items() if key != "node_hash"}
        )

    ordered = _topological(by_id)
    conflicts = _conflicts(by_id)
    waves = _waves(by_id, ordered, conflicts)
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "plan_id": str(plan_id),
        "goal_id": str(goal_id),
        "revision": int(revision),
        "intent": normalized_intent,
        "context_snapshot_id": str(context_snapshot_id),
        "context_hash": str(context_hash),
        "mapper_generation": str(mapper_generation),
        "evidence_refs": _strings(evidence_refs),
        "nodes": [by_id[node_id] for node_id in sorted(by_id)],
        "topological_order": ordered,
        "conflicts": conflicts,
        "execution_waves": waves,
        "history": [dict(item) for item in history],
        "planner": "deterministic-python-compiler",
        "llm_calls_after_compile": 0,
    }
    plan["plan_hash"] = _hash(plan)
    return plan


def detect_drift(
    plan: Mapping[str, Any],
    *,
    current_context_hash: str,
    current_generation: str,
    changed_context_refs: Sequence[str],
    evidence: Sequence[str],
) -> DriftResult:
    changed = set(_strings(changed_context_refs))
    nodes = {node["node_id"]: node for node in plan["nodes"]}
    direct = {
        node_id
        for node_id, node in nodes.items()
        if changed.intersection(node["context_refs"])
    }
    if current_generation != plan["mapper_generation"]:
        direct.update(
            node_id
            for node_id, node in nodes.items()
            if node.get("generation_sensitive")
        )
    reason = None
    if current_context_hash != plan["context_hash"] or direct:
        reason = "observable_context_drift"
    if current_generation != plan["mapper_generation"]:
        reason = "observable_generation_drift"
    invalidated = set(direct)
    progressed = True
    while progressed:
        progressed = False
        for node_id, node in nodes.items():
            if node_id not in invalidated and invalidated.intersection(node["depends_on"]):
                invalidated.add(node_id)
                progressed = True
    return DriftResult(
        reason,
        tuple(sorted(direct)),
        tuple(node_id for node_id in plan["topological_order"] if node_id in invalidated),
        tuple(_strings(evidence)),
    )


def replan(
    previous: Mapping[str, Any],
    *,
    drift: DriftResult,
    replacement_nodes: Sequence[Mapping[str, Any]],
    current_context_hash: str,
    current_generation: str,
) -> dict[str, Any]:
    if drift.reason_code is None or not drift.evidence:
        raise PlanError("replan_without_observable_cause")
    history = list(previous.get("history") or ())
    history.append(
        {
            "revision": previous["revision"],
            "plan_hash": previous["plan_hash"],
            "reason_code": drift.reason_code,
            "invalidated_nodes": list(drift.invalidated_nodes),
            "evidence": list(drift.evidence),
        }
    )
    return compile_plan(
        plan_id=previous["plan_id"],
        goal_id=previous["goal_id"],
        intent=previous["intent"],
        nodes=replacement_nodes,
        context_snapshot_id=previous["context_snapshot_id"],
        context_hash=current_context_hash,
        mapper_generation=current_generation,
        evidence_refs=previous["evidence_refs"],
        revision=int(previous["revision"]) + 1,
        history=history,
    )


def bind_slots(
    plan: Mapping[str, Any], assignments: Mapping[str, str]
) -> dict[str, Any]:
    unknown = sorted(set(assignments) - {node["node_id"] for node in plan["nodes"]})
    if unknown:
        raise PlanError("slot_assignment_unknown_node", ",".join(unknown))
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "event": "slots_bound",
        "plan_id": plan["plan_id"],
        "plan_revision": plan["revision"],
        "plan_hash": plan["plan_hash"],
        "assignments": {
            node_id: str(assignments[node_id]) for node_id in sorted(assignments)
        },
        "logical_tasks_unchanged": True,
    }
    receipt["receipt_hash"] = _hash(receipt)
    return receipt
