"""Backward-compatible task-aware selection powered by the retrieval engine."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from typing import Any

from .retrieval_index import (
    DEFAULT_TOKEN_BUDGET,
    TOKENIZER_POLICY,
    estimate_tokens,
    serialized_json_bytes,
    serialized_token_count,
)
from .retrieval_index import (
    select_context_targets as _select_context_targets,
)
from .retrieval_index import (
    task_query_fingerprint as _task_query_fingerprint,
)
from .retrieval_index import (
    task_query_terms as _task_query_terms,
)
from .task_intent import build_task_query_plan, extract_task_context_settings


def task_query_terms(goal: str = "", task_intent: Mapping[str, Any] | None = None) -> list[str]:
    return _task_query_terms(goal, task_intent)


def task_query_fingerprint(
    *,
    goal: str = "",
    task_intent: Mapping[str, Any] | None = None,
    task_fingerprint: str = "",
    target: str = "",
    query_terms: list[str] | None = None,
) -> str:
    return _task_query_fingerprint(
        goal=goal,
        task_intent=task_intent,
        task_fingerprint=task_fingerprint,
        target=target,
        query_terms=query_terms,
    )


def select_context_targets(
    root: str,
    project_map: Mapping[str, Any],
    *,
    goal: str = "",
    task_intent: Mapping[str, Any] | None = None,
    task_fingerprint: str = "",
    target: str = "",
    limit: int = 8,
    symbol_index: Mapping[str, Any] | None = None,
    call_graph: Mapping[str, Any] | None = None,
    recent_paths: set[str] | None = None,
    token_budget: int | None = None,
    minimum_query_coverage: float = 0.2,
    retrieval_index: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper over the indexed selector from issue #199."""
    settings = extract_task_context_settings(goal=goal, task_intent=task_intent)
    effective_budget = (
        int(token_budget)
        if token_budget is not None
        else int(settings["serialized_output_token_budget"] or DEFAULT_TOKEN_BUDGET)
    )
    selection = _select_context_targets(
        root,
        project_map,
        goal=goal,
        task_intent=task_intent,
        task_fingerprint=task_fingerprint,
        target=target,
        limit=limit,
        symbol_index=symbol_index,
        call_graph=call_graph,
        recent_paths=recent_paths,
        token_budget=effective_budget,
        minimum_query_coverage=minimum_query_coverage,
        retrieval_index=retrieval_index,
    )
    selection["query_fingerprint"] = task_query_fingerprint(
        goal=goal,
        task_intent=task_intent,
        task_fingerprint=task_fingerprint,
        target=target,
        query_terms=list(selection.get("query_terms", [])),
    )
    if selection.get("abstained") and not selection.get("targets"):
        selection["abstention_reason"] = "no_relevant_targets"
    return selection


def _map_fingerprint(project_map: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(project_map, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _fidelity_from_pack(
    *,
    paths: set[str],
    query_terms: list[str],
    matched_terms: set[str],
    goal: str,
    task_intent: Mapping[str, Any] | None,
    target: str,
    minimum_query_coverage: float,
    files: list[Mapping[str, Any]],
) -> dict[str, Any]:
    plan = build_task_query_plan(goal=goal, task_intent=task_intent, target=target, query_terms=query_terms)
    exact_identifiers = {str(item).lower() for item in plan["exact_identifiers"]}
    ac_ids = {str(item).upper() for item in plan["ac_ids"]}
    matched_lower = {item.lower() for item in matched_terms}
    matched_upper = {item.upper() for item in matched_terms}
    discriminative_terms = [term for term in query_terms if len(term) >= 3]

    identifier_match = {item for item in exact_identifiers if item in matched_lower}
    ac_match = {item for item in ac_ids if item in matched_upper}
    target_ok = bool(not target.strip() or target.replace(os.sep, "/").strip() in paths)
    coverage_ratio = len(matched_terms) / len(discriminative_terms) if discriminative_terms else 1.0
    requires_strong_signal = bool(
        plan["symbol_terms"] or exact_identifiers or ac_ids or plan["target_path"] or plan["path_terms"]
    )

    has_test_route = any(file_entry.get("tests") for file_entry in files)
    reasons: list[str] = []
    if not files:
        reasons.append("no_relevant_targets")
    if not target_ok:
        reasons.append(f"target_not_selected:{target.replace(os.sep, '/')}")
    if exact_identifiers and len(identifier_match) < len(exact_identifiers):
        reasons.append("missing_identifiers:" + ",".join(sorted(exact_identifiers - identifier_match)))
    if ac_ids and len(ac_match) < len(ac_ids):
        reasons.append("missing_ac_ids:" + ",".join(sorted(ac_ids - ac_match)))
    explicit_target_selected = bool(target.strip()) and target_ok
    if coverage_ratio < minimum_query_coverage and discriminative_terms and not explicit_target_selected:
        reasons.append(
            f"discriminative_coverage {coverage_ratio:.3f} below minimum {minimum_query_coverage:.3f}"
        )
    sufficient = bool(
        files
        and target_ok
        and len(identifier_match) == len(exact_identifiers)
        and len(ac_match) == len(ac_ids)
        and (
            explicit_target_selected
            or (coverage_ratio >= minimum_query_coverage if discriminative_terms else True)
        )
    )
    return {
        "sufficient": sufficient,
        "abstained": not files,
        "coverage_ratio": round(coverage_ratio, 6),
        "dimensions": {
            "target_preserved": target_ok,
            "identifier_coverage_ratio": round(len(identifier_match) / len(exact_identifiers), 6)
            if exact_identifiers
            else 1.0,
            "ac_coverage_ratio": round(len(ac_match) / len(ac_ids), 6) if ac_ids else 1.0,
            "discriminative_coverage_ratio": round(coverage_ratio, 6),
            "verification_route_present": has_test_route if requires_strong_signal else None,
            "layer_count": len(
                {file_entry.get("language", "") for file_entry in files if file_entry.get("language")}
            ),
            "has_discriminative_signal": requires_strong_signal,
        },
        "reasons": reasons,
    }


def _enforce_serialized_budget(
    pack: dict[str, Any],
    *,
    token_budget: int,
    estimated_tokens: int,
) -> dict[str, Any]:
    """Fit optional metadata against the exact serialized JSON byte budget."""

    def measure() -> tuple[int, int]:
        serialized = serialized_json_bytes(pack)
        return len(serialized), serialized_token_count(pack)

    def update_receipt() -> tuple[int, int]:
        previous: dict[str, Any] | None = None
        for _ in range(8):
            byte_count, token_count = measure()
            receipt = {
                "token_budget": token_budget,
                "tokenizer_policy": TOKENIZER_POLICY,
                "estimated_tokens": estimated_tokens,
                "serialized_bytes": byte_count,
                "serialized_tokens": token_count,
                "measurement": "MEASURED",
                "budget_declared": True,
                "within_budget": token_count <= token_budget,
            }
            pack["serialization_budget"] = receipt
            if receipt == previous:
                return byte_count, token_count
            previous = receipt
        return measure()

    _, token_count = update_receipt()
    # Drop only optional metadata, in a fixed order. Source spans, hashes and
    # target identity remain load-bearing and are never silently shortened.
    for field in ("llm_directives", "recent_changes", "dependencies", "drilldown", "scales"):
        if token_count <= token_budget:
            break
        pack.pop(field, None)
        _, token_count = update_receipt()

    if token_count > token_budget:
        pack["needs_broader_context"] = True
        pack.setdefault("needs_broader_context_reason", "")
        reason = (
            f"serialized_output {token_count} tokens/{pack['serialization_budget']['serialized_bytes']} bytes "
            f"exceeds budget {token_budget}; required metadata cannot fit"
        )
        current = str(pack.get("needs_broader_context_reason", ""))
        pack["needs_broader_context_reason"] = "; ".join(piece for piece in (current, reason) if piece)
        update_receipt()
    return pack


def apply_task_context(
    pack: dict[str, Any],
    *,
    target_rows: list[Mapping[str, Any]],
    project_map: Mapping[str, Any],
    goal: str = "",
    task_intent: Mapping[str, Any] | None = None,
    task_fingerprint: str = "",
    target: str = "",
    query_terms: list[str] | None = None,
    minimum_query_coverage: float = 0.2,
    token_budget: int | None = None,
) -> dict[str, Any]:
    task_aware = bool(
        goal.strip() or task_intent or task_fingerprint.strip() or target.strip() or query_terms
    )
    if not task_aware:
        return pack

    terms = sorted(set(query_terms or task_query_terms(goal, task_intent)))
    query_set = set(terms)
    row_by_path = {str(row.get("path", "")).replace(os.sep, "/"): row for row in target_rows}
    matched_union: set[str] = set()
    relevant_recent_paths: set[str] = set()
    for file_entry in pack.get("files", []):
        path = str(file_entry.get("path", "")).replace(os.sep, "/")
        row = row_by_path.get(path, {})
        matched = sorted(query_set & set(row.get("matched_terms", [])))
        recent_boost = bool(row.get("recent_change_boost", False) and matched)
        file_entry.update(
            {
                "relevance_score": float(row.get("relevance_score", 0.0) or 0.0),
                "relevance_reason": str(row.get("relevance_reason", "")),
                "matched_terms": matched,
                "recent_change_boost": recent_boost,
                "score_components": dict(row.get("score_components", {})),
                "reason_codes": list(row.get("reason_codes", [])),
            }
        )
        matched_union.update(matched)
        if recent_boost:
            relevant_recent_paths.add(path)

    ratio = len(matched_union) / len(terms) if terms else 0.0
    query_fingerprint = task_query_fingerprint(
        goal=goal,
        task_intent=task_intent,
        task_fingerprint=task_fingerprint,
        target=target,
        query_terms=terms,
    )
    old_hash = str(pack.get("pack_hash", ""))
    map_fingerprint = _map_fingerprint(project_map)
    pack["pack_hash"] = hashlib.sha256(
        f"{old_hash}|{map_fingerprint}|{query_fingerprint}".encode()
    ).hexdigest()
    pack["map_fingerprint"] = map_fingerprint
    pack["query_fingerprint"] = query_fingerprint
    pack["task_fingerprint"] = task_fingerprint.strip()
    pack["query_plan"] = build_task_query_plan(
        goal=goal,
        task_intent=task_intent,
        target=target,
        query_terms=terms,
    )
    pack["query_coverage"] = {
        "matched_terms": sorted(matched_union),
        "matched_count": len(matched_union),
        "query_term_count": len(terms),
        "ratio": round(ratio, 6),
        "minimum": minimum_query_coverage,
    }
    recent_values = project_map.get("recent_changes") or project_map.get("changed_files") or []
    pack["recent_changes"] = (
        [
            value
            for value in recent_values
            if (value.get("path") if isinstance(value, Mapping) else value) in relevant_recent_paths
        ]
        if isinstance(recent_values, list)
        else []
    )

    settings = extract_task_context_settings(goal=goal, task_intent=task_intent)
    effective_token_budget = int(
        token_budget
        if token_budget is not None
        else settings["serialized_output_token_budget"] or DEFAULT_TOKEN_BUDGET
    )
    pre_budget_payload = json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    estimated_tokens = estimate_tokens(pre_budget_payload)
    budget_reasons: list[str] = []
    pack = _enforce_serialized_budget(
        pack,
        token_budget=effective_token_budget,
        estimated_tokens=estimated_tokens,
    )
    if not pack["serialization_budget"]["within_budget"]:
        budget_reasons.append(
            f"serialized_output {pack['serialization_budget']['serialized_tokens']} exceeds budget "
            f"{effective_token_budget}"
        )
        budget_reasons.append(
            f"next_query: tighten target or raise token budget (current={effective_token_budget})"
        )

    fidelity = _fidelity_from_pack(
        paths={str(file_entry.get("path", "")).replace(os.sep, "/") for file_entry in pack.get("files", [])},
        query_terms=terms,
        matched_terms=matched_union,
        goal=goal,
        task_intent=task_intent,
        target=target,
        minimum_query_coverage=minimum_query_coverage,
        files=list(pack.get("files", [])),
    )
    pack["fidelity"] = fidelity

    reasons: list[str] = []
    explicit_target_selected = bool(target.strip()) and any(
        str(file_entry.get("path", "")).replace(os.sep, "/") == target.replace(os.sep, "/").strip()
        for file_entry in pack.get("files", [])
    )
    if not pack.get("files"):
        reasons.append("no relevant task targets selected")
    if ratio < minimum_query_coverage and terms and not explicit_target_selected:
        reasons.append(f"query coverage {ratio:.3f} below minimum {minimum_query_coverage:.3f}")
    reasons.extend(fidelity["reasons"])
    reasons.extend(budget_reasons)
    if reasons:
        pack["needs_broader_context"] = True
        previous = str(pack.get("needs_broader_context_reason", ""))
        pack["needs_broader_context_reason"] = "; ".join(piece for piece in [previous, *reasons] if piece)
    pack = _enforce_serialized_budget(
        pack,
        token_budget=effective_token_budget,
        estimated_tokens=estimated_tokens,
    )
    return pack


__all__ = [
    "apply_task_context",
    "select_context_targets",
    "task_query_fingerprint",
    "task_query_terms",
]
