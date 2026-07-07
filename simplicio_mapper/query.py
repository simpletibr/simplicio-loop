"""Structured queries over already-built mapper artifacts (F10 `ask`).

Every verb answers from artifacts already computed in memory — never a
fresh repository scan — so an agent that needs "who calls X" gets a
handful of evidenced rows instead of loading call-graph.json/symbol-index.json
whole. Read-only: no verb writes anything to disk.

Emits ``simplicio.ask/v1`` as documented in ``SIMPLICIO_INTEGRATION.md``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections import deque
from typing import Any

from .docsync import _flows_touching, _scan_manual_docs_for_references, _symbols_for_files
from .flows import build_flow_inventory
from .mapper import _parse_json_safe, build_artifacts

ASK_SCHEMA = "simplicio.ask/v1"
DEFAULT_LIMIT = 20
DEFAULT_DEPTH = 3

VERBS = ("callers", "callees", "reaches", "impact", "flows", "rules", "tests-for", "term", "precedent")

# `precedent` is native-first: shell out to the `simplicio` runtime's
# SQLite/FTS5 precedent search when the binary is on PATH, falling back to a
# local keyword-overlap ranking over the in-memory precedent-index otherwise.
_PRECEDENT_RUNTIME_BINARY = "simplicio"
_PRECEDENT_NO_RUNTIME_ENV = "SIMPLICIO_MAPPER_NO_RUNTIME_PRECEDENT"
_PRECEDENT_TOP_N = 5


def _edge_view(edge: dict) -> dict:
    return {
        "source_file": edge.get("source_file"),
        "source_symbol": edge.get("source_symbol"),
        "target_file": edge.get("target_file"),
        "target_symbol": edge.get("target_symbol"),
        "line": edge.get("line"),
        "confidence": edge.get("confidence"),
    }


def _resolve_symbol_name(symbol_index: dict, name: str) -> str:
    """Accept both a short name and a fully qualified name; prefer an exact
    qualified match, falling back to the first symbol whose short name
    matches (and noting the qualified form so results stay disambiguated)."""
    for symbol in symbol_index.get("symbols", []):
        if symbol.get("qualified_name") == name:
            return name
    for symbol in symbol_index.get("symbols", []):
        if symbol.get("name") == name:
            return symbol["qualified_name"]
    return name


def _callers(call_graph: dict, name: str, limit: int) -> tuple[list[dict], int]:
    matches = [
        edge for edge in call_graph.get("edges", [])
        if edge.get("type") == "calls" and edge.get("target_symbol") == name
    ]
    matches.sort(key=lambda e: (e.get("source_file") or "", e.get("line") or 0))
    return matches[:limit], len(matches)


def _callees(call_graph: dict, name: str, limit: int) -> tuple[list[dict], int]:
    matches = [
        edge for edge in call_graph.get("edges", [])
        if edge.get("type") == "calls" and edge.get("source_symbol") == name
    ]
    matches.sort(key=lambda e: (e.get("target_file") or "", e.get("target_symbol") or ""))
    return matches[:limit], len(matches)


def _reaches(call_graph: dict, entry_file: str, depth: int, limit: int) -> tuple[list[dict], int]:
    edges_by_source: dict[str, list[dict]] = {}
    for edge in call_graph.get("edges", []):
        source = edge.get("source_file")
        if source:
            edges_by_source.setdefault(source, []).append(edge)

    visited = {entry_file}
    order: list[dict] = []
    queue: deque[tuple[str, int]] = deque([(entry_file, 0)])
    while queue:
        current, current_depth = queue.popleft()
        if current_depth > 0:
            order.append({"path": current, "depth": current_depth})
        if current_depth >= depth:
            continue
        for edge in sorted(
            edges_by_source.get(current, []),
            key=lambda e: (e.get("target_file") or "", e.get("type") or ""),
        ):
            target = edge.get("target_file")
            if not target or target in visited:
                continue
            visited.add(target)
            queue.append((target, current_depth + 1))
    order.sort(key=lambda item: (item["depth"], item["path"]))
    return order[:limit], len(order)


def _impact(cwd: str, artifacts: dict, target_files: list[str]) -> dict:
    flow_inventory = build_flow_inventory(cwd, artifacts)
    target_set = set(target_files)
    symbols = _symbols_for_files(artifacts["symbol_index"], target_set)
    flows = _flows_touching(flow_inventory, target_set)
    needs_review = _scan_manual_docs_for_references(cwd, target_set)
    return {
        "affected_symbols": [
            {"symbol": s.get("qualified_name") or s.get("name"), "path": s["defined_in"]} for s in symbols
        ],
        "affected_flows": flows,
        "needs_review": needs_review,
    }


def _read_text(cwd: str, rel_path: str) -> str:
    try:
        with open(os.path.join(cwd, rel_path), encoding="utf-8", errors="ignore") as handle:
            return handle.read()
    except OSError:
        return ""


def _tests_for(cwd: str, project_map: dict, target_file: str, limit: int) -> tuple[list[str], int]:
    stem = os.path.splitext(os.path.basename(target_file))[0]
    module = target_file.split("/", 1)[0] if "/" in target_file else "."
    matches = []
    for test_file in project_map.get("test_files") or []:
        text = _read_text(cwd, test_file)
        if not text:
            continue
        if target_file in text or stem in text or (module != "." and module in text):
            matches.append(test_file)
    matches.sort()
    return matches[:limit], len(matches)


def _business_rules(out_dir_abs: str) -> dict | None:
    return _parse_json_safe(os.path.join(out_dir_abs, "business-rules.json")) or None


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if token}


def _runtime_precedent_search(cwd: str, text: str, top_n: int) -> dict | None:
    """Shell out to the `simplicio` runtime's precedent search (SQLite/FTS5
    lexical ranking + a git-apply dry-run reuse-safety check).

    Returns the parsed ``simplicio.precedent-search/v1`` payload, or
    ``None`` on any failure — binary missing, kill-switch set, non-zero
    exit, timeout, or malformed JSON — so the caller always has a safe
    local fallback. Never raises.
    """
    if os.environ.get(_PRECEDENT_NO_RUNTIME_ENV):
        return None
    binary = shutil.which(_PRECEDENT_RUNTIME_BINARY)
    if not binary:
        return None
    try:
        result = subprocess.run(
            [binary, "precedent", "search", "--repo", cwd, "--text", text, "--top", str(top_n), "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        return None
    if not isinstance(payload, dict) or "candidates" not in payload:
        return None
    return payload


def _candidate_view(candidate: dict) -> dict:
    return {
        "precedent_id": candidate.get("precedent_id"),
        "score": candidate.get("score"),
        "reuse_level": candidate.get("reuse_level"),
        "suggested_next_action": candidate.get("suggested_next_action"),
    }


def _local_precedent_fallback(items: list[dict], text: str, top_n: int) -> list[dict]:
    """Rank precedent-index items by keyword overlap between the query and
    each item's ``tags`` + ``summary``. Descending overlap count; ties keep
    the index's original order (stable sort). Items with zero overlap are
    dropped rather than padding the tail with irrelevant precedents."""
    query_tokens = _tokenize(text)
    if not query_tokens:
        return []
    scored: list[tuple[int, dict]] = []
    for item in items:
        haystack = " ".join(item.get("tags") or []) + " " + str(item.get("summary") or "")
        overlap = len(query_tokens & _tokenize(haystack))
        if overlap:
            scored.append((overlap, item))
    scored.sort(key=lambda row: row[0], reverse=True)
    return [item for _, item in scored[:top_n]]


def run_query(
    cwd: str,
    out_dir: str = ".simplicio",
    verb: str = "",
    arg: str | None = None,
    depth: int = DEFAULT_DEPTH,
    limit: int = DEFAULT_LIMIT,
    effect: str | None = None,
    category: str | None = None,
) -> dict:
    if verb not in VERBS:
        raise ValueError(f"unknown ask verb: {verb!r} (expected one of {', '.join(VERBS)})")

    abs_cwd = os.path.abspath(cwd)
    abs_out = os.path.abspath(os.path.join(abs_cwd, out_dir))
    artifacts = build_artifacts(abs_cwd, output_dir=out_dir)
    symbol_index = artifacts["symbol_index"]
    call_graph = artifacts["call_graph"]
    project_map = artifacts["project_map"]

    query: dict[str, Any] = {"verb": verb}
    if arg:
        query["arg"] = arg
    if verb == "reaches":
        query["depth"] = depth
    if verb == "flows" and effect:
        query["effect"] = effect
    if verb == "rules" and category:
        query["category"] = category

    note = None
    if verb == "callers":
        resolved = _resolve_symbol_name(symbol_index, arg or "")
        matches, total = _callers(call_graph, resolved, limit)
        payload = {"results": [_edge_view(e) for e in matches], "total": total}
    elif verb == "callees":
        resolved = _resolve_symbol_name(symbol_index, arg or "")
        matches, total = _callees(call_graph, resolved, limit)
        payload = {"results": [_edge_view(e) for e in matches], "total": total}
    elif verb == "reaches":
        matches, total = _reaches(call_graph, arg or "", depth, limit)
        payload = {"results": matches, "total": total}
    elif verb == "impact":
        impact = _impact(abs_cwd, artifacts, [arg] if arg else [])
        total = len(impact["affected_symbols"]) + len(impact["affected_flows"]) + len(impact["needs_review"])
        payload = {"results": impact, "total": total}
    elif verb == "flows":
        flow_inventory = build_flow_inventory(abs_cwd, artifacts)
        flows = flow_inventory["flows"]
        if effect:
            flows = [f for f in flows if any(e["type"] == effect for e in f["effects"])]
        payload = {"results": flows[:limit], "total": len(flows)}
    elif verb == "tests-for":
        matches, total = _tests_for(abs_cwd, project_map, arg or "", limit)
        payload = {"results": matches, "total": total}
    elif verb == "precedent":
        text = arg or ""
        top_n = min(limit, _PRECEDENT_TOP_N)
        native = _runtime_precedent_search(abs_cwd, text, top_n) if text else None
        if native is not None:
            candidates = native.get("candidates") or []
            results = [_candidate_view(c) for c in candidates[:top_n]]
            payload = {"results": results, "total": len(candidates), "source": "runtime-precedent-search"}
            if not results and native.get("suggested_next_action"):
                note = native["suggested_next_action"]
        else:
            items = artifacts["precedent_index"].get("items") or []
            matches = _local_precedent_fallback(items, text, top_n)
            payload = {"results": matches, "total": len(matches), "source": "local-tag-overlap"}
    elif verb in ("rules", "term"):
        rules_doc = _business_rules(abs_out)
        if rules_doc is None:
            note = "no business-rules.json found — run `simplicio-mapper business <path>` first"
            payload = {"results": [], "total": 0}
        elif verb == "rules":
            rules = rules_doc.get("rules") or []
            if category:
                rules = [r for r in rules if r.get("category") == category]
            payload = {"results": rules[:limit], "total": len(rules)}
        else:
            glossary = [item for item in rules_doc.get("glossary") or [] if item.get("term") == arg]
            payload = {"results": glossary, "total": len(glossary)}
    else:  # pragma: no cover - guarded by VERBS check above
        raise ValueError(f"unknown ask verb: {verb}")

    return {"schema": ASK_SCHEMA, "version": 1, "query": query, "note": note, **payload}
