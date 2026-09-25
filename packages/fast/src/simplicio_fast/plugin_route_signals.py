"""Structural Plugin v1 route signals. Fast measures; DecisionEngine decides."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .hbp_codec import seal_receipt, verify_chain
from .plugin_context_packet import validate_relative_path


SIGNALS_SCHEMA = "simplicio.plugin.route-signals/v1"
REQUEST_SCHEMA = "simplicio.plugin.route-signals-request/v1"
MANIFEST_SCHEMA = "simplicio.plugin.route-signals-manifest/v1"
HBP_SCHEMA = "simplicio.plugin.route-signals-hbp/v1"
ABI_MAJOR = 1
ABI_MINOR = 0
SIGNAL_NAMES = (
    "file_count",
    "fan_in",
    "fan_out",
    "hub",
    "sensitive",
    "diff_size",
    "cache_locality",
    "packet_bytes",
)
SIGNAL_UNITS = {
    "file_count": "count",
    "fan_in": "count",
    "fan_out": "count",
    "hub": "count",
    "sensitive": "count",
    "diff_size": "bytes",
    "cache_locality": "ratio",
    "packet_bytes": "bytes",
}
PHASES = frozenset({"pre_route", "post_diff"})
PROMOTION_RANKS = (
    "fast_path_candidate",
    "review_recommended",
    "full_path_recommended",
    "blocked_signal",
)
HUB_DEGREE = 8
MAX_GRAPH_NODES = 100_000
MAX_GRAPH_EDGES = 100_000
_SENSITIVE = re.compile(
    r"(?i)(^|/)(auth|oauth|secret|credential|passwd|password|crypto|permission|iam|token|\.env)(/|$|\.)"
)


class PluginRouteSignalsError(ValueError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise PluginRouteSignalsError("signals_not_json") from error


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _required_text(value: object, reason: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PluginRouteSignalsError(reason)
    return value


def contract_manifest() -> dict[str, Any]:
    return {
        "schema": MANIFEST_SCHEMA,
        "signals_schema": SIGNALS_SCHEMA,
        "request_schema": REQUEST_SCHEMA,
        "hbp_schema": HBP_SCHEMA,
        "abi": {"major": ABI_MAJOR, "minor": ABI_MINOR},
        "signals": list(SIGNAL_NAMES),
        "phases": sorted(PHASES),
        "promotion_ranks": list(PROMOTION_RANKS),
        "authority": "derived_read_only",
        "decides_policy": False,
        "writes": False,
        "fabricates_savings": False,
        "unknown_policy": "null_plus_reason",
        "consumers": ["runtime-r05", "loop-l01"],
    }


def _unknown(name: str, reason: str, provenance: str) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "unknown",
        "value": None,
        "unit": SIGNAL_UNITS[name],
        "lower_bound": None,
        "upper_bound": None,
        "unknown_reason": reason,
        "provenance": provenance,
    }


def _measured(
    name: str,
    value: int | float,
    provenance: str,
    *,
    lower: int | float | None = None,
    upper: int | float | None = None,
    kind: str = "measured",
) -> dict[str, Any]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PluginRouteSignalsError("signal_value_invalid", name)
    if kind not in {"measured", "bounded_estimate"}:
        raise PluginRouteSignalsError("signal_kind_invalid", kind)
    return {
        "name": name,
        "kind": kind,
        "value": value,
        "unit": SIGNAL_UNITS[name],
        "lower_bound": value if lower is None else lower,
        "upper_bound": value if upper is None else upper,
        "unknown_reason": None,
        "provenance": provenance,
    }


def _validate_path(value: str) -> str:
    try:
        return validate_relative_path(value)
    except Exception as error:
        raise PluginRouteSignalsError("path_escape", value) from error


@dataclass(frozen=True, slots=True)
class PluginRouteRequest:
    generation: str
    source_hashes: Mapping[str, str]
    targets: Sequence[str]
    phase: str = "pre_route"
    graph: Mapping[str, Any] | None = None
    packet_metadata: Mapping[str, Any] | None = None
    cache_state: Mapping[str, Any] | None = None
    diff: Mapping[str, Any] | None = None
    previous_promotion: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.generation, "generation_missing")
        if self.phase not in PHASES:
            raise PluginRouteSignalsError("phase_invalid", self.phase)
        if not isinstance(self.source_hashes, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str) or len(value) != 64
            for key, value in self.source_hashes.items()
        ):
            raise PluginRouteSignalsError("source_hashes_invalid")
        object.__setattr__(
            self,
            "source_hashes",
            {_validate_path(key): value for key, value in self.source_hashes.items()},
        )
        if not isinstance(self.targets, (tuple, list)):
            raise PluginRouteSignalsError("targets_invalid")
        object.__setattr__(self, "targets", tuple(self.targets))
        if self.previous_promotion is not None and self.previous_promotion not in PROMOTION_RANKS:
            raise PluginRouteSignalsError("promotion_invalid", str(self.previous_promotion))


def compile_route_signals(request: PluginRouteRequest) -> dict[str, Any]:
    """Emit numeric evidence only. Never allow/deny, pick a skill, or invent savings."""
    vague = _vague_targets(request.targets)
    file_count = _file_count(request.targets, vague)
    graph_signals = _graph_signals(request.targets, request.graph)
    sensitive = _sensitive_signal(request.targets, vague)
    diff_size = _diff_signal(request)
    cache_locality = _cache_signal(request.cache_state)
    packet_bytes = _packet_signal(request.packet_metadata)
    signals = {
        "file_count": file_count,
        "fan_in": graph_signals["fan_in"],
        "fan_out": graph_signals["fan_out"],
        "hub": graph_signals["hub"],
        "sensitive": sensitive,
        "diff_size": diff_size,
        "cache_locality": cache_locality,
        "packet_bytes": packet_bytes,
    }
    promotion = _promotion(signals, vague, request)
    body = {
        "schema": SIGNALS_SCHEMA,
        "abi": {"major": ABI_MAJOR, "minor": ABI_MINOR},
        "generation": request.generation,
        "source_hashes": dict(sorted(request.source_hashes.items())),
        "phase": request.phase,
        "targets": list(request.targets),
        "signals": signals,
        "promotion_evidence": promotion,
        "decision": None,
        "decision_null_reason": "FAST_NOT_POLICY_AUTHORITY",
        "savings": None,
        "savings_null_reason": "SAVINGS_NOT_MEASURED",
        "route": None,
        "route_null_reason": "FAST_DOES_NOT_SELECT_ROUTE",
        "skills": None,
        "skills_null_reason": "FAST_DOES_NOT_SELECT_SKILLS",
        "authority": "derived_read_only",
        "writes": False,
        "consumers": ["runtime-r05", "loop-l01"],
        "graph_truncated": graph_signals["truncated"],
        "graph_digest": graph_signals["digest"],
    }
    encoded = _canonical(body)
    body["encoded_bytes"] = len(encoded)
    body["signals_hash"] = _digest(body)
    return body


def verify_route_signals(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema") != SIGNALS_SCHEMA:
        raise PluginRouteSignalsError("signals_schema_invalid")
    unsigned = dict(value)
    supplied = unsigned.pop("signals_hash", "")
    if supplied != _digest(unsigned):
        raise PluginRouteSignalsError("signals_corrupt")
    if value.get("decision") is not None:
        raise PluginRouteSignalsError("policy_decision_forbidden")
    if value.get("savings") is not None:
        raise PluginRouteSignalsError("savings_fabricated")
    for name, signal in value.get("signals", {}).items():
        if name not in SIGNAL_NAMES or not isinstance(signal, Mapping):
            raise PluginRouteSignalsError("signal_invalid", str(name))
        if signal.get("kind") == "unknown":
            if signal.get("value") is not None:
                raise PluginRouteSignalsError("unknown_became_value", name)
            if not signal.get("unknown_reason"):
                raise PluginRouteSignalsError("unknown_reason_missing", name)
    return dict(value)


def encode_hbp(signals: Mapping[str, Any]) -> str:
    verified = verify_route_signals(signals)
    encoded = base64.urlsafe_b64encode(_canonical(verified)).decode("ascii")
    return seal_receipt(
        f"schema={HBP_SCHEMA}|kind=signals|digest={verified['signals_hash']}|payload={encoded}"
    )


def decode_hbp(row: str) -> dict[str, Any]:
    if not isinstance(row, str) or not row:
        raise PluginRouteSignalsError("signals_corrupt", "hbp")
    verify_chain([row])
    body = row.rsplit("|event_hash=", 1)[0].rsplit("|prev_event_hash=", 1)[0]
    fields = dict(part.split("=", 1) for part in body.split("|"))
    if fields.get("schema") != HBP_SCHEMA:
        raise PluginRouteSignalsError("signals_schema_invalid")
    payload = json.loads(
        base64.b64decode(fields["payload"].encode("ascii"), altchars=b"-_", validate=True)
    )
    verified = verify_route_signals(payload)
    if verified["signals_hash"] != fields.get("digest"):
        raise PluginRouteSignalsError("signals_corrupt", "hbp_digest")
    return verified


def _vague_targets(targets: Sequence[str]) -> bool:
    if not targets:
        return True
    return any(
        not isinstance(item, str)
        or not item.strip()
        or "*" in item
        or item in {".", "/"}
        for item in targets
    )


def _file_count(targets: Sequence[str], vague: bool) -> dict[str, Any]:
    if vague and not targets:
        return _unknown("file_count", "targets_missing", "input")
    if vague:
        return _unknown("file_count", "targets_vague", "input")
    paths = {_validate_path(item) for item in targets}
    return _measured("file_count", len(paths), "input")


def _graph_signals(
    targets: Sequence[str], graph: Mapping[str, Any] | None
) -> dict[str, Any]:
    empty = {
        "fan_in": _unknown("fan_in", "graph_missing", "graph"),
        "fan_out": _unknown("fan_out", "graph_missing", "graph"),
        "hub": _unknown("hub", "graph_missing", "graph"),
        "truncated": False,
        "digest": None,
    }
    if graph is None:
        return empty
    if not isinstance(graph, Mapping):
        raise PluginRouteSignalsError("graph_invalid")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
        raise PluginRouteSignalsError("graph_invalid", "nodes")
    if not isinstance(edges, Sequence) or isinstance(edges, (str, bytes)):
        raise PluginRouteSignalsError("graph_invalid", "edges")
    if len(nodes) > MAX_GRAPH_NODES or len(edges) > MAX_GRAPH_EDGES:
        raise PluginRouteSignalsError("graph_limit")
    normalized_nodes = [_validate_path(str(node)) for node in nodes]
    inbound: dict[str, int] = {node: 0 for node in normalized_nodes}
    outbound: dict[str, int] = {node: 0 for node in normalized_nodes}
    canonical_edges: list[tuple[str, str]] = []
    for edge in edges:
        if not isinstance(edge, Mapping):
            raise PluginRouteSignalsError("graph_invalid", "edge")
        src = _validate_path(str(edge.get("from", "")))
        dst = _validate_path(str(edge.get("to", "")))
        inbound[dst] = inbound.get(dst, 0) + 1
        outbound[src] = outbound.get(src, 0) + 1
        canonical_edges.append((src, dst))
    focus = [_validate_path(item) for item in targets] if targets and not _vague_targets(targets) else normalized_nodes
    if not focus:
        return {
            "fan_in": _unknown("fan_in", "targets_missing", "graph"),
            "fan_out": _unknown("fan_out", "targets_missing", "graph"),
            "hub": _unknown("hub", "targets_missing", "graph"),
            "truncated": False,
            "digest": _digest({"nodes": normalized_nodes, "edges": canonical_edges}),
        }
    fan_in = max(inbound.get(node, 0) for node in focus)
    fan_out = max(outbound.get(node, 0) for node in focus)
    hub = max(inbound.get(node, 0) + outbound.get(node, 0) for node in focus)
    truncated = bool(graph.get("truncated"))
    kind = "bounded_estimate" if truncated else "measured"
    digest = _digest({"nodes": sorted(normalized_nodes), "edges": sorted(canonical_edges)})
    return {
        "fan_in": _measured("fan_in", fan_in, "graph", kind=kind),
        "fan_out": _measured("fan_out", fan_out, "graph", kind=kind),
        "hub": _measured("hub", hub, "graph", kind=kind),
        "truncated": truncated,
        "digest": digest,
    }


def _sensitive_signal(targets: Sequence[str], vague: bool) -> dict[str, Any]:
    if vague and not targets:
        return _unknown("sensitive", "targets_missing", "input")
    if vague:
        return _unknown("sensitive", "targets_vague", "input")
    count = sum(1 for item in targets if _SENSITIVE.search(_validate_path(item)))
    return _measured("sensitive", count, "input")


def _diff_signal(request: PluginRouteRequest) -> dict[str, Any]:
    if request.diff is None:
        reason = "diff_missing" if request.phase == "post_diff" else "diff_not_provided"
        return _unknown("diff_size", reason, "diff")
    if not isinstance(request.diff, Mapping):
        raise PluginRouteSignalsError("diff_invalid")
    if "bytes" in request.diff:
        value = request.diff["bytes"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PluginRouteSignalsError("diff_invalid", "bytes")
        return _measured("diff_size", value, "diff")
    added = request.diff.get("added_lines")
    removed = request.diff.get("removed_lines")
    if (
        isinstance(added, bool)
        or isinstance(removed, bool)
        or not isinstance(added, int)
        or not isinstance(removed, int)
        or added < 0
        or removed < 0
    ):
        raise PluginRouteSignalsError("diff_invalid", "lines")
    return _measured("diff_size", added + removed, "diff")


def _cache_signal(state: Mapping[str, Any] | None) -> dict[str, Any]:
    if state is None:
        return _unknown("cache_locality", "cache_state_missing", "cache")
    if not isinstance(state, Mapping):
        raise PluginRouteSignalsError("cache_state_invalid")
    hits = state.get("hits")
    misses = state.get("misses")
    if (
        isinstance(hits, bool)
        or isinstance(misses, bool)
        or not isinstance(hits, int)
        or not isinstance(misses, int)
        or hits < 0
        or misses < 0
    ):
        raise PluginRouteSignalsError("cache_state_invalid")
    total = hits + misses
    if total == 0:
        return _unknown("cache_locality", "cache_empty", "cache")
    return _measured("cache_locality", hits / total, "cache")


def _packet_signal(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    if metadata is None:
        return _unknown("packet_bytes", "packet_metadata_missing", "packet")
    if not isinstance(metadata, Mapping):
        raise PluginRouteSignalsError("packet_metadata_invalid")
    value = metadata.get("encoded_bytes")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PluginRouteSignalsError("packet_metadata_invalid")
    return _measured("packet_bytes", value, "packet")


def _rank(name: str) -> int:
    return PROMOTION_RANKS.index(name)


def _promotion(
    signals: Mapping[str, Mapping[str, Any]],
    vague: bool,
    request: PluginRouteRequest,
) -> dict[str, Any]:
    rank = "fast_path_candidate"
    reasons: list[str] = []
    if vague:
        rank = "review_recommended"
        reasons.append("targets_vague_or_missing")
    hub = signals["hub"]
    if hub["kind"] != "unknown" and hub["value"] >= HUB_DEGREE:
        rank = _max_rank(rank, "review_recommended")
        reasons.append("hub_degree")
    if signals["sensitive"]["kind"] != "unknown" and signals["sensitive"]["value"] >= 1:
        rank = _max_rank(rank, "full_path_recommended")
        reasons.append("sensitive_surface")
    if request.graph is None and len([item for item in request.targets if isinstance(item, str) and item]) > 1:
        rank = _max_rank(rank, "review_recommended")
        reasons.append("missing_map")
    if request.phase == "post_diff":
        diff = signals["diff_size"]
        packet = signals["packet_bytes"]
        if diff["kind"] == "unknown":
            rank = _max_rank(rank, "review_recommended")
            reasons.append("post_diff_missing")
        elif (
            packet["kind"] != "unknown"
            and isinstance(diff["value"], int)
            and isinstance(packet["value"], int)
            and diff["value"] > packet["value"]
        ):
            rank = _max_rank(rank, "full_path_recommended")
            reasons.append("diff_overshoot")
    if request.previous_promotion is not None and _rank(rank) < _rank(request.previous_promotion):
        reasons.append("monotonic_hold")
        rank = request.previous_promotion
    return {
        "rank": rank,
        "previous_rank": request.previous_promotion,
        "monotonic": True,
        "reasons": reasons,
        "decides_policy": False,
    }


def _max_rank(left: str, right: str) -> str:
    return left if _rank(left) >= _rank(right) else right


def measure_route_signals(
    request: PluginRouteRequest,
    *,
    iterations: int = 21,
    batch_size: int = 8,
) -> dict[str, Any]:
    if (
        isinstance(iterations, bool)
        or isinstance(batch_size, bool)
        or not isinstance(iterations, int)
        or not isinstance(batch_size, int)
        or iterations < 1
        or batch_size < 1
    ):
        raise PluginRouteSignalsError("benchmark_invalid")
    cold0 = time.perf_counter_ns()
    first = compile_route_signals(request)
    cold_ns = time.perf_counter_ns() - cold0
    warm: list[int] = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        compile_route_signals(request)
        warm.append(time.perf_counter_ns() - started)
    batch0 = time.perf_counter_ns()
    for _ in range(batch_size):
        compile_route_signals(request)
    batch_ns = time.perf_counter_ns() - batch0
    ordered = sorted(warm)
    rss = _rss_kib()
    return {
        "schema": "simplicio.plugin.route-signals-benchmark/v1",
        "iterations": iterations,
        "batch_size": batch_size,
        "cold_ns": cold_ns,
        "warm_p50_ns": ordered[len(ordered) // 2],
        "warm_p95_ns": ordered[max(0, int(len(ordered) * 0.95) - 1)],
        "warm_p99_ns": ordered[max(0, int(len(ordered) * 0.99) - 1)],
        "batch_ns": batch_ns,
        "throughput_per_s": None
        if batch_ns == 0
        else (batch_size * 1_000_000_000) / batch_ns,
        "raw_warm_ns": warm,
        "encoded_bytes": first["encoded_bytes"],
        "rss_kib": rss,
        "rss_kib_null_reason": None if rss is not None else "RSS_UNAVAILABLE",
        "tokens": None,
        "tokens_null_reason": "NO_LLM_USED",
    }


def _rss_kib() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


__all__ = [
    "ABI_MAJOR",
    "HBP_SCHEMA",
    "PROMOTION_RANKS",
    "SIGNALS_SCHEMA",
    "PluginRouteRequest",
    "PluginRouteSignalsError",
    "compile_route_signals",
    "contract_manifest",
    "decode_hbp",
    "encode_hbp",
    "measure_route_signals",
    "verify_route_signals",
]
