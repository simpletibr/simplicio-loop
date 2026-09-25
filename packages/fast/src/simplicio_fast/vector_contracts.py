"""Versioned contracts for the bounded TurboQuant vector-index slice."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

VECTOR_INDEX_SCHEMA = "simplicio.fast-vector-index/v1"
VECTOR_QUERY_RECEIPT_SCHEMA = "simplicio.fast-vector-query-receipt/v1"
SUPPORTED_METRICS = frozenset({"cosine", "dot", "l2"})
SUPPORTED_NORMALIZATIONS = frozenset({"none", "l2"})
SUPPORTED_INTEGRAL_FORMATS = frozenset({"fp16", "fp32"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEGMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class VectorContractError(ValueError):
    """A vector contract failed closed with a stable reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _mapping(value: Any, reason: str = "payload_not_object") -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VectorContractError(reason, "payload must be an object")
    return value


def _required(payload: Mapping[str, Any], name: str) -> Any:
    if name not in payload:
        raise VectorContractError("field_missing", f"missing field: {name}")
    return payload[name]


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VectorContractError("field_invalid", f"{name} must be a non-empty string")
    return value


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise VectorContractError(
            "field_invalid", f"{name} must be an integer >= {minimum}"
        )
    return value


def _number(value: Any, name: str, *, minimum: float = 0.0) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < minimum
    ):
        raise VectorContractError(
            "field_invalid", f"{name} must be a finite number >= {minimum}"
        )
    return float(value)


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise VectorContractError(
            "digest_invalid", f"{name} must be a lowercase SHA-256 digest"
        )
    return value


def _schema(payload: Mapping[str, Any], expected: str) -> None:
    actual = payload.get("schema")
    if actual == expected:
        return
    prefix = expected.rsplit("/", 1)[0] + "/v"
    if isinstance(actual, str) and actual.startswith(prefix):
        raise VectorContractError(
            "unsupported_schema", f"unsupported schema version: {actual}"
        )
    raise VectorContractError("schema_mismatch", f"expected {expected}")


def _validate_segment_list(value: Any) -> None:
    if not isinstance(value, list) or not value:
        raise VectorContractError(
            "segments_invalid", "segments must be a non-empty list"
        )
    ranges: list[tuple[int, int]] = []
    for index, raw in enumerate(value):
        segment = _mapping(raw, "segment_invalid")
        name = _text(_required(segment, "name"), f"segments[{index}].name")
        if not _SEGMENT_NAME.fullmatch(name):
            raise VectorContractError(
                "segment_name_invalid", f"invalid segment name: {name}"
            )
        offset = _integer(_required(segment, "offset"), f"segments[{index}].offset")
        size = _integer(
            _required(segment, "bytes"), f"segments[{index}].bytes", minimum=1
        )
        alignment = _integer(
            _required(segment, "alignment"), f"segments[{index}].alignment", minimum=1
        )
        if alignment & (alignment - 1) or offset % alignment:
            raise VectorContractError(
                "segment_alignment_invalid", f"segments[{index}] is not aligned"
            )
        if _required(segment, "endianness") != "little":
            raise VectorContractError(
                "endianness_unsupported", f"segments[{index}] must be little-endian"
            )
        _digest(_required(segment, "sha256"), f"segments[{index}].sha256")
        ranges.append((offset, offset + size))
    ranges.sort()
    if any(end > start for (_, end), (start, _) in zip(ranges, ranges[1:])):
        raise VectorContractError("segment_overlap", "vector segments overlap")


def validate_vector_index_manifest(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate a simplicio.fast-vector-index/v1 manifest."""
    payload = _mapping(payload)
    _schema(payload, VECTOR_INDEX_SCHEMA)
    for name in ("repository", "commit", "generation", "created_at"):
        _text(_required(payload, name), name)
    embedding = _mapping(_required(payload, "embedding"), "embedding_invalid")
    for name in ("model", "revision"):
        _text(_required(embedding, name), f"embedding.{name}")
    _integer(_required(embedding, "dimension"), "embedding.dimension", minimum=1)
    if _required(payload, "metric") not in SUPPORTED_METRICS:
        raise VectorContractError("metric_unsupported", "unsupported distance metric")
    if _required(payload, "normalization") not in SUPPORTED_NORMALIZATIONS:
        raise VectorContractError(
            "normalization_unsupported", "unsupported normalization"
        )
    quantizer = _mapping(_required(payload, "quantizer"), "quantizer_invalid")
    if _required(quantizer, "algorithm") != "turboquant-4bit":
        raise VectorContractError(
            "quantizer_unsupported", "manifest is not TurboQuant 4-bit"
        )
    _text(_required(quantizer, "format_version"), "quantizer.format_version")
    _digest(_required(quantizer, "rotation_seed_hash"), "quantizer.rotation_seed_hash")
    _digest(_required(quantizer, "codebook_hash"), "quantizer.codebook_hash")
    _integer(_required(payload, "vector_count"), "vector_count")
    mapping = _mapping(
        _required(payload, "canonical_id_mapping"), "canonical_id_mapping_invalid"
    )
    if _required(mapping, "owner") != "mapper":
        raise VectorContractError(
            "canonical_id_owner_invalid", "Mapper must own canonical IDs"
        )
    _text(_required(mapping, "format"), "canonical_id_mapping.format")
    _validate_segment_list(_required(payload, "segments"))
    integral = _mapping(_required(payload, "integral_store"), "integral_store_invalid")
    if _required(integral, "format") not in SUPPORTED_INTEGRAL_FORMATS:
        raise VectorContractError(
            "integral_format_unsupported", "integral store must be fp16 or fp32"
        )
    _text(_required(integral, "location"), "integral_store.location")
    _digest(_required(integral, "sha256"), "integral_store.sha256")
    source_hashes = _mapping(
        _required(payload, "build_source_hashes"), "build_source_hashes_invalid"
    )
    if not source_hashes:
        raise VectorContractError(
            "build_source_hashes_empty", "build source hashes are required"
        )
    for name, digest in source_hashes.items():
        _text(name, "build_source_hashes key")
        _digest(digest, f"build_source_hashes.{name}")
    flags = _required(payload, "compatibility_flags")
    if not isinstance(flags, list) or any(
        not isinstance(flag, str) or not flag for flag in flags
    ):
        raise VectorContractError(
            "compatibility_flags_invalid", "compatibility_flags must be a string list"
        )
    return payload


def _validate_resources(value: Any) -> None:
    resources = _mapping(value, "resources_invalid")
    for name in ("cpu_ms", "rss_bytes", "io_bytes"):
        metric = _required(resources, name)
        if metric is not None:
            _number(metric, f"resources.{name}")


def validate_vector_query_receipt(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate a simplicio.fast-vector-query-receipt/v1 receipt."""
    payload = _mapping(payload)
    _schema(payload, VECTOR_QUERY_RECEIPT_SCHEMA)
    _digest(_required(payload, "query_hash"), "query_hash")
    _text(_required(payload, "policy_version"), "policy_version")
    requested_k = _integer(_required(payload, "requested_k"), "requested_k", minimum=1)
    candidate_k = _integer(_required(payload, "candidate_k"), "candidate_k", minimum=1)
    if candidate_k < requested_k:
        raise VectorContractError(
            "candidate_k_invalid", "candidate_k must cover requested_k"
        )
    _number(_required(payload, "oversampling"), "oversampling", minimum=1.0)
    engine = _mapping(_required(payload, "engine"), "engine_invalid")
    _text(_required(engine, "requested"), "engine.requested")
    _text(_required(engine, "selected"), "engine.selected")
    timings = _mapping(_required(payload, "timings"), "timings_invalid")
    _number(_required(timings, "quantized_ms"), "timings.quantized_ms")
    _number(_required(timings, "integral_ms"), "timings.integral_ms")
    io = _mapping(_required(payload, "io"), "io_invalid")
    _integer(_required(io, "pages_read"), "io.pages_read")
    _integer(_required(io, "bytes_read"), "io.bytes_read")
    cache = _mapping(_required(payload, "cache"), "cache_invalid")
    for name in ("hit", "miss"):
        if not isinstance(_required(cache, name), bool):
            raise VectorContractError("cache_invalid", f"cache.{name} must be boolean")
    fallback = _mapping(_required(payload, "fallback"), "fallback_invalid")
    if not isinstance(_required(fallback, "used"), bool):
        raise VectorContractError("fallback_invalid", "fallback.used must be boolean")
    _text(_required(fallback, "reason_code"), "fallback.reason_code")
    results = _required(payload, "results")
    if not isinstance(results, list) or len(results) > candidate_k:
        raise VectorContractError(
            "results_invalid", "results must contain at most candidate_k items"
        )
    for index, raw in enumerate(results):
        result = _mapping(raw, "result_invalid")
        _text(_required(result, "canonical_id"), f"results[{index}].canonical_id")
        _number(
            _required(result, "quantized_score"),
            f"results[{index}].quantized_score",
            minimum=-math.inf,
        )
        _number(
            _required(result, "integral_score"),
            f"results[{index}].integral_score",
            minimum=-math.inf,
        )
    _validate_resources(_required(payload, "resources"))
    _text(_required(payload, "status"), "status")
    _text(_required(payload, "generation"), "generation")
    return payload


__all__ = [
    "VECTOR_INDEX_SCHEMA",
    "VECTOR_QUERY_RECEIPT_SCHEMA",
    "VectorContractError",
    "validate_vector_index_manifest",
    "validate_vector_query_receipt",
]
