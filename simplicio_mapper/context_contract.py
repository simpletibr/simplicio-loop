"""Fail-closed conformance checks for versioned context payloads."""

from __future__ import annotations

import hashlib
import json
import math
import os
import posixpath
import re
from collections.abc import Mapping
from typing import Any

from .contract import validate_instance

REPORT_SCHEMA = "simplicio.context-conformance-report/v1"
CONTEXT_SNAPSHOT_SCHEMA = "simplicio.context-snapshot/v1"
CONTEXT_GRAPH_SCHEMA = "simplicio.context-graph/v1"
SCHEMA_VERSION = "v1"
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 64
_LOGICAL_HANDLE_PREFIXES = ("module:", "layer:", "adr:")
_ARTIFACT_FINGERPRINTS = {"project_map", "symbol_index", "call_graph", "architecture_inventory"}


def canonical_json(value: Any) -> bytes:
    """Return canonical UTF-8 JSON, sorted and without insignificant space."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _snapshot_id_of(payload: Mapping[str, Any]) -> str:
    return canonical_sha256({key: value for key, value in dict(payload).items() if key not in {"snapshot_id", "generated_at"}})


def _load_context_schema(schema_id: str) -> dict[str, Any]:
    filename = {CONTEXT_SNAPSHOT_SCHEMA: "context-snapshot.schema.json", CONTEXT_GRAPH_SCHEMA: "context-graph.schema.json"}[schema_id]
    package = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contracts", "context-snapshot", "v1", "schemas", filename)
    path = package if os.path.isfile(package) else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts", "context-snapshot", "v1", "schemas", filename)
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _reason(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _preflight(value: Any, max_bytes: int, max_depth: int) -> tuple[list[dict[str, str]], int]:
    """Bound DFS before serializing input, using O(depth) iterator frames."""
    reasons: list[dict[str, str]] = []
    stack: list[tuple[Any, str, int, Any]] = [(value, "$", 0, None)]
    active: set[int] = set()
    estimate = 0
    while stack:
        item, path, depth, iterator = stack[-1]
        if iterator is not None:
            try:
                key, child = next(iterator)
            except StopIteration:
                active.discard(id(item))
                stack.pop()
                continue
            if isinstance(item, Mapping):
                if not isinstance(key, str):
                    reasons.append(_reason("PAYLOAD_NOT_JSON", path, "object keys must be strings"))
                    break
                try:
                    estimate += len(key.encode("utf-8")) + 3
                except UnicodeError as exc:
                    reasons.append(_reason("PAYLOAD_NOT_JSON", path, str(exc)))
                    break
            if estimate > max_bytes:
                reasons.append(_reason("PAYLOAD_TOO_LARGE", "$", f"payload exceeds {max_bytes} bytes"))
                break
            child_path = f"{path}.{key}" if isinstance(item, Mapping) else f"{path}[{key}]"
            stack.append((child, child_path, depth + 1, None))
            continue
        if depth > max_depth:
            reasons.append(_reason("PAYLOAD_TOO_DEEP", path, f"payload exceeds depth {max_depth}"))
            break
        if isinstance(item, (Mapping, list)):
            marker = id(item)
            if marker in active:
                reasons.append(_reason("PAYLOAD_CYCLIC", path, "payload contains a reference cycle"))
                break
            active.add(marker)
            estimate += 2
            stack[-1] = (item, path, depth, iter(item.items()) if isinstance(item, Mapping) else iter(enumerate(item)))
            continue
        if isinstance(item, str):
            try:
                estimate += len(item.encode("utf-8")) + 2
            except UnicodeError as exc:
                reasons.append(_reason("PAYLOAD_NOT_JSON", path, str(exc)))
                break
        elif item is None or isinstance(item, (bool, int, float)):
            if isinstance(item, float) and not math.isfinite(item):
                reasons.append(_reason("PAYLOAD_NOT_JSON", path, "NaN and Infinity are not valid JSON"))
                break
            estimate += 32
        else:
            reasons.append(_reason("PAYLOAD_NOT_JSON", path, f"unsupported value type {type(item).__name__}"))
            break
        stack.pop()
        if estimate > max_bytes:
            reasons.append(_reason("PAYLOAD_TOO_LARGE", "$", f"payload exceeds {max_bytes} bytes"))
            break
    return reasons, estimate


def _schema_reasons(payload: Mapping[str, Any], schema_id: str, prefix: str) -> list[dict[str, str]]:
    """Return structured schema failures without exceptions."""
    schema = _load_context_schema(schema_id)
    schema_base = os.path.dirname(
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "contracts",
            "context-snapshot",
            "v1",
            "schemas",
            "context-graph.schema.json",
        )
    )
    return [
        _reason(prefix, "$", error)
        for error in validate_instance(dict(payload), schema, schema_base)
    ]


def _handle_reasons(handle: Any, path: str, source_root: str | None) -> list[dict[str, str]]:
    if not isinstance(handle, Mapping) or not isinstance(handle.get("file"), str) or not handle["file"]:
        return [_reason("SOURCE_HANDLE_MISSING", path, "source handle requires a file")]
    unknown = set(handle).difference({"file", "line", "span"})
    if unknown:
        return [
            _reason(
                "SOURCE_HANDLE_UNKNOWN_PROPERTY",
                path,
                f"source handle has unsupported properties: {', '.join(sorted(map(str, unknown)))}",
            )
        ]
    file_name = handle["file"]
    if "\x00" in file_name or "\\" in file_name or os.path.isabs(file_name) or re.match(r"^[A-Za-z]:/", file_name):
        return [_reason("SOURCE_HANDLE_INVALID", f"{path}.file", "source file must be a relative POSIX handle")]
    if file_name != "<unknown>" and not file_name.startswith(_LOGICAL_HANDLE_PREFIXES):
        normalized = posixpath.normpath(file_name)
        if normalized != file_name or normalized == ".." or normalized.startswith("../"):
            return [_reason("SOURCE_HANDLE_TRAVERSAL", f"{path}.file", "source file escapes its logical root")]
        if source_root:
            candidate = os.path.realpath(os.path.join(source_root, *file_name.split("/")))
            root = os.path.realpath(source_root)
            if os.path.commonpath([root, candidate]) != root or not os.path.exists(candidate):
                return [_reason("SOURCE_HANDLE_UNRESOLVABLE", f"{path}.file", "source file is not reversible under source_root")]
    line = handle.get("line")
    if line is not None and (not isinstance(line, int) or isinstance(line, bool) or line < 1):
        return [_reason("SOURCE_HANDLE_LINE_INVALID", f"{path}.line", "line must be an integer >= 1")]
    span = handle.get("span")
    if span is not None and (
        not isinstance(span, list)
        or len(span) != 2
        or any(not isinstance(number, int) or isinstance(number, bool) or number < 1 for number in span)
        or span[0] > span[1]
    ):
        return [_reason("SOURCE_HANDLE_SPAN_INVALID", f"{path}.span", "span must be [start, end] with 1 <= start <= end")]
    return []


def _path_collection_reasons(value: Any, path: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return [_reason("PATH_SET_INVALID", path, "value must be an array of logical paths")]
    reasons: list[dict[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or item.startswith(_LOGICAL_HANDLE_PREFIXES) or item == "<unknown>":
            reasons.append(_reason("PATH_SET_INVALID", f"{path}[{index}]", "path must be a physical relative POSIX path"))
        else:
            reasons.extend(_handle_reasons({"file": item}, f"{path}[{index}]", None))
    if all(isinstance(item, str) for item in value):
        if value != sorted(value):
            reasons.append(_reason("PATH_SET_UNSORTED", path, "paths must be sorted canonically"))
        if len(set(value)) != len(value):
            reasons.append(_reason("PATH_SET_DUPLICATE", path, "paths must be unique"))
    return reasons


def _graph_invariants(graph: Mapping[str, Any], source_root: str | None) -> list[dict[str, str]]:
    reasons: list[dict[str, str]] = []
    nodes, edges = graph.get("nodes"), graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return reasons
    ids = set()
    for index, node in enumerate(nodes):
        path = f"$.nodes[{index}]"
        if not isinstance(node, Mapping):
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            reasons.append(_reason("NODE_ID_INVALID", f"{path}.id", "node id must be a non-empty string"))
        elif node_id in ids:
            reasons.append(_reason("NODE_ID_DUPLICATE", f"{path}.id", "node ids must be unique"))
        else:
            ids.add(node_id)
        reasons.extend(_handle_reasons(node.get("source"), f"{path}.source", source_root))
    edge_ids = set()
    for index, edge in enumerate(edges):
        path = f"$.edges[{index}]"
        if not isinstance(edge, Mapping):
            continue
        edge_id = edge.get("id")
        if not isinstance(edge_id, str) or not edge_id:
            reasons.append(_reason("EDGE_ID_INVALID", f"{path}.id", "edge id must be a non-empty string"))
        elif edge_id in edge_ids:
            reasons.append(_reason("EDGE_ID_DUPLICATE", f"{path}.id", "edge ids must be unique"))
        else:
            edge_ids.add(edge_id)
        if not isinstance(edge.get("source"), str) or not isinstance(edge.get("target"), str):
            reasons.append(_reason("EDGE_ENDPOINT_INVALID", path, "edge source and target must be strings"))
        else:
            derived_id = (
                edge.get("relation_id")
                if isinstance(edge.get("relation_id"), str) and edge.get("relation_id")
                else canonical_sha256(
                    {"kind": edge.get("kind"), "source": edge["source"], "target": edge["target"]}
                )
            )
            if edge.get("id") != derived_id:
                reasons.append(_reason("EDGE_ID_MISMATCH", f"{path}.id", "edge id does not match producer derivation"))
        reasons.extend(_handle_reasons(edge.get("source_handle"), f"{path}.source_handle", source_root))
    counts = graph.get("counts")
    if not isinstance(counts, Mapping):
        reasons.append(_reason("GRAPH_COUNTS_MISSING", "$.counts", "graph counts must be an object"))
    else:
        expected = {"nodes": len(nodes), "edges": len(edges)}
        expected.update({scale: sum(isinstance(n, Mapping) and n.get("scale") == scale for n in nodes) for scale in ("micro", "meso", "macro")})
        for key, value in expected.items():
            if counts.get(key) != value:
                reasons.append(_reason("GRAPH_COUNT_MISMATCH", f"$.counts.{key}", f"expected {value}, got {counts.get(key)!r}"))
    semantics = graph.get("scale_semantics")
    if not isinstance(semantics, Mapping) or set(semantics) != {"micro", "meso", "macro"}:
        reasons.append(_reason("SCALE_SEMANTICS_INVALID", "$.scale_semantics", "all three scale semantics are required"))
    drilldown = graph.get("drilldown")
    if not isinstance(drilldown, Mapping) or drilldown.get("reversible") is not True or drilldown.get("node_source_field") != "source" or drilldown.get("edge_source_field") != "source_handle":
        reasons.append(_reason("GRAPH_DRILLDOWN_INVALID", "$.drilldown", "graph drilldown must declare reversible source fields"))
    return reasons


def _report(target_schema: str, reasons: list[dict[str, str]], payload: Any) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "target_schema": target_schema,
        "valid": not reasons,
        "reason_codes": reasons,
        "snapshot_id": payload.get("snapshot_id", "") if isinstance(payload, Mapping) else "",
    }


def validate_context_graph(graph: Any, *, source_root: str | None = None, max_bytes: int = MAX_SNAPSHOT_BYTES, max_depth: int = MAX_JSON_DEPTH) -> dict[str, Any]:
    """Validate a ``simplicio.context-graph/v1`` payload directly."""
    reasons, _ = _preflight(graph, max_bytes, max_depth)
    if reasons:
        return _report(CONTEXT_GRAPH_SCHEMA, reasons, graph)
    if not isinstance(graph, Mapping):
        reasons.append(_reason("GRAPH_NOT_OBJECT", "$", "graph must be a JSON object"))
    elif graph.get("schema") != CONTEXT_GRAPH_SCHEMA or graph.get("version") != 1:
        reasons.append(_reason("UNSUPPORTED_GRAPH_SCHEMA", "$.schema", "only context-graph/v1 is supported"))
    else:
        try:
            encoded = canonical_json(graph)
            if len(encoded) > max_bytes:
                reasons.append(_reason("PAYLOAD_TOO_LARGE", "$", f"payload exceeds {max_bytes} bytes"))
        except (RecursionError, MemoryError, TypeError, ValueError) as exc:
            reasons.append(_reason("PAYLOAD_NOT_JSON", "$", str(exc)))
        reasons.extend(_schema_reasons(graph, CONTEXT_GRAPH_SCHEMA, "GRAPH_SCHEMA_INVALID"))
        reasons.extend(_graph_invariants(graph, source_root))
    return _report(CONTEXT_GRAPH_SCHEMA, reasons, graph)


def validate_context_snapshot(snapshot: Any, *, source_root: str | None = None, max_bytes: int = MAX_SNAPSHOT_BYTES, max_depth: int = MAX_JSON_DEPTH) -> dict[str, Any]:
    """Validate a ``simplicio.context-snapshot/v1`` envelope fail-closed."""
    reasons, _ = _preflight(snapshot, max_bytes, max_depth)
    if reasons:
        return _report(CONTEXT_SNAPSHOT_SCHEMA, reasons, snapshot)
    if not isinstance(snapshot, Mapping):
        reasons.append(_reason("SNAPSHOT_NOT_OBJECT", "$", "snapshot must be a JSON object"))
        return _report(CONTEXT_SNAPSHOT_SCHEMA, reasons, snapshot)
    if snapshot.get("schema") != CONTEXT_SNAPSHOT_SCHEMA or snapshot.get("schema_version") != SCHEMA_VERSION:
        reasons.append(_reason("UNSUPPORTED_SCHEMA", "$.schema", "only context-snapshot/v1 is supported"))
    else:
        try:
            encoded = canonical_json(snapshot)
            if len(encoded) > max_bytes:
                reasons.append(_reason("PAYLOAD_TOO_LARGE", "$", f"payload exceeds {max_bytes} bytes"))
        except (RecursionError, MemoryError, TypeError, ValueError) as exc:
            reasons.append(_reason("PAYLOAD_NOT_JSON", "$", str(exc)))
        reasons.extend(_schema_reasons(snapshot, CONTEXT_SNAPSHOT_SCHEMA, "SNAPSHOT_SCHEMA_INVALID"))
        graph_report = validate_context_graph(snapshot.get("graph"), source_root=source_root, max_bytes=max_bytes, max_depth=max_depth)
        reasons.extend(graph_report["reason_codes"])
        freshness = snapshot.get("freshness")
        graph = snapshot.get("graph")
        if isinstance(freshness, Mapping) and isinstance(graph, Mapping):
            if freshness.get("graph_hash") != canonical_sha256(graph):
                reasons.append(_reason("GRAPH_HASH_MISMATCH", "$.freshness.graph_hash", "graph hash does not match canonical graph"))
            if freshness.get("root_hash") != snapshot.get("root_hash"):
                reasons.append(_reason("FRESHNESS_ROOT_HASH_MISMATCH", "$.freshness.root_hash", "freshness root hash must match snapshot root hash"))
            source_set = snapshot.get("source_set")
            if isinstance(source_set, list) and freshness.get("source_count") != len(source_set):
                reasons.append(_reason("SOURCE_COUNT_MISMATCH", "$.freshness.source_count", "source count does not match source_set"))
            fingerprints = freshness.get("artifact_hashes")
            if not isinstance(fingerprints, Mapping) or set(fingerprints) != _ARTIFACT_FINGERPRINTS:
                reasons.append(_reason("ARTIFACT_HASHES_INVALID", "$.freshness.artifact_hashes", "exact producer fingerprints are required"))
            elif any(not _is_sha256(fingerprints[key]) for key in _ARTIFACT_FINGERPRINTS):
                reasons.append(_reason("ARTIFACT_HASH_INVALID", "$.freshness.artifact_hashes", "fingerprints must be lowercase SHA-256"))
        else:
            reasons.append(_reason("FRESHNESS_INVALID", "$.freshness", "freshness metadata is required"))
        source_set = snapshot.get("source_set")
        reasons.extend(_path_collection_reasons(source_set, "$.source_set"))
        reasons.extend(_path_collection_reasons(snapshot.get("exclusions"), "$.exclusions"))
        if isinstance(source_set, list) and isinstance(snapshot.get("repository_id"), str) and isinstance(snapshot.get("revision"), str):
            expected_root = canonical_sha256(
                {
                    "repository_id": snapshot["repository_id"],
                    "revision": snapshot["revision"],
                    "source_set": sorted(source_set),
                }
            )
            if snapshot.get("root_hash") != expected_root:
                reasons.append(_reason("ROOT_HASH_MISMATCH", "$.root_hash", "root hash does not match producer derivation"))
        if isinstance(graph, Mapping) and snapshot.get("scale_semantics") != graph.get("scale_semantics"):
            reasons.append(_reason("SCALE_SEMANTICS_MISMATCH", "$.scale_semantics", "snapshot and graph scale semantics differ"))
        if snapshot.get("build_config_hash") != "" and not _is_sha256(snapshot.get("build_config_hash")):
            reasons.append(_reason("BUILD_CONFIG_HASH_INVALID", "$.build_config_hash", "must be empty or lowercase SHA-256"))
        drilldown = snapshot.get("drilldown")
        if not isinstance(drilldown, Mapping) or drilldown.get("reversible") is not True or drilldown.get("source_handle_contract") != {"node": "source", "edge": "source_handle"}:
            reasons.append(_reason("SNAPSHOT_DRILLDOWN_INVALID", "$.drilldown", "snapshot drilldown must declare source handle fields"))
        task = snapshot.get("task")
        fidelity = snapshot.get("fidelity")
        if isinstance(task, Mapping) and isinstance(fidelity, Mapping):
            omissions = task.get("omissions")
            if isinstance(omissions, list):
                if fidelity.get("omissions") != omissions:
                    reasons.append(_reason("FIDELITY_OMISSIONS_MISMATCH", "$.fidelity.omissions", "must match task omissions"))
                counts = graph.get("counts") if isinstance(graph, Mapping) else None
                coverage = fidelity.get("coverage")
                fields = (("addressable_nodes", "nodes"), ("addressable_edges", "edges"), ("micro", "micro"), ("meso", "meso"), ("macro", "macro"))
                if not isinstance(counts, Mapping) or not isinstance(coverage, Mapping) or any(coverage.get(left) != counts.get(right) for left, right in fields):
                    reasons.append(_reason("FIDELITY_COVERAGE_MISMATCH", "$.fidelity.coverage", "must match graph counts"))
                gate = str(fidelity.get("gate", "")).strip().casefold()
                status = str(fidelity.get("status", "")).strip().casefold()
                abstained = bool(fidelity.get("abstained")) or status in {"insufficient", "abstained"}
                expected_gate = bool(omissions) or abstained
                if not abstained and (status != ("partial" if omissions else "complete") or gate != ("needs_broader_context" if omissions else "ready")):
                    reasons.append(_reason("FIDELITY_STATE_MISMATCH", "$.fidelity", "state must match omissions"))
                if bool(snapshot.get("needs_broader_context")) != expected_gate:
                    reasons.append(_reason("CONTEXT_GATE_MISMATCH", "$.needs_broader_context", "context gate does not match omissions"))
        if snapshot.get("snapshot_id") != _snapshot_id_of(snapshot):
            reasons.append(_reason("SNAPSHOT_HASH_MISMATCH", "$.snapshot_id", "snapshot id does not match canonical payload"))
    return _report(CONTEXT_SNAPSHOT_SCHEMA, reasons, snapshot)


def validate_context_payload(payload: Any, **kwargs: Any) -> dict[str, Any]:
    """Dispatch validation by schema, rejecting unknown/future payloads."""
    if isinstance(payload, Mapping) and payload.get("schema") == CONTEXT_GRAPH_SCHEMA:
        return validate_context_graph(payload, **kwargs)
    return validate_context_snapshot(payload, **kwargs)


def validate_context_file(path: str, *, source_root: str | None = None, max_bytes: int = MAX_SNAPSHOT_BYTES, max_depth: int = MAX_JSON_DEPTH) -> dict[str, Any]:
    """Read at most ``max_bytes + 1`` bytes before decoding untrusted JSON."""
    try:
        if os.stat(path).st_size > max_bytes:
            return _report("", [_reason("PAYLOAD_TOO_LARGE", "$", f"payload exceeds {max_bytes} bytes")], {})
        with open(path, "rb") as handle:
            raw = handle.read(max_bytes + 1)
    except (OSError, MemoryError) as exc:
        return _report("", [_reason("PAYLOAD_READ_ERROR", "$", str(exc))], {})
    if len(raw) > max_bytes:
        return _report("", [_reason("PAYLOAD_TOO_LARGE", "$", f"payload exceeds {max_bytes} bytes")], {})
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError, MemoryError) as exc:
        return _report("", [_reason("INVALID_JSON", "$", str(exc))], {})
    return validate_context_payload(payload, source_root=source_root, max_bytes=max_bytes, max_depth=max_depth)


__all__ = ["MAX_JSON_DEPTH", "MAX_SNAPSHOT_BYTES", "REPORT_SCHEMA", "canonical_json", "canonical_sha256", "validate_context_file", "validate_context_graph", "validate_context_payload", "validate_context_snapshot"]
