"""Canonical, deterministic per-task execution context (issue #350)."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .context_snapshot import build_context_snapshot
from .query import _local_precedent_fallback, _tokenize
from .retrieval_index import (
    DEFAULT_TOKEN_BUDGET,
    TOKENIZER_POLICY,
    _expand_handle,
    resolve_expand_handle,
    serialized_json_bytes,
    serialized_token_count,
)

EXECUTION_CONTEXT_SCHEMA = "simplicio.execution-context/v1"
SCHEMA_VERSION = 1

_SECRET_PATH_PARTS = {
    ".env",
    ".npmrc",
    ".pypirc",
    "credentials",
    "id_rsa",
    "id_dsa",
    "id_ed25519",
    "secrets",
}
_SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".keystore"}
_NAMED_SECRET = re.compile(
    r"(?i)(?P<name>(?:"
    r"aws_(?:access_key_id|secret_access_key|session_token)|"
    r"github_token|api[_-]?key|access[_-]?token|refresh[_-]?token|token|"
    r"password|passwd|client[_-]?secret|secret|private[_-]?key"
    r")\s*[:=]\s*)(?P<value>[^\s,;\"']+|[\"'][^\"']*[\"'])"
)
_CREDENTIAL_URL = re.compile(
    r"(?i)(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<user>[^/\s:@]+):(?P<password>[^@\s/]+)@"
)
_BEARER_SECRET = re.compile(
    r"(?i)(?P<prefix>\b(?:authorization\s*:\s*)?bearer\s+)(?P<value>[a-z0-9._~+/=-]{8,})"
)
_GITHUB_SECRET = re.compile(r"\b(?:github_pat_[A-Za-z0-9_]{10,}|gh[pousr]_[A-Za-z0-9]{20,})\b")
_JWT_SECRET = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")
_AWS_ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")


class ExecutionContextError(ValueError):
    """The requested execution context cannot be safely resolved."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _envelope_hash(payload: Mapping[str, Any]) -> str:
    """Hash semantic content, excluding identity and self-measurement fields."""
    addressable = {key: value for key, value in payload.items() if key != "envelope_hash"}
    raw_budget = addressable.get("token_budget")
    if isinstance(raw_budget, Mapping):
        budget = dict(raw_budget)
        for field in ("serialized_tokens", "serialized_bytes", "within_budget"):
            budget.pop(field, None)
        addressable["token_budget"] = budget
    return _canonical_hash(addressable)


def _normalize_path(path: str) -> str:
    normalized = path.replace(os.sep, "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _path_reason(root: str, path: str) -> str:
    normalized = _normalize_path(path)
    absolute_root = os.path.realpath(root)
    absolute_path = os.path.realpath(os.path.join(absolute_root, normalized))
    try:
        authorized = os.path.commonpath([absolute_root, absolute_path]) == absolute_root
    except ValueError:
        authorized = False
    if not authorized:
        return "outside_authorized_root"
    real_relative = _normalize_path(os.path.relpath(absolute_path, absolute_root))
    for candidate in (normalized, real_relative):
        parts = {part.casefold() for part in candidate.split("/")}
        basename = os.path.basename(candidate).casefold()
        if parts & _SECRET_PATH_PARTS or any(
            part.startswith(".env.") or "credential" in part or "secret" in part for part in parts
        ):
            return "secret_path"
        if os.path.splitext(basename)[1] in _SECRET_SUFFIXES:
            return "secret_path"
    return ""


def _read_text(root: str, path: str) -> tuple[str | None, str]:
    reason = _path_reason(root, path)
    if reason:
        return None, reason
    absolute_path = os.path.realpath(os.path.join(root, _normalize_path(path)))
    try:
        with open(absolute_path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None, "unreadable_file"
    if b"\x00" in raw:
        return None, "binary_file"
    try:
        return raw.decode("utf-8"), ""
    except UnicodeDecodeError:
        return None, "binary_file"


def _redact_text(text: str) -> tuple[str, int]:
    count = 0

    def replace_named(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{match.group('name')}<redacted>"

    def replace_url(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{match.group('scheme')}{match.group('user')}:<redacted>@"

    def replace_bearer(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{match.group('prefix')}<redacted>"

    def replace_bare(_match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return "<redacted>"

    safe = _CREDENTIAL_URL.sub(replace_url, text)
    safe = _BEARER_SECRET.sub(replace_bearer, safe)
    safe = _NAMED_SECRET.sub(replace_named, safe)
    for pattern in (_GITHUB_SECRET, _JWT_SECRET, _AWS_ACCESS_KEY):
        safe = pattern.sub(replace_bare, safe)
    return safe, count


def _redact_payload_values(
    value: Any,
    redactions: list[dict[str, Any]],
    *,
    location: str = "$",
) -> Any:
    """Redact credential-shaped strings recursively at the envelope boundary."""
    if isinstance(value, str):
        safe, count = _redact_text(value)
        if count:
            redactions.append(
                {
                    "path": location,
                    "reason": "secret_value",
                    "count": count,
                }
            )
        return safe
    if isinstance(value, list):
        return [
            _redact_payload_values(item, redactions, location=f"{location}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, Mapping):
        return {
            key: _redact_payload_values(item, redactions, location=f"{location}.{key}")
            for key, item in value.items()
        }
    return value


def _span_rows(
    *,
    root: str,
    path: str,
    text: str,
    expanded: Mapping[str, Any],
    redactions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lines = text.splitlines()
    source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    expansion_handle = str(expanded.get("expand_handle") or "")
    if not expansion_handle:
        expansion_handle = _expand_handle(root, path, source_hash, kind="full")
    spans = list(expanded.get("spans", []))
    out: list[dict[str, Any]] = []
    for span in spans:
        start = max(1, int(span.get("start_line", 1) or 1))
        end = min(len(lines), int(span.get("end_line", start) or start))
        if end < start:
            continue
        exact = "\n".join(lines[start - 1 : end])
        safe, count = _redact_text(exact)
        if count:
            redactions.append(
                {
                    "path": path,
                    "reason": "secret_value",
                    "span": [start, end],
                    "count": count,
                }
            )
        out.append(
            {
                "start_line": start,
                "end_line": end,
                "kind": str(span.get("kind") or "source"),
                "symbol": span.get("symbol"),
                "span_hash": hashlib.sha256(exact.encode("utf-8")).hexdigest(),
                "text": safe,
                "expansion_handle": expansion_handle,
            }
        )
    return out


def _selected_sources(
    root: str,
    selection: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    expanded_by_path = {
        _normalize_path(str(row.get("path") or "")): row
        for row in selection.get("expanded_spans", [])
        if isinstance(row, Mapping) and row.get("path")
    }
    sources: list[dict[str, Any]] = []
    redactions: list[dict[str, Any]] = []
    for rank, target in enumerate(selection.get("targets", []), start=1):
        if not isinstance(target, Mapping) or not target.get("path"):
            continue
        path = _normalize_path(str(target["path"]))
        text, reason = _read_text(root, path)
        if text is None:
            redactions.append({"path": path, "reason": reason})
            continue
        expanded = expanded_by_path.get(path, {})
        spans = _span_rows(root=root, path=path, text=text, expanded=expanded, redactions=redactions)
        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        expansion_handle = (
            spans[0]["expansion_handle"]
            if spans
            else str(expanded.get("expand_handle") or _expand_handle(root, path, source_hash[:16]))
        )
        sources.append(
            {
                "path": path,
                "rank": rank,
                "language": str(target.get("language") or ""),
                "relevance_score": float(target.get("relevance_score", 0.0) or 0.0),
                "reason_codes": sorted(str(code) for code in target.get("reason_codes", [])),
                "source_hash": source_hash,
                "line_count": len(text.splitlines()),
                "symbols": sorted(str(value) for value in target.get("symbol_matches", [])),
                "spans": spans,
                "expansion_handle": expansion_handle,
            }
        )
    sources.sort(key=lambda item: (item["rank"], item["path"]))
    redactions.sort(key=lambda item: (item["path"], item["reason"], item.get("span", [])))
    return sources, redactions


def _graph_evidence(
    root: str,
    call_graph: Mapping[str, Any],
    selected_paths: set[str],
    redactions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for edge in call_graph.get("edges", []):
        if not isinstance(edge, Mapping):
            continue
        source = _normalize_path(str(edge.get("source_file") or edge.get("from") or ""))
        target = _normalize_path(str(edge.get("target_file") or edge.get("to") or ""))
        if not source or not target or not ({source, target} & selected_paths):
            continue
        unsafe = [(path, _path_reason(root, path)) for path in (source, target)]
        if any(reason for _, reason in unsafe):
            redactions.extend(
                {"path": path, "reason": reason, "evidence_kind": "graph_edge"}
                for path, reason in unsafe
                if reason
            )
            continue
        out.append(
            {
                "kind": str(edge.get("type") or "depends_on"),
                "source": source,
                "target": target,
                "dependency_distance": 0 if source == target else 1,
                "confidence": edge.get("confidence"),
                "provenance": "call-graph",
                "source_handle": {
                    "path": source,
                    "line": int(edge.get("line", 0) or 0) or None,
                },
                "edge_hash": _canonical_hash(edge),
            }
        )
    return sorted(out, key=lambda item: (item["dependency_distance"], item["source"], item["target"], item["kind"]))


def _test_evidence(
    root: str,
    selection: Mapping[str, Any],
    selected_paths: set[str],
    redactions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in selection.get("expanded_spans", []):
        if not isinstance(row, Mapping):
            continue
        source = _normalize_path(str(row.get("path") or ""))
        for path in row.get("tests", []):
            normalized = _normalize_path(str(path))
            if reason := _path_reason(root, normalized):
                redactions.append(
                    {"path": normalized, "reason": reason, "evidence_kind": "related_test"}
                )
                continue
            out[normalized] = {
                "path": normalized,
                "verifies": source,
                "route": f"python -m pytest {normalized}",
                "confidence": 1.0 if source in selected_paths else 0.5,
                "provenance": "retrieval-index:related-tests",
            }
    return [out[path] for path in sorted(out)]


def _precedent_evidence(
    root: str,
    precedent_index: Mapping[str, Any],
    goal: str,
    redactions: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    matches = _local_precedent_fallback(list(precedent_index.get("items", [])), goal, limit)
    query_tokens = _tokenize(goal)
    out: list[dict[str, Any]] = []
    for item in matches:
        path = _normalize_path(str(item.get("path") or ""))
        if reason := _path_reason(root, path):
            redactions.append({"path": path, "reason": reason, "evidence_kind": "precedent"})
            continue
        haystack = " ".join(item.get("tags") or []) + " " + str(item.get("summary") or "")
        overlap = len(query_tokens & _tokenize(haystack))
        snippet, redacted = _redact_text(str(item.get("snippet") or ""))
        if redacted:
            redactions.append(
                {
                    "path": path,
                    "reason": "secret_value",
                    "evidence_kind": "precedent",
                    "count": redacted,
                }
            )
        out.append(
            {
                "id": str(item.get("id") or item.get("precedent_id") or ""),
                "path": path,
                "line": item.get("line"),
                "summary": str(item.get("summary") or ""),
                "snippet": snippet,
                "confidence": {
                    "value": overlap,
                    "semantics": "keyword_overlap_count",
                    "measured": False,
                },
                "provenance": "precedent-index:local-keyword-overlap",
                "redacted_values": redacted,
            }
        )
    return out


def _fit_budget(payload: dict[str, Any], token_budget: int) -> None:
    omissions = payload["omissions"]
    payload["token_budget"] = {
        "requested_tokens": int(token_budget),
        "serialized_tokens": 0,
        "serialized_bytes": 0,
        "tokenizer_policy": TOKENIZER_POLICY,
        "measurement": "MEASURED",
        "within_budget": False,
    }
    payload["envelope_hash"] = _envelope_hash(payload)
    for field, kind in (
        ("precedents", "precedent"),
        ("graph_edges", "graph_edge"),
        ("related_tests", "related_test"),
    ):
        while payload[field] and serialized_token_count(payload) > token_budget:
            removed = payload[field].pop()
            source_handle = removed.get("expansion_handle") or removed.get("source_handle")
            if not source_handle and removed.get("path"):
                source_handle = {
                    "path": removed["path"],
                    "line": removed.get("line"),
                }
            omissions.append(
                {
                    "kind": kind,
                    "reason": "token_budget",
                    "expansion_handle": source_handle,
                }
            )
            payload["envelope_hash"] = _envelope_hash(payload)
    token_count = serialized_token_count(payload)
    within = token_count <= token_budget
    payload["token_budget"]["serialized_tokens"] = token_count
    payload["token_budget"]["serialized_bytes"] = len(serialized_json_bytes(payload))
    payload["token_budget"]["within_budget"] = within
    if not within:
        abstention_reasons = set(payload["abstention"].get("reasons", []))
        abstention_reasons.add("required_metadata_exceeds_budget")
        payload["abstention"] = {
            "abstained": True,
            "reasons": sorted(abstention_reasons),
        }
        payload["needs_broader_context"] = True
        payload["fidelity"]["sufficient"] = False
        fidelity_reasons = set(payload["fidelity"].get("reasons", []))
        fidelity_reasons.add("required_metadata_exceeds_budget")
        payload["fidelity"]["reasons"] = sorted(fidelity_reasons)
        budget_queries = [
            f"raise --token-budget above {token_count}",
            "tighten --target or goal to reduce required exact spans",
        ]
        payload["next_queries"] = list(dict.fromkeys([*payload["next_queries"], *budget_queries]))


def _stamp_hash_and_measurement(payload: dict[str, Any]) -> None:
    payload["envelope_hash"] = _envelope_hash(payload)
    previous: tuple[int, int] | None = None
    for _ in range(8):
        count = serialized_token_count(payload)
        size = len(serialized_json_bytes(payload))
        payload["token_budget"]["serialized_tokens"] = count
        payload["token_budget"]["serialized_bytes"] = size
        payload["token_budget"]["within_budget"] = count <= payload["token_budget"]["requested_tokens"]
        current = (count, size)
        if current == previous:
            break
        previous = current


def build_execution_context(
    root: str,
    *,
    goal: str,
    task_fingerprint: str = "",
    acceptance_criteria: Sequence[str] = (),
    task_intent: Mapping[str, Any] | None = None,
    project_map: Mapping[str, Any],
    symbol_index: Mapping[str, Any],
    call_graph: Mapping[str, Any],
    precedent_index: Mapping[str, Any] | None,
    selection: Mapping[str, Any],
    context_pack: Mapping[str, Any] | None = None,
    architecture_inventory: Mapping[str, Any] | None = None,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> dict[str, Any]:
    """Compose already-ranked mapper evidence for exactly one task."""
    if token_budget <= 0:
        raise ExecutionContextError("token_budget must be positive")
    sources, redactions = _selected_sources(root, selection)
    selected_paths = {source["path"] for source in sources}
    has_exact_spans = any(source["spans"] for source in sources)
    task_descriptor = {
        "goal": goal.strip(),
        "acceptance_criteria": sorted({str(value) for value in acceptance_criteria if str(value)}),
        "intent_fingerprint": str((task_intent or {}).get("fingerprint") or ""),
    }
    fingerprint = task_fingerprint.strip() or _canonical_hash(task_descriptor)
    snapshot = build_context_snapshot(
        root,
        project_map=project_map,
        symbol_index=symbol_index,
        call_graph=call_graph,
        architecture_inventory=architecture_inventory or {},
        task_query=goal,
        budget_tokens=token_budget,
    )
    selection_fidelity = dict(selection.get("fidelity", {}))
    abstained = (
        not sources
        or not has_exact_spans
        or bool(selection.get("abstained"))
        or not bool(selection_fidelity.get("sufficient"))
    )
    reasons = []
    if not sources:
        reasons.append("no_safe_relevant_sources")
    elif not has_exact_spans:
        reasons.append("exact_spans_omitted")
    if selection.get("abstention_reason"):
        reasons.append(str(selection["abstention_reason"]))
    reasons.extend(str(value) for value in selection_fidelity.get("reasons", []))
    omissions = [
        {
            "kind": "source_content",
            "reason": "selection_pointer_only",
            "expansion_handle": source["expansion_handle"],
        }
        for source in sources
        if not source["spans"]
    ]
    fidelity_reasons = [str(value) for value in selection_fidelity.get("reasons", [])]
    if not has_exact_spans and "exact_spans_omitted" not in fidelity_reasons:
        fidelity_reasons.append("exact_spans_omitted")
    next_queries = list(
        selection.get("broader_context", [])
        or (selection.get("token_budget_fit", {}) or {}).get("broader_context", [])
    )
    if not has_exact_spans and "resolve source expansion handles" not in next_queries:
        next_queries.append("resolve source expansion handles")
    payload: dict[str, Any] = {
        "schema": EXECUTION_CONTEXT_SCHEMA,
        "task": {
            "fingerprint": fingerprint,
            **task_descriptor,
        },
        "repository": {
            "id": snapshot["repository_id"],
            "root_hash": snapshot["root_hash"],
            "map_hash": _canonical_hash(project_map),
            "snapshot_id": snapshot["snapshot_id"],
            "context_pack_hash": str((context_pack or {}).get("pack_hash") or ""),
            "artifact_hashes": snapshot["freshness"]["artifact_hashes"],
        },
        "sources": sources,
        "graph_edges": _graph_evidence(root, call_graph, selected_paths, redactions),
        "related_tests": _test_evidence(root, selection, selected_paths, redactions),
        "precedents": _precedent_evidence(root, precedent_index or {}, goal, redactions),
        "fidelity": {
            "sufficient": (
                bool(selection_fidelity.get("sufficient"))
                and bool(sources)
                and has_exact_spans
            ),
            "vector": dict(selection_fidelity.get("dimensions", {})),
            "coverage_ratio": selection_fidelity.get("coverage_ratio", 0.0),
            "reasons": sorted(fidelity_reasons),
        },
        "omissions": omissions,
        "abstention": {"abstained": abstained, "reasons": sorted(set(reasons))},
        "needs_broader_context": abstained or bool(selection.get("needs_broader_context")),
        "next_queries": next_queries,
        "trust": {
            "classification": "repository-local",
            "sensitivity": "redacted" if redactions else "normal",
            "source_content": "extractive",
        },
        "redactions": redactions,
    }
    boundary = _redact_payload_values(
        {key: value for key, value in payload.items() if key != "redactions"},
        redactions,
    )
    payload.update(boundary)
    payload["redactions"] = redactions
    payload["trust"]["sensitivity"] = "redacted" if redactions else "normal"
    payload["redactions"].sort(
        key=lambda item: (item["path"], item["reason"], item.get("evidence_kind", ""), item.get("span", []))
    )
    _fit_budget(payload, int(token_budget))
    _stamp_hash_and_measurement(payload)
    return payload


def resolve_execution_context_handle(root: str, expansion_handle: str) -> dict[str, Any]:
    """Resolve an existing retrieval handle, rejecting corruption and staleness."""
    try:
        resolved = resolve_expand_handle(root, expansion_handle)
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        raise ExecutionContextError(str(error)) from error
    reason = _path_reason(root, str(resolved.get("path") or ""))
    if reason:
        raise ExecutionContextError(f"unsafe expansion handle: {reason}")
    if resolved.get("stale"):
        raise ExecutionContextError("stale expansion handle")
    safe, count = _redact_text(str(resolved.get("text") or ""))
    resolved["text"] = safe
    resolved["redacted_values"] = count
    return resolved


def validate_execution_context(payload: Mapping[str, Any]) -> list[str]:
    """Return stable corruption/compatibility reason codes."""
    errors: list[str] = []
    if payload.get("schema") != EXECUTION_CONTEXT_SCHEMA:
        errors.append("UNSUPPORTED_SCHEMA")
        return errors
    required = {
        "task",
        "repository",
        "sources",
        "graph_edges",
        "related_tests",
        "precedents",
        "fidelity",
        "omissions",
        "abstention",
        "needs_broader_context",
        "next_queries",
        "trust",
        "redactions",
        "token_budget",
        "envelope_hash",
    }
    if missing := sorted(required - set(payload)):
        errors.extend(f"MISSING_REQUIRED:{name}" for name in missing)
        return errors
    allowed = required | {"schema"}
    errors.extend(f"INVALID_SHAPE:{name}" for name in sorted(set(payload) - allowed))

    def expect(value: Any, expected: type, path: str) -> None:
        valid = isinstance(value, expected)
        if expected is int:
            valid = valid and not isinstance(value, bool)
        if not valid:
            errors.append(f"INVALID_SHAPE:{path}")

    def expect_string(value: Any, path: str, *, min_length: int = 0) -> None:
        if not isinstance(value, str) or len(value) < min_length:
            errors.append(f"INVALID_SHAPE:{path}")

    def expect_number(
        value: Any,
        path: str,
        *,
        minimum: int | float | None = None,
        maximum: int | float | None = None,
        nullable: bool = False,
    ) -> None:
        if nullable and value is None:
            return
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"INVALID_SHAPE:{path}")
            return
        if minimum is not None and value < minimum:
            errors.append(f"INVALID_SHAPE:{path}")
        elif maximum is not None and value > maximum:
            errors.append(f"INVALID_SHAPE:{path}")

    def expect_integer(
        value: Any,
        path: str,
        *,
        minimum: int | None = None,
        nullable: bool = False,
    ) -> None:
        if nullable and value is None:
            return
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"INVALID_SHAPE:{path}")
            return
        if minimum is not None and value < minimum:
            errors.append(f"INVALID_SHAPE:{path}")

    def expect_hash(value: Any, path: str) -> None:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            errors.append(f"INVALID_SHAPE:{path}")

    def expect_enum(value: Any, allowed_values: set[Any], path: str) -> None:
        try:
            valid = value in allowed_values
        except TypeError:
            valid = False
        if not valid:
            errors.append(f"INVALID_SHAPE:{path}")

    def expect_object_fields(
        value: Any,
        *,
        path: str,
        required_fields: set[str],
        allowed_fields: set[str],
    ) -> Mapping[str, Any] | None:
        if not isinstance(value, Mapping):
            errors.append(f"INVALID_SHAPE:{path}")
            return None
        for field in sorted(required_fields - set(value)):
            errors.append(f"INVALID_SHAPE:{path}.{field}")
        for field in sorted(set(value) - allowed_fields):
            errors.append(f"INVALID_SHAPE:{path}.{field}")
        return value

    def expect_string_list(value: Any, path: str) -> None:
        expect(value, list, path)
        if isinstance(value, list):
            for index, item in enumerate(value):
                expect(item, str, f"{path}[{index}]")

    def expect_source_handle(value: Any, path: str) -> None:
        source_handle = expect_object_fields(
            value,
            path=path,
            required_fields={"path", "line"},
            allowed_fields={"path", "line"},
        )
        if source_handle is None:
            return
        if "path" in source_handle:
            expect(source_handle["path"], str, f"{path}.path")
        if "line" in source_handle:
            expect_integer(source_handle["line"], f"{path}.line", minimum=1, nullable=True)

    task = expect_object_fields(
        payload["task"],
        path="task",
        required_fields={"fingerprint", "goal", "acceptance_criteria", "intent_fingerprint"},
        allowed_fields={"fingerprint", "goal", "acceptance_criteria", "intent_fingerprint"},
    )
    if task is not None:
        for field in ("fingerprint", "goal", "intent_fingerprint"):
            if field in task:
                expect_string(
                    task[field],
                    f"task.{field}",
                    min_length=1 if field == "fingerprint" else 0,
                )
        if "acceptance_criteria" in task:
            expect_string_list(task["acceptance_criteria"], "task.acceptance_criteria")

    repository = expect_object_fields(
        payload["repository"],
        path="repository",
        required_fields={"id", "root_hash", "map_hash", "snapshot_id", "artifact_hashes"},
        allowed_fields={
            "id",
            "root_hash",
            "map_hash",
            "snapshot_id",
            "context_pack_hash",
            "artifact_hashes",
        },
    )
    if repository is not None:
        for field in ("id", "context_pack_hash"):
            if field in repository:
                expect(repository[field], str, f"repository.{field}")
        for field in ("root_hash", "map_hash", "snapshot_id"):
            if field in repository:
                expect_hash(repository[field], f"repository.{field}")
        if "artifact_hashes" in repository:
            expect(repository["artifact_hashes"], dict, "repository.artifact_hashes")
            if isinstance(repository["artifact_hashes"], Mapping):
                for name, value in repository["artifact_hashes"].items():
                    expect(name, str, f"repository.artifact_hashes.{name}")
                    expect_hash(value, f"repository.artifact_hashes.{name}")

    expect(payload["sources"], list, "sources")
    if isinstance(payload["sources"], list):
        source_required = {
            "path",
            "rank",
            "language",
            "relevance_score",
            "reason_codes",
            "source_hash",
            "line_count",
            "symbols",
            "spans",
            "expansion_handle",
        }
        source_allowed = source_required
        for index, source_value in enumerate(payload["sources"]):
            path = f"sources[{index}]"
            source = expect_object_fields(
                source_value,
                path=path,
                required_fields=source_required,
                allowed_fields=source_allowed,
            )
            if source is None:
                continue
            if "path" in source:
                expect_string(source["path"], f"{path}.path", min_length=1)
            if "source_hash" in source:
                expect_hash(source["source_hash"], f"{path}.source_hash")
            if "expansion_handle" in source:
                expect_string(source["expansion_handle"], f"{path}.expansion_handle", min_length=1)
            if "rank" in source:
                expect_integer(source["rank"], f"{path}.rank", minimum=1)
            if "language" in source:
                expect(source["language"], str, f"{path}.language")
            if "relevance_score" in source:
                expect_number(source["relevance_score"], f"{path}.relevance_score")
            if "line_count" in source:
                expect_integer(source["line_count"], f"{path}.line_count", minimum=0)
            if "spans" in source:
                expect(source["spans"], list, f"{path}.spans")
            for field in ("reason_codes", "symbols"):
                if field in source:
                    expect_string_list(source[field], f"{path}.{field}")
            if isinstance(source.get("spans"), list):
                span_required = {
                    "start_line",
                    "end_line",
                    "kind",
                    "symbol",
                    "span_hash",
                    "text",
                    "expansion_handle",
                }
                for span_index, span_value in enumerate(source["spans"]):
                    span_path = f"{path}.spans[{span_index}]"
                    span = expect_object_fields(
                        span_value,
                        path=span_path,
                        required_fields=span_required,
                        allowed_fields=span_required,
                    )
                    if span is None:
                        continue
                    for field in ("start_line", "end_line"):
                        if field in span:
                            expect_integer(span[field], f"{span_path}.{field}", minimum=1)
                    for field in ("kind", "text"):
                        if field in span:
                            expect(span[field], str, f"{span_path}.{field}")
                    if "expansion_handle" in span:
                        expect_string(
                            span["expansion_handle"],
                            f"{span_path}.expansion_handle",
                            min_length=1,
                        )
                    if "symbol" in span and span["symbol"] is not None:
                        expect(span["symbol"], str, f"{span_path}.symbol")
                    if "span_hash" in span:
                        expect_hash(span["span_hash"], f"{span_path}.span_hash")

    expect(payload["graph_edges"], list, "graph_edges")
    if isinstance(payload["graph_edges"], list):
        required_fields = {
            "kind",
            "source",
            "target",
            "dependency_distance",
            "confidence",
            "provenance",
            "source_handle",
            "edge_hash",
        }
        for index, value in enumerate(payload["graph_edges"]):
            path = f"graph_edges[{index}]"
            edge = expect_object_fields(
                value,
                path=path,
                required_fields=required_fields,
                allowed_fields=required_fields,
            )
            if edge is None:
                continue
            for field in ("kind", "source", "target", "provenance"):
                if field in edge:
                    expect(edge[field], str, f"{path}.{field}")
            if "dependency_distance" in edge:
                expect_integer(edge["dependency_distance"], f"{path}.dependency_distance", minimum=0)
            if "confidence" in edge:
                expect_number(edge["confidence"], f"{path}.confidence", nullable=True)
            if "source_handle" in edge:
                expect_source_handle(edge["source_handle"], f"{path}.source_handle")
            if "edge_hash" in edge:
                expect_hash(edge["edge_hash"], f"{path}.edge_hash")

    expect(payload["related_tests"], list, "related_tests")
    if isinstance(payload["related_tests"], list):
        required_fields = {"path", "verifies", "route", "confidence", "provenance"}
        for index, value in enumerate(payload["related_tests"]):
            path = f"related_tests[{index}]"
            related_test = expect_object_fields(
                value,
                path=path,
                required_fields=required_fields,
                allowed_fields=required_fields,
            )
            if related_test is None:
                continue
            for field in ("path", "verifies", "route", "provenance"):
                if field in related_test:
                    expect(related_test[field], str, f"{path}.{field}")
            if "confidence" in related_test:
                expect_number(related_test["confidence"], f"{path}.confidence")

    expect(payload["precedents"], list, "precedents")
    if isinstance(payload["precedents"], list):
        required_fields = {
            "id",
            "path",
            "line",
            "summary",
            "snippet",
            "confidence",
            "provenance",
            "redacted_values",
        }
        confidence_fields = {"value", "semantics", "measured"}
        for index, value in enumerate(payload["precedents"]):
            path = f"precedents[{index}]"
            precedent = expect_object_fields(
                value,
                path=path,
                required_fields=required_fields,
                allowed_fields=required_fields,
            )
            if precedent is None:
                continue
            for field in ("id", "path", "summary", "snippet", "provenance"):
                if field in precedent:
                    expect(precedent[field], str, f"{path}.{field}")
            if "line" in precedent:
                expect_integer(precedent["line"], f"{path}.line", nullable=True)
            if "redacted_values" in precedent:
                expect_integer(precedent["redacted_values"], f"{path}.redacted_values", minimum=0)
            if "confidence" in precedent:
                confidence = expect_object_fields(
                    precedent["confidence"],
                    path=f"{path}.confidence",
                    required_fields=confidence_fields,
                    allowed_fields=confidence_fields,
                )
                if confidence is not None:
                    if "value" in confidence:
                        expect_integer(confidence["value"], f"{path}.confidence.value", minimum=0)
                    if "semantics" in confidence:
                        expect_enum(
                            confidence["semantics"],
                            {"keyword_overlap_count"},
                            f"{path}.confidence.semantics",
                        )
                    if confidence.get("measured") is not False:
                        errors.append(f"INVALID_SHAPE:{path}.confidence.measured")

    expect(payload["omissions"], list, "omissions")
    if isinstance(payload["omissions"], list):
        required_fields = {"kind", "reason", "expansion_handle"}
        for index, value in enumerate(payload["omissions"]):
            path = f"omissions[{index}]"
            omission = expect_object_fields(
                value,
                path=path,
                required_fields=required_fields,
                allowed_fields=required_fields,
            )
            if omission is None:
                continue
            for field in ("kind", "reason"):
                if field in omission:
                    expect(omission[field], str, f"{path}.{field}")
            if "expansion_handle" in omission:
                handle = omission["expansion_handle"]
                if isinstance(handle, Mapping):
                    expect_source_handle(handle, f"{path}.expansion_handle")
                elif handle is not None and not isinstance(handle, str):
                    errors.append(f"INVALID_SHAPE:{path}.expansion_handle")

    expect(payload["redactions"], list, "redactions")
    if isinstance(payload["redactions"], list):
        required_fields = {"path", "reason"}
        allowed_fields = required_fields | {"evidence_kind", "span", "count"}
        allowed_reasons = {
            "binary_file",
            "outside_authorized_root",
            "secret_path",
            "secret_value",
            "unreadable_file",
        }
        for index, value in enumerate(payload["redactions"]):
            path = f"redactions[{index}]"
            redaction = expect_object_fields(
                value,
                path=path,
                required_fields=required_fields,
                allowed_fields=allowed_fields,
            )
            if redaction is None:
                continue
            if "path" in redaction:
                expect(redaction["path"], str, f"{path}.path")
            if "reason" in redaction:
                expect_enum(redaction["reason"], allowed_reasons, f"{path}.reason")
            if "evidence_kind" in redaction:
                expect(redaction["evidence_kind"], str, f"{path}.evidence_kind")
            if "span" in redaction:
                span = redaction["span"]
                if not isinstance(span, list) or len(span) != 2:
                    errors.append(f"INVALID_SHAPE:{path}.span")
                if isinstance(span, list):
                    for span_index, line in enumerate(span):
                        expect_integer(line, f"{path}.span[{span_index}]", minimum=1)
            if "count" in redaction:
                expect_integer(redaction["count"], f"{path}.count", minimum=1)

    expect_string_list(payload["next_queries"], "next_queries")

    fidelity = expect_object_fields(
        payload["fidelity"],
        path="fidelity",
        required_fields={"sufficient", "vector", "coverage_ratio", "reasons"},
        allowed_fields={"sufficient", "vector", "coverage_ratio", "reasons"},
    )
    if fidelity is not None:
        if "sufficient" in fidelity:
            expect(fidelity["sufficient"], bool, "fidelity.sufficient")
        if "vector" in fidelity:
            vector_fields = {
                "target_preserved",
                "identifier_coverage_ratio",
                "ac_coverage_ratio",
                "discriminative_coverage_ratio",
                "verification_route_present",
                "layer_count",
                "has_discriminative_signal",
                "matched_domain_terms",
            }
            vector = expect_object_fields(
                fidelity["vector"],
                path="fidelity.vector",
                required_fields=set(),
                allowed_fields=vector_fields,
            )
            if vector is not None:
                for field in ("target_preserved", "has_discriminative_signal"):
                    if field in vector:
                        expect(vector[field], bool, f"fidelity.vector.{field}")
                for field in (
                    "identifier_coverage_ratio",
                    "ac_coverage_ratio",
                    "discriminative_coverage_ratio",
                ):
                    if field in vector:
                        expect_number(
                            vector[field],
                            f"fidelity.vector.{field}",
                            minimum=0,
                            maximum=1,
                        )
                if "verification_route_present" in vector:
                    value = vector["verification_route_present"]
                    if value is not None:
                        expect(value, bool, "fidelity.vector.verification_route_present")
                if "layer_count" in vector:
                    expect_integer(vector["layer_count"], "fidelity.vector.layer_count", minimum=0)
                if "matched_domain_terms" in vector:
                    expect_string_list(vector["matched_domain_terms"], "fidelity.vector.matched_domain_terms")
        if "coverage_ratio" in fidelity:
            expect_number(fidelity["coverage_ratio"], "fidelity.coverage_ratio", minimum=0, maximum=1)
        if "reasons" in fidelity:
            expect_string_list(fidelity["reasons"], "fidelity.reasons")

    abstention = expect_object_fields(
        payload["abstention"],
        path="abstention",
        required_fields={"abstained", "reasons"},
        allowed_fields={"abstained", "reasons"},
    )
    if abstention is not None:
        if "abstained" in abstention:
            expect(abstention["abstained"], bool, "abstention.abstained")
        if "reasons" in abstention:
            expect_string_list(abstention["reasons"], "abstention.reasons")
    expect(payload["needs_broader_context"], bool, "needs_broader_context")

    trust = expect_object_fields(
        payload["trust"],
        path="trust",
        required_fields={"classification", "sensitivity", "source_content"},
        allowed_fields={"classification", "sensitivity", "source_content"},
    )
    if trust is not None:
        expected_values = {
            "classification": {"repository-local"},
            "sensitivity": {"normal", "redacted"},
            "source_content": {"extractive"},
        }
        for field, values in expected_values.items():
            if field in trust:
                expect_enum(trust[field], values, f"trust.{field}")

    if payload.get("envelope_hash") != _envelope_hash(payload):
        errors.append("ENVELOPE_HASH_MISMATCH")
    if not isinstance(payload.get("envelope_hash"), str) or not re.fullmatch(
        r"[0-9a-f]{64}",
        str(payload.get("envelope_hash")),
    ):
        errors.append("INVALID_SHAPE:envelope_hash")
    receipt = payload.get("token_budget")
    if not isinstance(receipt, Mapping):
        errors.append("TOKEN_BUDGET_INVALID")
    else:
        receipt_required = {
            "requested_tokens",
            "serialized_tokens",
            "serialized_bytes",
            "tokenizer_policy",
            "measurement",
            "within_budget",
        }
        for field in sorted(receipt_required - set(receipt)):
            errors.append(f"INVALID_SHAPE:token_budget.{field}")
        for field in sorted(set(receipt) - receipt_required):
            errors.append(f"INVALID_SHAPE:token_budget.{field}")
        for field in ("requested_tokens", "serialized_tokens", "serialized_bytes"):
            if field in receipt:
                expect_integer(
                    receipt[field],
                    f"token_budget.{field}",
                    minimum=1 if field == "requested_tokens" else 0,
                )
        if "tokenizer_policy" in receipt:
            expect_string(receipt["tokenizer_policy"], "token_budget.tokenizer_policy", min_length=1)
        if "measurement" in receipt:
            expect_enum(receipt["measurement"], {"MEASURED"}, "token_budget.measurement")
        if "within_budget" in receipt:
            expect(receipt["within_budget"], bool, "token_budget.within_budget")
        actual_tokens = serialized_token_count(payload)
        if receipt.get("serialized_tokens") != actual_tokens:
            errors.append("SERIALIZED_TOKEN_COUNT_MISMATCH")
        actual_bytes = len(serialized_json_bytes(payload))
        if receipt.get("serialized_bytes") != actual_bytes:
            errors.append("SERIALIZED_BYTE_COUNT_MISMATCH")
        requested = receipt.get("requested_tokens")
        if isinstance(requested, int) and not isinstance(requested, bool):
            expected_within = actual_tokens <= requested
            if receipt.get("within_budget") is not expected_within:
                errors.append("WITHIN_BUDGET_MISMATCH")
    return errors


__all__ = [
    "EXECUTION_CONTEXT_SCHEMA",
    "ExecutionContextError",
    "build_execution_context",
    "resolve_execution_context_handle",
    "validate_execution_context",
]
