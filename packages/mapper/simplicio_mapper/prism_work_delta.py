"""PrismWorkDelta/v1 — incremental invalidation for PrismTaskFacts conflict graphs.

Mapper reports which facts/conflicts changed. Loop decides pause/replan.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .prism_task_facts import TASK_FACTS_SCHEMA, PrismFactsError, validate_prism_task_facts

WORK_DELTA_SCHEMA = "simplicio.prism-work-delta/v1"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _index_facts(items: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        validated = validate_prism_task_facts(item)
        out[validated["task_id"]] = validated
    return out


def _conflict_map(facts: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = list(facts.get("hard_conflict_candidates", [])) + list(facts.get("soft_conflict_candidates", []))
    return {row["conflict_id"]: row for row in rows}


def build_prism_work_delta(
    *,
    base_facts: Sequence[Mapping[str, Any]],
    target_facts: Sequence[Mapping[str, Any]],
    base_generation: str,
    target_generation: str,
    base_graph_digest: str,
    target_graph_digest: str,
    change_kinds: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Diff two PrismTaskFacts generations into a deterministic work delta."""
    if not base_generation or not target_generation:
        raise PrismFactsError("generation_invalid", f"{base_generation}->{target_generation}")
    if not base_graph_digest or not target_graph_digest:
        raise PrismFactsError("graph_digest_invalid", "")

    base = _index_facts(base_facts)
    target = _index_facts(target_facts)
    created_tasks: list[dict[str, Any]] = []
    updated_tasks: list[dict[str, Any]] = []
    deleted_tasks: list[dict[str, Any]] = []
    created_conflicts: list[dict[str, Any]] = []
    updated_conflicts: list[dict[str, Any]] = []
    deleted_conflicts: list[dict[str, Any]] = []
    invalidations: list[dict[str, Any]] = []

    for task_id in sorted(set(base) | set(target)):
        if task_id not in base:
            created_tasks.append({"task_id": task_id, "facts_digest": target[task_id]["facts_digest"]})
            invalidations.append(
                {
                    "task_id": task_id,
                    "scope": "task",
                    "reason_code": "TASK_CREATED",
                    "evidence_refs": [target[task_id]["facts_digest"]],
                    "requires_replan": True,
                }
            )
            continue
        if task_id not in target:
            deleted_tasks.append({"task_id": task_id, "facts_digest": base[task_id]["facts_digest"]})
            invalidations.append(
                {
                    "task_id": task_id,
                    "scope": "task",
                    "reason_code": "TASK_DELETED",
                    "evidence_refs": [base[task_id]["facts_digest"]],
                    "requires_replan": True,
                }
            )
            continue
        if base[task_id]["facts_digest"] != target[task_id]["facts_digest"]:
            updated_tasks.append(
                {
                    "task_id": task_id,
                    "base_facts_digest": base[task_id]["facts_digest"],
                    "target_facts_digest": target[task_id]["facts_digest"],
                }
            )
            invalidations.append(
                {
                    "task_id": task_id,
                    "scope": "facts",
                    "reason_code": "FACTS_DIGEST_CHANGED",
                    "evidence_refs": [base[task_id]["facts_digest"], target[task_id]["facts_digest"]],
                    "requires_replan": True,
                }
            )
        b_conf = _conflict_map(base[task_id])
        t_conf = _conflict_map(target[task_id])
        for cid in sorted(set(b_conf) | set(t_conf)):
            if cid not in b_conf:
                created_conflicts.append(t_conf[cid])
            elif cid not in t_conf:
                deleted_conflicts.append(b_conf[cid])
            elif b_conf[cid] != t_conf[cid]:
                updated_conflicts.append(
                    {
                        "conflict_id": cid,
                        "base": b_conf[cid],
                        "target": t_conf[cid],
                    }
                )

    affected = sorted({item["task_id"] for item in invalidations})
    kinds = sorted(set(change_kinds or ("source",)))
    safe_to_reuse = (
        not affected
        and base_graph_digest == target_graph_digest
        and not created_tasks
        and not deleted_tasks
        and not updated_tasks
    )

    body = {
        "schema": WORK_DELTA_SCHEMA,
        "base_generation": base_generation,
        "target_generation": target_generation,
        "base_graph_digest": base_graph_digest,
        "target_graph_digest": target_graph_digest,
        "base_task_facts_digest": _sha([base[k]["facts_digest"] for k in sorted(base)]),
        "target_task_facts_digest": _sha([target[k]["facts_digest"] for k in sorted(target)]),
        "created_task_facts": created_tasks,
        "updated_task_facts": updated_tasks,
        "deleted_task_facts": deleted_tasks,
        "created_conflict_candidates": sorted(created_conflicts, key=lambda item: item["conflict_id"]),
        "updated_conflict_candidates": sorted(updated_conflicts, key=lambda item: item["conflict_id"]),
        "deleted_conflict_candidates": sorted(deleted_conflicts, key=lambda item: item["conflict_id"]),
        "affected_task_ids": affected,
        "invalidations": sorted(invalidations, key=lambda item: (item["task_id"], item["reason_code"])),
        "change_kinds": kinds,
        # Fact only — never mutation authority.
        "safe_to_reuse_context": safe_to_reuse,
        "safe_to_reuse_context_null_reason": None if safe_to_reuse else "INVALIDATED_FACTS",
        "authority": None,
        "authority_null_reason": "DELTA_IS_FACT_NOT_AUTHORITY",
        "lineage": {
            "task_facts_schema": TASK_FACTS_SCHEMA,
            "producer": "simplicio-mapper",
            "consumer": "simplicio-loop",
        },
    }
    body["delta_digest"] = _sha(body)
    body["encoded_bytes"] = len(_canonical(body))
    return body


def validate_prism_work_delta(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != WORK_DELTA_SCHEMA:
        raise PrismFactsError("schema_invalid", str(payload.get("schema")))
    unsigned = {k: v for k, v in payload.items() if k not in {"delta_digest", "encoded_bytes"}}
    if payload.get("delta_digest") != _sha(unsigned):
        raise PrismFactsError("digest_mismatch", str(payload.get("delta_digest")))
    return dict(payload)


__all__ = [
    "WORK_DELTA_SCHEMA",
    "build_prism_work_delta",
    "validate_prism_work_delta",
]
