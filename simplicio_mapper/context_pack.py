"""simplicio.context-pack/v1 — compact LLM context bundles (issue #115).

The mapper is the canonical producer of compact context for LLM planners.
A context pack collects, for a given set of target files:

- repo metadata (mapper schema, root hash);
- per-file snapshot hashes, language, symbols defined inside, callers /
  imports derived from the call graph, and related test files;
- optional selected line ranges with per-range hashes and a short snippet
  (omitted in compact mode for files above the line threshold);
- dependency hints carried forward from `project-map.json`;
- recent changed files when available;
- an explicit `needs_broader_context` flag with a `reason` when compact
  context is unsafe (target missing, unreadable, unstable range, or any of
  the upstream mapper artifacts is absent).

The canonical schema lives in simplicio-runtime issue #70; this module
must not introduce a repo-local variation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable
from typing import Any

from .context_contract import canonical_sha256
from .mapper import LLM_DIRECTIVES
from .relations import canonicalize_relation, relation_coverage, relation_summary
from .task_context import apply_task_context, enforce_serialized_budget, select_context_targets

CONTEXT_PACK_SCHEMA = "simplicio.context-pack/v1"
MAPPER_INDEX_SCHEMA = "simplicio.mapper-index/v1"

COMPACT_LINE_THRESHOLD = 2000
_SNIPPET_PREFIX_CHARS = 120

_LANGUAGE_BY_EXT = {
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".py": "python",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hrl": "erlang",
    ".lua": "lua",
    ".r": "r",
    ".jl": "julia",
    ".pl": "perl",
    ".pm": "perl",
    ".html": "html",
    ".htm": "html",
    ".xhtml": "xhtml",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    ".eex": "html-template",
    ".heex": "html-template",
    ".leex": "html-template",
    ".erb": "html-template",
}


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_safe(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def _load_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _language_for(path: str, text: str | None = None) -> str:
    base = os.path.basename(path)
    if base == "Dockerfile":
        return "dockerfile"
    ext = os.path.splitext(path)[1].lower()
    if ext == ".m":
        if text is None:
            return "objectivec"
        probe = text
        if re.search(r"^\s*(#\s*import|@interface|@implementation|@import\b)", probe, re.MULTILINE):
            return "objectivec"
        return "matlab"
    return _LANGUAGE_BY_EXT.get(ext, ext[1:] if ext else "text")


def _range_snippet(text: str, start: int, end: int, compact: bool) -> list[str]:
    if compact:
        return []
    lines = text.splitlines()
    out: list[str] = []
    if 1 <= start <= len(lines):
        out.append(lines[start - 1].strip()[:_SNIPPET_PREFIX_CHARS])
    if start != end and 1 <= end <= len(lines):
        out.append(lines[end - 1].strip()[:_SNIPPET_PREFIX_CHARS])
    return [piece for piece in out if piece]


def _file_symbols(symbols: list[dict], path: str) -> list[dict]:
    found: list[dict] = []
    for symbol in symbols:
        if symbol.get("defined_in") != path:
            continue
        identity = symbol.get("qualified_name") or symbol.get("name") or ""
        found.append(
            {
                "name": symbol.get("name"),
                "kind": symbol.get("kind"),
                "line": symbol.get("line"),
                "hash": hashlib.sha256(f"{identity}|{path}".encode()).hexdigest()[:16],
            }
        )
    return sorted(found, key=lambda entry: (entry.get("line") or 0, entry.get("name") or ""))


def _related_tests(project_files: dict, path: str) -> list[str]:
    base = os.path.splitext(os.path.basename(path))[0]
    if not base:
        return []
    matches: set[str] = set()
    for candidate, meta in project_files.items():
        roles = meta.get("roles", [])
        if "test" in roles and base in candidate:
            matches.add(candidate)
    return sorted(matches)


def _related_test_evidence(project_files: dict, path: str, tests: list[str]) -> list[dict[str, Any]]:
    """Classify name-paired tests separately from measured test evidence."""
    out: list[dict[str, Any]] = []
    for test_path in tests:
        metadata = project_files.get(test_path, {})
        declared = metadata.get("test_evidence", {}) if isinstance(metadata, dict) else {}
        declared = declared if isinstance(declared, dict) else {}
        evidence_class = str(declared.get("evidence_class") or "")
        if evidence_class not in {"inferred_by_name", "runtime_observed"}:
            evidence_class = "runtime_observed" if declared.get("measured") else "inferred_by_name"
        out.append(
            {
                "path": test_path,
                "verifies": path,
                "evidence_class": evidence_class,
                "provenance": {
                    "method": declared.get("method") or "basename-role-match",
                    "measured": evidence_class == "runtime_observed",
                },
            }
        )
    return out


def _call_graph_edges(call_graph: dict) -> list[dict]:
    """Return only canonical Mapper v1 relations."""
    edges: list[dict] = []
    for edge in call_graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        normalized = canonicalize_relation(edge)
        if normalized is not None:
            edges.append(normalized)
    return edges


def _json_fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _module_candidates(path: str) -> list[str]:
    normalized = path.replace(os.sep, "/").strip("/")
    if not normalized:
        return []
    parts = normalized.split("/")
    return [parts[0]] if len(parts) > 1 else [normalized]


def _drilldown_handles(path: str, ranges: list[dict], symbols: list[dict]) -> list[dict]:
    handles: list[dict] = [{"kind": "file", "file": path}]
    for symbol in symbols:
        line = symbol.get("line")
        if isinstance(line, int):
            handles.append({"kind": "symbol", "file": path, "line": line, "symbol": symbol.get("name")})
    for selected in ranges:
        handles.append(
            {
                "kind": "range",
                "file": path,
                "span": [selected["start_line"], selected["end_line"]],
                "range_hash": selected["range_hash"],
            }
        )
    return handles


def _scale_summary(files_out: list[dict]) -> dict[str, Any]:
    return {
        "micro": {"symbol_count": sum(len(entry.get("symbols", [])) for entry in files_out)},
        "meso": {
            "file_count": len(files_out),
            "dependency_edges": sum(
                len(entry.get("imports", [])) + len(entry.get("callers", [])) for entry in files_out
            ),
        },
        "macro": {
            "module_candidates": sorted(
                {
                    module
                    for entry in files_out
                    for module in entry.get("scale_context", {}).get("macro", {}).get("modules", [])
                }
            ),
        },
    }


def build_context_pack(
    root: str,
    targets: Iterable[dict],
    *,
    project_map: dict | None = None,
    symbol_index: dict | None = None,
    call_graph: dict | None = None,
    architecture_inventory: dict | None = None,
    goal: str = "",
    task_intent: dict[str, Any] | None = None,
    task_fingerprint: str = "",
    target: str = "",
    query_terms: list[str] | None = None,
    minimum_query_coverage: float = 0.2,
    token_budget: int | None = None,
    context_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a `simplicio.context-pack/v1` envelope.

    `targets` is an iterable of `{"path": str, "ranges": [(start, end), ...]}`
    dicts. Pre-built `project_map` / `symbol_index` / `call_graph` payloads
    can be passed in; otherwise the function looks under `.simplicio/` and
    emits `needs_broader_context=True` when any of them is missing.
    """
    target_rows = list(targets)
    abs_root = os.path.abspath(root)
    base = os.path.join(abs_root, ".simplicio")
    project_map = (
        project_map if project_map is not None else _load_json(os.path.join(base, "project-map.json"))
    )
    symbol_index = (
        symbol_index if symbol_index is not None else _load_json(os.path.join(base, "symbol-index.json"))
    )
    call_graph = call_graph if call_graph is not None else _load_json(os.path.join(base, "call-graph.json"))
    architecture_inventory = (
        architecture_inventory
        if architecture_inventory is not None
        else _load_json(os.path.join(base, "architecture-inventory.json"))
    )

    reasons: list[str] = []
    if not project_map:
        reasons.append("project-map.json absent")
        project_map = {}
    if not symbol_index:
        reasons.append("symbol-index.json absent")
        symbol_index = {}
    if not call_graph:
        reasons.append("call-graph.json absent")
        call_graph = {}
    if not architecture_inventory:
        architecture_inventory = {}

    pm_files = {entry["path"]: entry for entry in project_map.get("files", [])}
    si_symbols = symbol_index.get("symbols", [])
    cg_edges = _call_graph_edges(call_graph)
    cg_relation_summaries = [summary for edge in cg_edges if (summary := relation_summary(edge)) is not None]
    raw_cg_edges = call_graph.get("edges", [])
    raw_cg_edges = raw_cg_edges if isinstance(raw_cg_edges, list) else []
    upstream_coverage = call_graph.get("coverage", {})
    upstream_coverage = upstream_coverage if isinstance(upstream_coverage, dict) else {}
    cg_coverage = relation_coverage(
        cg_relation_summaries,
        observed_edges=max(len(raw_cg_edges), int(upstream_coverage.get("observed_edges", 0) or 0)),
        edge_limit=upstream_coverage.get("edge_limit"),
        invalid_edges=max(
            max(0, len(raw_cg_edges) - len(cg_relation_summaries)),
            int(upstream_coverage.get("invalid_edges", 0) or 0),
        ),
    )
    if upstream_coverage.get("status") == "degraded":
        cg_coverage["status"] = "degraded"
    producer = call_graph.get("producer", {})
    producer = producer if isinstance(producer, dict) else {}
    if call_graph.get("schema") == "simplicio.call-graph/v1" and producer.get("canonical_digest"):
        cg_coverage["contract_status"] = "canonical"
    else:
        cg_coverage["contract_status"] = "degraded"
        if cg_coverage["status"] == "complete":
            cg_coverage["status"] = "degraded"
    layer_by_module: dict[str, list[str]] = {}
    for layer in architecture_inventory.get("layers", []):
        layer_name = layer.get("name")
        for module_name in layer.get("modules", []) or []:
            if layer_name:
                layer_by_module.setdefault(module_name, []).append(layer_name)

    files_out: list[dict] = []
    for target_row in target_rows:
        path = target_row["path"]
        ranges = list(target_row.get("ranges", []))
        abs_path = os.path.join(abs_root, path) if not os.path.isabs(path) else path
        if not os.path.exists(abs_path):
            if target_row.get("creation_target") is True:
                empty_hash = hashlib.sha256(b"").hexdigest()
                files_out.append(
                    {
                        "path": path.replace(os.sep, "/"),
                        "language": "",
                        "snapshot_hash": empty_hash,
                        "line_count": 0,
                        "compact": False,
                        "ranges": [],
                        "symbols": [],
                        "callers": [],
                        "imports": [],
                        "relation_evidence": [],
                        "tests": [],
                        "test_evidence": [],
                        "drilldown": {"reversible": True, "handles": []},
                        "freshness": {"snapshot_hash": empty_hash, "range_hashes": []},
                        "scale_context": {
                            "micro": {"symbols": [], "symbol_count": 0},
                            "meso": {"path": path.replace(os.sep, "/"), "imports": [], "callers": [], "tests": [], "relation_evidence": [], "test_evidence": []},
                            "macro": {"modules": [], "layers": []},
                        },
                        "creation_target": True,
                    }
                )
                continue
            reasons.append(f"target missing: {path}")
            continue
        text = _read_safe(abs_path)
        if text is None:
            reasons.append(f"unreadable: {path}")
            continue
        line_count = len(text.splitlines())
        compact = line_count > COMPACT_LINE_THRESHOLD
        selected_ranges: list[dict] = []
        for start, end in ranges:
            if start < 1 or end < start or end > line_count:
                reasons.append(f"unstable range {start}-{end} in {path}")
                continue
            chunk = "\n".join(text.splitlines()[start - 1 : end])
            selected_ranges.append(
                {
                    "start_line": start,
                    "end_line": end,
                    "range_hash": _sha256_text(chunk),
                    "snippet": _range_snippet(text, start, end, compact),
                }
            )
        callers = sorted(
            {
                edge["source_file"]
                for edge in cg_edges
                if edge.get("target_file") == path
                and edge.get("source_file") != path
            }
        )
        imports = sorted(
            {
                edge["target_file"]
                for edge in cg_edges
                if edge.get("source_file") == path
                and edge.get("target_file")
                and edge.get("target_file") != path
            }
        )
        relation_evidence = [
            relation_summary(edge)
            for edge in cg_edges
            if path in {edge.get("source_file"), edge.get("target_file")}
        ]
        relation_evidence = sorted(
            (edge for edge in relation_evidence if edge is not None),
            key=lambda edge: str(edge.get("relation_id") or ""),
        )
        tests = _related_tests(pm_files, path)
        test_evidence = _related_test_evidence(pm_files, path, tests)
        symbols = _file_symbols(si_symbols, path)
        modules = _module_candidates(path)
        macro_layers = sorted({layer for module in modules for layer in layer_by_module.get(module, [])})
        drilldown = _drilldown_handles(path.replace(os.sep, "/"), selected_ranges, symbols)
        files_out.append(
            {
                "path": path.replace(os.sep, "/"),
                "language": _language_for(abs_path, text),
                "snapshot_hash": _sha256_text(text),
                "line_count": line_count,
                "compact": compact,
                "ranges": selected_ranges,
                "symbols": symbols,
                "callers": callers,
                "imports": imports,
                "relation_evidence": relation_evidence,
                "tests": tests,
                "test_evidence": test_evidence,
                "drilldown": {"reversible": True, "handles": drilldown},
                "freshness": {
                    "snapshot_hash": _sha256_text(text),
                    "range_hashes": [selected["range_hash"] for selected in selected_ranges],
                },
                "scale_context": {
                    "micro": {"symbols": symbols, "symbol_count": len(symbols)},
                    "meso": {
                        "path": path.replace(os.sep, "/"),
                        "imports": imports,
                        "callers": callers,
                        "tests": tests,
                        "relation_evidence": relation_evidence,
                        "test_evidence": test_evidence,
                    },
                    "macro": {"modules": modules, "layers": macro_layers},
                },
            }
        )

    needs_broader = bool(reasons)
    files_out.sort(key=lambda entry: entry["path"])

    digest = hashlib.sha256()
    root_hash = _sha256_text(abs_root)
    digest.update(root_hash.encode("utf-8"))
    digest.update(_json_fingerprint(project_map).encode("utf-8"))
    digest.update(_json_fingerprint(symbol_index).encode("utf-8"))
    digest.update(_json_fingerprint(call_graph).encode("utf-8"))
    for entry in files_out:
        digest.update(entry["snapshot_hash"].encode("utf-8"))
        for selected in entry["ranges"]:
            digest.update(selected["range_hash"].encode("utf-8"))

    payload = {
        "schema": CONTEXT_PACK_SCHEMA,
        "repo": {
            "mapper_schema": MAPPER_INDEX_SCHEMA,
            "root_hash": root_hash,
        },
        "pack_hash": digest.hexdigest(),
        "files": files_out,
        "scales": _scale_summary(files_out),
        "freshness": {
            "root_hash": root_hash,
            "artifact_hashes": {
                "project_map": _json_fingerprint(project_map),
                "symbol_index": _json_fingerprint(symbol_index),
                "call_graph": _json_fingerprint(call_graph),
                "architecture_inventory": _json_fingerprint(architecture_inventory),
            },
            "target_count": len(files_out),
        },
        "dependencies": project_map.get("dependencies", {}),
        "recent_changes": (project_map.get("recent_changes") or project_map.get("changed_files") or []),
        "needs_broader_context": needs_broader,
        "needs_broader_context_reason": "; ".join(reasons) if reasons else "",
        "drilldown": {
            "reversible": True,
            "handles": [handle for entry in files_out for handle in entry["drilldown"]["handles"]],
        },
        "llm_directives": LLM_DIRECTIVES,
        "relation_coverage": cg_coverage,
    }
    payload = apply_task_context(
        payload,
        target_rows=target_rows,
        project_map=project_map,
        goal=goal,
        task_intent=task_intent,
        task_fingerprint=task_fingerprint,
        target=target,
        query_terms=query_terms,
        minimum_query_coverage=minimum_query_coverage,
        token_budget=token_budget,
    )
    if context_snapshot is not None:
        payload["source_snapshot"] = {
            "snapshot_id": context_snapshot["snapshot_id"],
            "revision": context_snapshot["revision"],
            "source_digest": canonical_sha256(context_snapshot),
            "root_hash": context_snapshot["root_hash"],
        }
    payload["fidelity"] = {
        "status": "partial" if payload.get("needs_broader_context") else "sufficient",
        "gate": "needs_broader_context" if payload.get("needs_broader_context") else "ready",
        "reasons": [
            piece.strip()
            for piece in str(payload.get("needs_broader_context_reason", "")).split(";")
            if piece.strip()
        ],
        "query_coverage": dict(payload.get("query_coverage", {})),
        "scale_coverage": _scale_summary(payload.get("files", [])),
    }
    if "serialization_budget" in payload:
        budget = payload["serialization_budget"]
        payload = enforce_serialized_budget(
            payload,
            token_budget=int(budget["token_budget"]),
            estimated_tokens=int(budget.get("estimated_tokens", 0)),
        )
    return payload


__all__ = [
    "COMPACT_LINE_THRESHOLD",
    "CONTEXT_PACK_SCHEMA",
    "LLM_DIRECTIVES",
    "MAPPER_INDEX_SCHEMA",
    "build_context_pack",
    "select_context_targets",
]
