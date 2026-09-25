"""Bounded Python TurboQuant index build/query integration."""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Iterable, Literal

from .turboquant import (
    QuantizationError,
    QuantizedVector,
    approximate_candidates,
    exact_rerank,
    quantize,
)
from .vector_contracts import VECTOR_QUERY_RECEIPT_SCHEMA, validate_vector_query_receipt

SCHEMA = "simplicio.fast.vector-index-runtime/v1"
Metric = Literal["cosine", "dot", "l2"]
_METRICS = frozenset({"cosine", "dot", "l2"})


class VectorIndexError(ValueError):
    """A vector-index operation failed with a stable reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class _Entry:
    canonical_id: str
    integral: tuple[float, ...]
    quantized: QuantizedVector


def _vector(values: Iterable[float]) -> tuple[float, ...]:
    try:
        result = tuple(float(value) for value in values)
    except (TypeError, ValueError) as error:
        raise VectorIndexError(
            "vector_invalid", "vectors must be finite numeric iterables"
        ) from error
    if not result or any(not math.isfinite(value) for value in result):
        raise VectorIndexError(
            "vector_invalid", "vectors must be finite non-empty iterables"
        )
    return result


def _metric(metric: str) -> Metric:
    if metric not in _METRICS:
        raise VectorIndexError(
            "metric_unsupported", "metric must be cosine, dot, or l2"
        )
    return metric


def _positive(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise VectorIndexError("limit_invalid", f"{name} must be a positive integer")


class TurboQuantIndex:
    """Immutable packed candidate index with exact integral reranking.

    Persistence, mmap and Rust parity are separate acceptance gates.
    """

    def __init__(
        self, entries: tuple[_Entry, ...], *, seed: int, metric: Metric, generation: str
    ) -> None:
        self._entries = entries
        self.seed = seed
        self.metric = metric
        self.generation = generation

    @property
    def schema(self) -> str:
        return SCHEMA

    @property
    def dimension(self) -> int:
        return len(self._entries[0].integral)

    @property
    def size(self) -> int:
        return len(self._entries)

    @classmethod
    def build(
        cls,
        records: Iterable[tuple[str, Iterable[float]]],
        *,
        seed: int = 0,
        metric: Metric = "dot",
        generation: str = "python-memory-v1",
    ) -> "TurboQuantIndex":
        selected_metric = _metric(metric)
        if not isinstance(generation, str) or not generation.strip():
            raise VectorIndexError(
                "generation_invalid", "generation must be a non-empty string"
            )
        entries: list[_Entry] = []
        seen: set[str] = set()
        try:
            iterator = iter(records)
        except TypeError as error:
            raise VectorIndexError(
                "records_invalid", "records must be iterable"
            ) from error
        for raw_id, raw_vector in iterator:
            if not isinstance(raw_id, str) or not raw_id.strip():
                raise VectorIndexError(
                    "canonical_id_invalid", "canonical IDs must be non-empty strings"
                )
            if raw_id in seen:
                raise VectorIndexError(
                    "canonical_id_duplicate", "canonical IDs must be unique"
                )
            seen.add(raw_id)
            vector = _vector(raw_vector)
            if entries and len(vector) != len(entries[0].integral):
                raise VectorIndexError(
                    "dimension_mismatch", "all vectors must have one dimension"
                )
            try:
                packed = quantize(vector, seed)
            except QuantizationError as error:
                raise VectorIndexError("quantization_failed", str(error)) from error
            entries.append(_Entry(raw_id, vector, packed))
        if not entries:
            raise VectorIndexError("records_empty", "at least one vector is required")
        return cls(
            tuple(entries),
            seed=entries[0].quantized.seed,
            metric=selected_metric,
            generation=generation.strip(),
        )

    def query(
        self,
        query: Iterable[float],
        *,
        requested_k: int = 10,
        candidate_k: int | None = None,
    ) -> dict[str, Any]:
        _positive(requested_k, "requested_k")
        if candidate_k is None:
            candidate_k = max(requested_k, requested_k * 4)
        _positive(candidate_k, "candidate_k")
        if candidate_k < requested_k:
            raise VectorIndexError(
                "candidate_k_invalid", "candidate_k must cover requested_k"
            )
        query_vector = _vector(query)
        if len(query_vector) != self.dimension:
            raise VectorIndexError(
                "dimension_mismatch", "query dimension must match index"
            )
        started = time.perf_counter()
        try:
            approximate = approximate_candidates(
                query_vector,
                ((entry.canonical_id, entry.quantized) for entry in self._entries),
                seed=self.seed,
                metric=self.metric,
                candidate_k=candidate_k,
            )
        except QuantizationError as error:
            raise VectorIndexError("query_quantization_failed", str(error)) from error
        quantized_ms = (time.perf_counter() - started) * 1000
        scores = {item.canonical_id: item.score for item in approximate}
        integral = {entry.canonical_id: entry.integral for entry in self._entries}
        exact = exact_rerank(
            query_vector,
            ((item.canonical_id, integral[item.canonical_id]) for item in approximate),
            metric=self.metric,
            top_k=requested_k,
        )
        integral_ms = (time.perf_counter() - started) * 1000 - quantized_ms
        query_hash = hashlib.sha256(
            json.dumps(query_vector, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        receipt = {
            "schema": VECTOR_QUERY_RECEIPT_SCHEMA,
            "query_hash": query_hash,
            "policy_version": SCHEMA,
            "requested_k": requested_k,
            "candidate_k": candidate_k,
            "oversampling": candidate_k / requested_k,
            "engine": {"requested": "python", "selected": "python"},
            "timings": {"quantized_ms": quantized_ms, "integral_ms": integral_ms},
            "io": {"pages_read": 0, "bytes_read": 0},
            "cache": {"hit": False, "miss": True},
            "fallback": {"used": False, "reason_code": "none"},
            "results": [
                {
                    "canonical_id": item.canonical_id,
                    "quantized_score": scores[item.canonical_id],
                    "integral_score": item.score,
                }
                for item in exact
            ],
            "resources": {
                "cpu_ms": (time.perf_counter() - started) * 1000,
                "rss_bytes": None,
                "io_bytes": 0,
            },
            "status": "complete",
            "generation": self.generation,
        }
        try:
            validate_vector_query_receipt(receipt)
        except ValueError as error:
            raise VectorIndexError("receipt_invalid", str(error)) from error
        return receipt


__all__ = ["SCHEMA", "TurboQuantIndex", "VectorIndexError"]
