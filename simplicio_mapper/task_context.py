"""Deterministic task-aware ranking for mapper context packs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

_STOP_WORDS = {
    "about", "after", "antes", "apenas", "como", "com", "cada", "das", "dos",
    "depois", "deve", "entre", "essa", "esse", "esta", "este", "for", "from",
    "mais", "nao", "onde", "para", "pela", "pelo", "pode", "por", "primeiro",
    "quando", "que", "sao", "sem", "ser", "that", "the", "then", "this", "tipo",
    "task", "system", "uma", "uns", "with",
}
_MAX_CANDIDATE_CHARS = 64_000


def _normalized_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return " ".join(text.lower().split())


def _flatten_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        chunks: list[str] = []
        for key in sorted(value, key=str):
            if key in {"fingerprint", "schema", "id", "rule_ids"}:
                continue
            chunks.extend(_flatten_strings(value[key]))
        return chunks
    if isinstance(value, (list, tuple, set)):
        chunks = []
        for item in value:
            chunks.extend(_flatten_strings(item))
        return chunks
    return []


def task_query_terms(goal: str = "", task_intent: Mapping[str, Any] | None = None) -> list[str]:
    chunks = [goal, *_flatten_strings(task_intent or {})]
    tokens = re.findall(r"[a-z0-9_]+", _normalized_text(" ".join(chunks)))
    return sorted({token for token in tokens if len(token) >= 3 and token not in _STOP_WORDS})


def task_query_fingerprint(
    *,
    goal: str = "",
    task_intent: Mapping[str, Any] | None = None,
    task_fingerprint: str = "",
    target: str = "",
    query_terms: list[str] | None = None,
) -> str:
    terms = sorted(set(query_terms or task_query_terms(goal, task_intent)))
    identity = {
        "goal": _normalized_text(goal),
        "intent": task_intent or {},
        "task_fingerprint": task_fingerprint.strip(),
        "target": target.replace(os.sep, "/").strip(),
        "terms": terms,
    }
    canonical = json.dumps(identity, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _recent_paths(project_map: Mapping[str, Any]) -> set[str]:
    values = project_map.get("recent_changes") or project_map.get("changed_files") or []
    paths: set[str] = set()
    if not isinstance(values, list):
        return paths
    for value in values:
        path = value.get("path") if isinstance(value, Mapping) else value
        if isinstance(path, str) and path:
            paths.add(path.replace(os.sep, "/"))
    return paths


def _candidate_text(root: str, entry: Mapping[str, Any]) -> tuple[str, set[str]]:
    path = str(entry.get("path", "")).replace(os.sep, "/")
    parts = [path]
    for key in ("language", "summary", "roles", "tags", "imports", "exports"):
        value = entry.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value)
    absolute = os.path.join(root, path)
    try:
        with open(absolute, encoding="utf-8", errors="replace") as handle:
            parts.append(handle.read(_MAX_CANDIDATE_CHARS))
    except OSError:
        pass
    text = _normalized_text(" ".join(parts))
    tokens = set(re.findall(r"[a-z0-9_]+", text))
    path_tokens = set(re.findall(r"[a-z0-9_]+", _normalized_text(path)))
    return path, tokens | path_tokens


def select_context_targets(
    root: str,
    project_map: Mapping[str, Any],
    *,
    goal: str = "",
    task_intent: Mapping[str, Any] | None = None,
    task_fingerprint: str = "",
    target: str = "",
    limit: int = 8,
) -> dict[str, Any]:
    """Rank task-relevant files or abstain; recency never creates relevance."""
    abs_root = os.path.abspath(root)
    query_terms = task_query_terms(goal, task_intent)
    query_set = set(query_terms)
    normalized_target = target.replace(os.sep, "/").strip()
    raw_files = project_map.get("files", [])
    entries = [dict(item) for item in raw_files if isinstance(item, Mapping)]
    known_paths = {str(item.get("path", "")).replace(os.sep, "/") for item in entries}
    target_exists = bool(normalized_target and os.path.isfile(os.path.join(abs_root, normalized_target)))
    if target_exists and normalized_target not in known_paths:
        entries.append({"path": normalized_target})
    recent = _recent_paths(project_map)
    ranked: list[dict[str, Any]] = []
    for entry in entries:
        path, candidate_terms = _candidate_text(abs_root, entry)
        if not path or not os.path.isfile(os.path.join(abs_root, path)):
            continue
        matched = sorted(query_set & candidate_terms)
        exact_target = bool(normalized_target and path == normalized_target)
        if not matched and not exact_target:
            continue
        coverage = len(matched) / len(query_terms) if query_terms else 0.0
        recent_boost = bool(matched and path in recent)
        importance = float(entry.get("importance", 0.0) or 0.0)
        score = coverage + min(max(importance, 0.0), 1.0) * 0.01
        if recent_boost:
            score += 0.05
        if exact_target:
            score += 2.0
        reason_parts = []
        if exact_target:
            reason_parts.append("explicit_target")
        if matched:
            reason_parts.append("matched_terms=" + ",".join(matched))
        if recent_boost:
            reason_parts.append("relevant_recent_change")
        ranked.append({
            "path": path,
            "relevance_score": round(score, 6),
            "relevance_reason": "; ".join(reason_parts),
            "matched_terms": matched,
            "recent_change_boost": recent_boost,
        })
    ranked.sort(key=lambda row: (-row["relevance_score"], row["path"]))
    selected = ranked[: max(1, limit)]
    matched_union = sorted({term for row in selected for term in row["matched_terms"]})
    coverage_ratio = len(matched_union) / len(query_terms) if query_terms else 0.0
    if not normalized_target:
        target_resolution = {"requested": "", "status": "not_requested", "reason": ""}
    elif not target_exists:
        target_resolution = {
            "requested": normalized_target,
            "status": "missing",
            "reason": f"target does not exist: {normalized_target}",
        }
    else:
        target_resolution = {
            "requested": normalized_target,
            "status": "included" if normalized_target in {row["path"] for row in selected} else "excluded",
            "reason": "explicit target selected" if normalized_target in {row["path"] for row in selected} else "target excluded by limit",
        }
    abstained = not selected
    return {
        "query_fingerprint": task_query_fingerprint(
            goal=goal,
            task_intent=task_intent,
            task_fingerprint=task_fingerprint,
            target=normalized_target,
            query_terms=query_terms,
        ),
        "query_terms": query_terms,
        "targets": selected,
        "coverage": {
            "matched_terms": matched_union,
            "matched_count": len(matched_union),
            "query_term_count": len(query_terms),
            "ratio": round(coverage_ratio, 6),
        },
        "target_resolution": target_resolution,
        "abstained": abstained,
        "abstention_reason": "no_relevant_targets" if abstained else "",
        "metrics": {
            "candidate_count": len(entries),
            "relevant_count": len(ranked),
            "selected_count": len(selected),
            "precision_at_k": 1.0 if selected else 0.0,
        },
    }


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
) -> dict[str, Any]:
    task_aware = bool(goal.strip() or task_intent or task_fingerprint.strip() or target.strip() or query_terms)
    if not task_aware:
        return pack
    terms = sorted(set(query_terms or task_query_terms(goal, task_intent)))
    query_set = set(terms)
    row_by_path = {str(row.get("path", "")).replace(os.sep, "/"): row for row in target_rows}
    matched_union: set[str] = set()
    relevant_recent_paths: set[str] = set()
    for file_entry in pack.get("files", []):
        row = row_by_path.get(str(file_entry.get("path", "")), {})
        matched = sorted(query_set & set(row.get("matched_terms", [])))
        score = float(row.get("relevance_score", 0.0) or 0.0)
        reason = str(row.get("relevance_reason", ""))
        recent_boost = bool(row.get("recent_change_boost", False) and matched)
        file_entry.update({
            "relevance_score": score,
            "relevance_reason": reason,
            "matched_terms": matched,
            "recent_change_boost": recent_boost,
        })
        matched_union.update(matched)
        if recent_boost:
            relevant_recent_paths.add(str(file_entry.get("path", "")))
    ratio = len(matched_union) / len(terms) if terms else 0.0
    query_fingerprint = task_query_fingerprint(
        goal=goal,
        task_intent=task_intent,
        task_fingerprint=task_fingerprint,
        target=target,
        query_terms=terms,
    )
    old_hash = str(pack.get("pack_hash", ""))
    map_fingerprint = hashlib.sha256(
        json.dumps(project_map, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    pack["pack_hash"] = hashlib.sha256(
        f"{old_hash}|{map_fingerprint}|{query_fingerprint}".encode()
    ).hexdigest()
    pack["map_fingerprint"] = map_fingerprint
    pack["query_fingerprint"] = query_fingerprint
    pack["task_fingerprint"] = task_fingerprint.strip()
    pack["query_coverage"] = {
        "matched_terms": sorted(matched_union),
        "matched_count": len(matched_union),
        "query_term_count": len(terms),
        "ratio": round(ratio, 6),
        "minimum": minimum_query_coverage,
    }
    recent_values = project_map.get("recent_changes") or project_map.get("changed_files") or []
    pack["recent_changes"] = [
        value
        for value in recent_values
        if (value.get("path") if isinstance(value, Mapping) else value) in relevant_recent_paths
    ] if isinstance(recent_values, list) else []
    if not pack.get("files"):
        reason = "no relevant task targets selected"
    elif ratio < minimum_query_coverage:
        reason = f"query coverage {ratio:.3f} below minimum {minimum_query_coverage:.3f}"
    else:
        reason = ""
    if reason:
        pack["needs_broader_context"] = True
        previous = str(pack.get("needs_broader_context_reason", ""))
        pack["needs_broader_context_reason"] = "; ".join(piece for piece in (previous, reason) if piece)
    return pack


__all__ = [
    "apply_task_context",
    "select_context_targets",
    "task_query_fingerprint",
    "task_query_terms",
]
