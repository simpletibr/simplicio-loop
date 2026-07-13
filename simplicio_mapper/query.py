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
import sys
from collections import deque
from functools import lru_cache
from typing import Any

from .context_cache import ContextCache, ContextCacheKey, LAYER_CONTEXT_SUMMARY, LAYER_RUNTIME_PROVIDER
from .docsync import _flows_touching, _scan_manual_docs_for_references, _symbols_for_files
from .flows import build_flow_inventory
from .mapper import _parse_json_safe, build_artifacts
from .savings import estimate_tokens, record_savings_event

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
_PRECEDENT_SCHEMA = "simplicio.precedent-search/v1"

# `impact` and `tests-for` are native-first too (issue #174), same pattern as
# `precedent` above: shell out to the `simplicio` runtime binary when it is
# on PATH and its response validates, falling back to the local Python
# computation (`_impact`/`_tests_for`) otherwise. Chosen over the other `ask`
# verbs based on real measurement (`scripts/measure_verbs.py`,
# `scripts/measure_verbs_report.json`) -- isolated from the fixed
# `build_artifacts()` cost every `ask` call already pays, `impact` and
# `tests-for` are respectively ~36x and ~8x more expensive than the cheapest
# verb (`callers`/`callees`), because `impact` recomputes a fresh
# flow-inventory and scans every spec/doc file on each call, and `tests-for`
# reads the full text of every test file on each call.
_ASK_RUNTIME_BINARY = "simplicio"
_ASK_NATIVE_VERBS = {
    "impact": "SIMPLICIO_MAPPER_NO_RUNTIME_IMPACT",
    "tests-for": "SIMPLICIO_MAPPER_NO_RUNTIME_TESTS_FOR",
}
_RUNTIME_VERSION_PREFIX = "Simplicio Runtime "
_RUNTIME_CAPABILITY_SCHEMA = "simplicio.capability-list/v1"
_RUNTIME_MAPPER_CAPABILITY = "simplicio-mapper"
_QUERY_CACHE_POLICY_VERSION = "run-query-native-first/v2"
_QUERY_CACHE_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".simplicio",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
}


def _runtime_argv(binary: str, *args: str) -> list[str]:
    # Test/runtime shims can be Python scripts; Windows cannot exec their
    # shebang directly, so invoke them through the current interpreter.
    prefix = [sys.executable, binary] if binary.lower().endswith(".py") else [binary]
    return [*prefix, *args]


def _json_object_from_output(text: str, schema: str) -> dict | None:
    """Find a schema-matching JSON object in output that may contain progress lines."""
    for line in reversed(text.splitlines()):
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("schema") == schema:
            return payload
    return None


def _normalize_relpath(path: str) -> str:
    return path.replace(os.sep, "/")


def _cache_path(root: str, out_dir: str) -> str:
    return os.path.join(os.path.abspath(root), out_dir, "context-cache.json")


def _repo_identity(root: str) -> str:
    pkg = _parse_json_safe(os.path.join(root, "package.json")) or {}
    name = pkg.get("name") if isinstance(pkg, dict) else None
    if isinstance(name, str) and name.strip():
        return name.strip()
    return os.path.basename(root.rstrip("\\/")) or "."


def _query_cacheable_paths(root: str, out_dir: str) -> list[str]:
    abs_root = os.path.abspath(root)
    abs_out = os.path.abspath(os.path.join(abs_root, out_dir))
    rel_paths: list[str] = []
    for current_root, dirs, files in os.walk(abs_root):
        dirs[:] = [
            d for d in dirs
            if d not in _QUERY_CACHE_SKIP_DIRS
            and os.path.abspath(os.path.join(current_root, d)) != abs_out
        ]
        for filename in files:
            full = os.path.join(current_root, filename)
            if os.path.abspath(full) == os.path.abspath(_cache_path(abs_root, out_dir)):
                continue
            try:
                rel = os.path.relpath(full, abs_root)
            except ValueError:
                continue
            rel_paths.append(_normalize_relpath(rel))
    rel_paths.sort()
    return rel_paths


def _query_cache_key(root: str, out_dir: str, query: dict[str, Any]) -> ContextCacheKey:
    return ContextCacheKey.for_files(
        root,
        _query_cacheable_paths(root, out_dir),
        repo_identity=_repo_identity(root),
        mapper_schema_version=ASK_SCHEMA,
        parser_version=f"python-{sys.version_info.major}.{sys.version_info.minor}",
        query_task_hash=json.dumps(query, sort_keys=True),
        retrieval_policy_version=_QUERY_CACHE_POLICY_VERSION,
        token_budget=int(query.get("limit") or 0),
        renderer=query.get("verb", ""),
        output_format=ASK_SCHEMA,
    )


def _cache_block(cache: ContextCache, key_hash: str, receipt: dict) -> dict:
    return {
        "key_hash": key_hash,
        "receipt": receipt,
        "diagnostics": cache.explain(key_hash),
    }


def _validated_runtime_binary(binary: str) -> tuple[bool, str]:
    """Reject homonymous ``simplicio`` executables before native delegation."""
    try:
        version = subprocess.run(
            _runtime_argv(binary, "--version"),
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return False, "identity_probe_failed"
    if version.returncode != 0 or not version.stdout.strip().startswith(_RUNTIME_VERSION_PREFIX):
        return False, "identity_mismatch"
    try:
        capabilities = subprocess.run(
            _runtime_argv(binary, "capabilities", "list", "--json"),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False, "capability_probe_failed"
    if capabilities.returncode != 0:
        return False, "capability_probe_failed"
    payload = _json_object_from_output(capabilities.stdout, _RUNTIME_CAPABILITY_SCHEMA)
    if payload is None:
        return False, "capability_schema_mismatch"
    items = payload.get("items")
    if not isinstance(items, list) or not any(
        isinstance(item, dict)
        and item.get("id") == _RUNTIME_MAPPER_CAPABILITY
        and item.get("status") in ("available", "installed")
        for item in items
    ):
        return False, "mapper_capability_missing"
    return True, "validated"


@lru_cache(maxsize=8)
def _cached_runtime_validation(binary: str, mtime_ns: int, size: int) -> tuple[bool, str]:
    del mtime_ns, size  # Cache invalidators, not probe inputs.
    return _validated_runtime_binary(binary)


def _runtime_target(binary_name: str) -> tuple[str | None, str]:
    binary = shutil.which(binary_name)
    if not binary:
        return None, "binary_missing"
    try:
        stat = os.stat(binary)
    except OSError:
        valid, reason = _validated_runtime_binary(binary)
    else:
        # Python development shims stay uncached so their controlled test
        # modes remain observable; installed executables are re-probed only
        # when mtime or size changes.
        if binary.lower().endswith(".py"):
            valid, reason = _validated_runtime_binary(binary)
        else:
            valid, reason = _cached_runtime_validation(binary, stat.st_mtime_ns, stat.st_size)
    return (binary, "validated") if valid else (None, reason)


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
        edge
        for edge in call_graph.get("edges", [])
        if edge.get("type") == "calls" and edge.get("target_symbol") == name
    ]
    matches.sort(key=lambda e: (e.get("source_file") or "", e.get("line") or 0))
    return matches[:limit], len(matches)


def _callees(call_graph: dict, name: str, limit: int) -> tuple[list[dict], int]:
    matches = [
        edge
        for edge in call_graph.get("edges", [])
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


def _runtime_precedent_search(cwd: str, text: str, top_n: int) -> tuple[dict | None, str]:
    """Shell out to the `simplicio` runtime's precedent search (SQLite/FTS5
    lexical ranking + a git-apply dry-run reuse-safety check).

    Returns the parsed ``simplicio.precedent-search/v1`` payload, or
    ``None`` on any failure — binary missing, kill-switch set, non-zero
    exit, timeout, or malformed JSON — so the caller always has a safe
    local fallback. Never raises.
    """
    if os.environ.get(_PRECEDENT_NO_RUNTIME_ENV):
        return None, "kill_switch"
    binary, reason = _runtime_target(_PRECEDENT_RUNTIME_BINARY)
    if not binary:
        return None, reason
    try:
        result = subprocess.run(
            _runtime_argv(
                binary,
                "precedent",
                "search",
                "--repo",
                cwd,
                "--text",
                text,
                "--top",
                str(top_n),
                "--json",
            ),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None, "command_failed"
    if result.returncode != 0:
        return None, "command_failed"
    payload = _json_object_from_output(result.stdout, _PRECEDENT_SCHEMA)
    if payload is None or not isinstance(payload.get("candidates"), list):
        return None, "invalid_response_schema"
    return payload, "delegated"


def _runtime_ask_query(cwd: str, verb: str, arg: str, limit: int) -> tuple[dict | None, str]:
    """Shell out to the `simplicio` runtime binary for a native `ask <verb>`
    answer (`impact`/`tests-for` only, issue #174 -- same pattern as
    ``_runtime_precedent_search`` above).

    Returns the parsed ``simplicio.ask/v1`` payload (``results``/``total``
    only), or ``None`` on any failure -- binary missing, kill-switch set,
    non-zero exit, timeout, or a response that does not validate against the
    ``simplicio.ask/v1`` envelope -- so the caller always has a safe local
    fallback. Never raises.
    """
    env_var = _ASK_NATIVE_VERBS.get(verb)
    if env_var is None:
        return None, "unsupported_verb"
    if os.environ.get(env_var):
        return None, "kill_switch"
    if not arg:
        return None, "missing_argument"
    binary, reason = _runtime_target(_ASK_RUNTIME_BINARY)
    if not binary:
        return None, reason
    try:
        result = subprocess.run(
            _runtime_argv(binary, "ask", verb, "--repo", cwd, "--arg", arg, "--limit", str(limit), "--json"),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None, "command_failed"
    if result.returncode != 0:
        return None, "command_failed"
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        return None, "invalid_response_json"
    if not isinstance(payload, dict) or payload.get("schema") != ASK_SCHEMA:
        return None, "invalid_response_schema"
    if "results" not in payload or "total" not in payload:
        return None, "invalid_response_schema"
    return payload, "delegated"


def _record_ask_native_savings(cwd: str, verb: str, baseline_tokens: int, payload: dict, note: str) -> None:
    """Best-effort savings-ledger receipt for a native `ask` hit. Never
    raises -- a ledger write failure must never break the query path."""
    try:
        actual_tokens = estimate_tokens(json.dumps(payload, sort_keys=True))
        record_savings_event(
            cwd,
            source=f"native-delegation:{verb}",
            baseline_tokens=baseline_tokens,
            actual_tokens=actual_tokens,
            proof_kind="estimated",
            note=note,
        )
    except Exception:  # noqa: BLE001 - savings receipts are best-effort only
        return


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
    cache = ContextCache(_cache_path(abs_cwd, out_dir))
    artifacts: dict[str, Any] | None = None

    def _artifacts() -> dict[str, Any]:
        nonlocal artifacts
        if artifacts is None:
            artifacts = build_artifacts(abs_cwd, output_dir=out_dir)
        return artifacts

    query: dict[str, Any] = {"verb": verb}
    if arg:
        query["arg"] = arg
    query["limit"] = limit
    if verb == "reaches":
        query["depth"] = depth
    if verb == "flows" and effect:
        query["effect"] = effect
    if verb == "rules" and category:
        query["category"] = category

    note = None
    if verb == "callers":
        materialized = _artifacts()
        symbol_index = materialized["symbol_index"]
        call_graph = materialized["call_graph"]
        resolved = _resolve_symbol_name(symbol_index, arg or "")
        matches, total = _callers(call_graph, resolved, limit)
        payload = {"results": [_edge_view(e) for e in matches], "total": total}
    elif verb == "callees":
        materialized = _artifacts()
        symbol_index = materialized["symbol_index"]
        call_graph = materialized["call_graph"]
        resolved = _resolve_symbol_name(symbol_index, arg or "")
        matches, total = _callees(call_graph, resolved, limit)
        payload = {"results": [_edge_view(e) for e in matches], "total": total}
    elif verb == "reaches":
        materialized = _artifacts()
        call_graph = materialized["call_graph"]
        matches, total = _reaches(call_graph, arg or "", depth, limit)
        payload = {"results": matches, "total": total}
    elif verb == "impact":
        native, delegation_reason = _runtime_ask_query(abs_cwd, "impact", arg or "", limit)
        if native is not None:
            payload = {"results": native["results"], "total": native["total"], "source": "runtime-ask-impact"}
            native_key = ContextCacheKey(
                repo_identity=_repo_identity(abs_cwd),
                mapper_schema_version=ASK_SCHEMA,
                parser_version=f"python-{sys.version_info.major}.{sys.version_info.minor}",
                query_task_hash=json.dumps(query, sort_keys=True),
                retrieval_policy_version=_QUERY_CACHE_POLICY_VERSION,
                token_budget=limit,
                renderer=verb,
                output_format=ASK_SCHEMA,
            )
            receipt = cache.record_bypass(
                LAYER_RUNTIME_PROVIDER,
                native_key.content_hash(),
                reason="native-first-satisfied",
                kind="provider",
                baseline="local build_artifacts + impact fallback",
                method="runtime-native ask impact",
            )
            payload["cache"] = _cache_block(cache, native_key.content_hash(), receipt.to_dict())
        else:
            cache_key = _query_cache_key(abs_cwd, out_dir, query)
            cached_payload, receipt = cache.get_entry(LAYER_CONTEXT_SUMMARY, cache_key)
            if cached_payload is not None:
                payload = dict(cached_payload)
                payload["cache"] = _cache_block(cache, cache_key.content_hash(), receipt.to_dict())
            else:
                materialized = _artifacts()
                impact = _impact(abs_cwd, materialized, [arg] if arg else [])
                total = (
                    len(impact["affected_symbols"]) + len(impact["affected_flows"]) + len(impact["needs_review"])
                )
                payload = {"results": impact, "total": total, "source": "local-python"}
                cache.put(
                    LAYER_CONTEXT_SUMMARY,
                    cache_key,
                    payload,
                    bytes_avoided=len(json.dumps(payload, sort_keys=True).encode("utf-8")),
                )
                payload["cache"] = _cache_block(cache, cache_key.content_hash(), receipt.to_dict())
                baseline = estimate_tokens(json.dumps(materialized.get("call_graph"), sort_keys=True)) + estimate_tokens(
                    json.dumps(materialized.get("symbol_index"), sort_keys=True)
                )
                _record_ask_native_savings(
                    abs_cwd,
                    "impact",
                    baseline,
                    payload,
                    note="baseline=call_graph+symbol_index the LLM/loop would otherwise have to read "
                    "to answer 'what does changing this file affect' manually; method=heuristic:chars-div-4",
                )
        payload["delegation"] = {
            "runtime": "simplicio-runtime",
            "used": native is not None,
            "reason": delegation_reason,
        }
    elif verb == "flows":
        materialized = _artifacts()
        flow_inventory = build_flow_inventory(abs_cwd, materialized)
        flows = flow_inventory["flows"]
        if effect:
            flows = [f for f in flows if any(e["type"] == effect for e in f["effects"])]
        payload = {"results": flows[:limit], "total": len(flows)}
    elif verb == "tests-for":
        native, delegation_reason = _runtime_ask_query(abs_cwd, "tests-for", arg or "", limit)
        if native is not None:
            payload = {
                "results": native["results"],
                "total": native["total"],
                "source": "runtime-ask-tests-for",
            }
            native_key = ContextCacheKey(
                repo_identity=_repo_identity(abs_cwd),
                mapper_schema_version=ASK_SCHEMA,
                parser_version=f"python-{sys.version_info.major}.{sys.version_info.minor}",
                query_task_hash=json.dumps(query, sort_keys=True),
                retrieval_policy_version=_QUERY_CACHE_POLICY_VERSION,
                token_budget=limit,
                renderer=verb,
                output_format=ASK_SCHEMA,
            )
            receipt = cache.record_bypass(
                LAYER_RUNTIME_PROVIDER,
                native_key.content_hash(),
                reason="native-first-satisfied",
                kind="provider",
                baseline="local build_artifacts + tests-for fallback",
                method="runtime-native ask tests-for",
            )
            payload["cache"] = _cache_block(cache, native_key.content_hash(), receipt.to_dict())
        else:
            cache_key = _query_cache_key(abs_cwd, out_dir, query)
            cached_payload, receipt = cache.get_entry(LAYER_CONTEXT_SUMMARY, cache_key)
            if cached_payload is not None:
                payload = dict(cached_payload)
                payload["cache"] = _cache_block(cache, cache_key.content_hash(), receipt.to_dict())
            else:
                materialized = _artifacts()
                project_map = materialized["project_map"]
                matches, total = _tests_for(abs_cwd, project_map, arg or "", limit)
                payload = {"results": matches, "total": total, "source": "local-python"}
                cache.put(
                    LAYER_CONTEXT_SUMMARY,
                    cache_key,
                    payload,
                    bytes_avoided=len(json.dumps(payload, sort_keys=True).encode("utf-8")),
                )
                payload["cache"] = _cache_block(cache, cache_key.content_hash(), receipt.to_dict())
                baseline = sum(estimate_tokens(_read_text(abs_cwd, f)) for f in project_map.get("test_files") or [])
                _record_ask_native_savings(
                    abs_cwd,
                    "tests-for",
                    baseline,
                    payload,
                    note="baseline=full text of every test file the local fallback would otherwise "
                    "read in full to find matches; method=heuristic:chars-div-4",
                )
        payload["delegation"] = {
            "runtime": "simplicio-runtime",
            "used": native is not None,
            "reason": delegation_reason,
        }
    elif verb == "precedent":
        text = arg or ""
        top_n = min(limit, _PRECEDENT_TOP_N)
        if text:
            native, delegation_reason = _runtime_precedent_search(abs_cwd, text, top_n)
        else:
            native, delegation_reason = None, "missing_argument"
        if native is not None:
            candidates = native.get("candidates") or []
            results = [_candidate_view(c) for c in candidates[:top_n]]
            payload = {"results": results, "total": len(candidates), "source": "runtime-precedent-search"}
            if not results and native.get("suggested_next_action"):
                note = native["suggested_next_action"]
            native_key = ContextCacheKey(
                repo_identity=_repo_identity(abs_cwd),
                mapper_schema_version=ASK_SCHEMA,
                parser_version=f"python-{sys.version_info.major}.{sys.version_info.minor}",
                query_task_hash=json.dumps(query, sort_keys=True),
                retrieval_policy_version=_QUERY_CACHE_POLICY_VERSION,
                token_budget=limit,
                renderer=verb,
                output_format=ASK_SCHEMA,
            )
            receipt = cache.record_bypass(
                LAYER_RUNTIME_PROVIDER,
                native_key.content_hash(),
                reason="native-first-satisfied",
                kind="provider",
                baseline="local build_artifacts + precedent fallback",
                method="runtime-native precedent search",
            )
            payload["cache"] = _cache_block(cache, native_key.content_hash(), receipt.to_dict())
        else:
            cache_key = _query_cache_key(abs_cwd, out_dir, query)
            cached_payload, receipt = cache.get_entry(LAYER_CONTEXT_SUMMARY, cache_key)
            if cached_payload is not None:
                payload = dict(cached_payload)
                payload["cache"] = _cache_block(cache, cache_key.content_hash(), receipt.to_dict())
            else:
                materialized = _artifacts()
                items = materialized["precedent_index"].get("items") or []
                matches = _local_precedent_fallback(items, text, top_n)
                payload = {"results": matches, "total": len(matches), "source": "local-tag-overlap"}
                cache.put(
                    LAYER_CONTEXT_SUMMARY,
                    cache_key,
                    payload,
                    bytes_avoided=len(json.dumps(payload, sort_keys=True).encode("utf-8")),
                )
                payload["cache"] = _cache_block(cache, cache_key.content_hash(), receipt.to_dict())
        payload["delegation"] = {
            "runtime": "simplicio-runtime",
            "used": native is not None,
            "reason": delegation_reason,
        }
    elif verb in ("rules", "term"):
        _artifacts()
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
