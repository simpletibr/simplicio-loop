"""Runtime-first semantic scoring with a deterministic offline fallback.

The source snapshot and Mapper handles remain authoritative. Embeddings and
reranking are disposable, content-addressed derived data and are never treated
as evidence of a code relationship.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


SCORE_SCHEMA = "simplicio.fast.semantic-score/v1"
ARTIFACT_SCHEMA = "simplicio.fast.semantic-vector-artifact/v1"
INFERENCE_BACKEND_SCHEMA = "simplicio.inference-backend/v1"
INFERENCE_REQUEST_SCHEMA = "simplicio.inference-request/v1"
INFERENCE_RESULT_SCHEMA = "simplicio.inference-result/v1"
FORMULA_VERSION = "lexical-structural-semantic/v1"
PREPROCESSING_SCHEMA = "simplicio.fast.semantic-preprocessing/v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WORD = re.compile(r"[A-Za-z0-9_]+")


class SemanticScoringError(RuntimeError):
    """A semantic lane operation failed with a stable reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _finite(value: object, field: str, *, minimum: float = 0.0) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or float(value) < minimum
    ):
        raise ValueError(f"{field} must be a finite number >= {minimum}")
    return float(value)


def _positive(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _validate_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """Runtime-supplied model identity; Fast never downloads a model."""

    model: str
    version: str
    sha256: str
    preprocessing: str
    dimension: int
    max_tokens: int
    license: str

    def __post_init__(self) -> None:
        for field in ("model", "version", "preprocessing", "license"):
            _required_text(getattr(self, field), field)
        _validate_digest(self.sha256, "sha256")
        _positive(self.dimension, "dimension")
        _positive(self.max_tokens, "max_tokens")

    @property
    def preprocessing_hash(self) -> str:
        return _digest({"schema": PREPROCESSING_SCHEMA, "name": self.preprocessing})

    def record(self) -> dict[str, object]:
        return {
            **asdict(self),
            "preprocessing_hash": self.preprocessing_hash,
        }


@dataclass(frozen=True, slots=True)
class SourceDocument:
    canonical_id: str
    text: str
    source_sha256: str
    structural_score: float = 0.0

    def __post_init__(self) -> None:
        _required_text(self.canonical_id, "canonical_id")
        if not isinstance(self.text, str):
            raise ValueError("text must be a string")
        _validate_digest(self.source_sha256, "source_sha256")
        score = _finite(self.structural_score, "structural_score")
        if score > 1.0:
            raise ValueError("structural_score must be <= 1")
        if _sha_bytes(self.text.encode("utf-8")) != self.source_sha256:
            raise ValueError("source_sha256 does not match text")

    @classmethod
    def create(
        cls, canonical_id: str, text: str, *, structural_score: float = 0.0
    ) -> "SourceDocument":
        return cls(
            canonical_id,
            text,
            _sha_bytes(text.encode("utf-8")),
            structural_score,
        )


@dataclass(frozen=True, slots=True)
class SemanticBudgets:
    max_candidates: int = 128
    max_selected: int = 10
    max_request_bytes: int = 256_000
    max_index_bytes: int = 64 * 1024 * 1024
    max_memory_bytes: int = 128 * 1024 * 1024
    max_batch_size: int = 16
    max_queue_depth: int = 8
    max_latency_ms: int = 2_000
    max_selected_tokens: int = 8_000

    def __post_init__(self) -> None:
        for field in self.__dataclass_fields__:
            _positive(getattr(self, field), field)
        if self.max_selected > self.max_candidates:
            raise ValueError("max_selected cannot exceed max_candidates")
        if self.max_index_bytes > self.max_memory_bytes:
            raise ValueError("max_index_bytes cannot exceed max_memory_bytes")

    def record(self) -> dict[str, int]:
        return asdict(self)


@runtime_checkable
class InferenceBackend(Protocol):
    """Runtime-owned InferenceBackend/v1 surface."""

    def capabilities(self) -> Mapping[str, Any]: ...

    def infer(
        self,
        request: Mapping[str, Any],
        *,
        deadline: float,
        cancel_event: threading.Event | None,
    ) -> Mapping[str, Any]: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Optional embedding SPI with no LiteRT import or hard dependency."""

    @property
    def identity(self) -> ModelIdentity: ...

    def embed(
        self,
        texts: Sequence[str],
        *,
        deadline: float,
        cancel_event: threading.Event | None,
    ) -> tuple[tuple[float, ...], ...]: ...


@runtime_checkable
class Reranker(Protocol):
    """Optional reranker SPI. Returned scores must be normalized."""

    def rerank(
        self,
        query: str,
        candidates: Sequence[SourceDocument],
        *,
        deadline: float,
        cancel_event: threading.Event | None,
    ) -> Mapping[str, float]: ...


def _check_cancel_deadline(
    deadline: float, cancel_event: threading.Event | None
) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise SemanticScoringError("INFERENCE_CANCELLED")
    if time.monotonic() >= deadline:
        raise SemanticScoringError("INFERENCE_DEADLINE_EXCEEDED")


def _validated_vectors(
    raw: object, *, expected: int, dimension: int
) -> tuple[tuple[float, ...], ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise SemanticScoringError("INFERENCE_RESPONSE_MALFORMED", "vectors")
    if len(raw) != expected:
        raise SemanticScoringError("INFERENCE_RESPONSE_COUNT_MISMATCH")
    vectors: list[tuple[float, ...]] = []
    for candidate in raw:
        if not isinstance(candidate, Sequence) or isinstance(candidate, (str, bytes)):
            raise SemanticScoringError("INFERENCE_RESPONSE_MALFORMED", "vector")
        try:
            vector = tuple(float(value) for value in candidate)
        except (TypeError, ValueError) as error:
            raise SemanticScoringError("INFERENCE_RESPONSE_MALFORMED") from error
        if len(vector) != dimension:
            raise SemanticScoringError("INFERENCE_DIMENSION_MISMATCH")
        if any(not math.isfinite(value) for value in vector):
            raise SemanticScoringError("INFERENCE_VECTOR_NONFINITE")
        vectors.append(vector)
    return tuple(vectors)


class RuntimeEmbeddingProvider:
    """Provider that delegates execution to Runtime's InferenceBackend/v1."""

    def __init__(self, backend: InferenceBackend, identity: ModelIdentity) -> None:
        self.backend = backend
        self._identity = identity
        capabilities = backend.capabilities()
        if capabilities.get("schema") != INFERENCE_BACKEND_SCHEMA:
            raise SemanticScoringError("INFERENCE_BACKEND_ABI_MISMATCH")
        operations = capabilities.get("operations")
        if (
            not isinstance(operations, Sequence)
            or isinstance(operations, (str, bytes))
            or "embeddings" not in operations
        ):
            raise SemanticScoringError("INFERENCE_BACKEND_CAPABILITY_MISSING")

    @property
    def identity(self) -> ModelIdentity:
        return self._identity

    def embed(
        self,
        texts: Sequence[str],
        *,
        deadline: float,
        cancel_event: threading.Event | None,
    ) -> tuple[tuple[float, ...], ...]:
        _check_cancel_deadline(deadline, cancel_event)
        if not texts:
            return ()
        if any(not isinstance(text, str) for text in texts):
            raise SemanticScoringError("INFERENCE_INPUT_INVALID")
        request = {
            "schema": INFERENCE_REQUEST_SCHEMA,
            "operation": "embeddings",
            "model": self.identity.record(),
            "inputs": list(texts),
            "deadline_unix_ms": int(
                (time.time() + max(0.0, deadline - time.monotonic())) * 1000
            ),
        }
        try:
            result = self.backend.infer(
                request, deadline=deadline, cancel_event=cancel_event
            )
        except SemanticScoringError:
            raise
        except Exception as error:
            raise SemanticScoringError(
                "INFERENCE_BACKEND_FAILURE", type(error).__name__
            ) from error
        _check_cancel_deadline(deadline, cancel_event)
        if result.get("schema") != INFERENCE_RESULT_SCHEMA:
            raise SemanticScoringError("INFERENCE_RESPONSE_SCHEMA_MISMATCH")
        if result.get("model_sha256") != self.identity.sha256:
            raise SemanticScoringError("INFERENCE_MODEL_MISMATCH")
        return _validated_vectors(
            result.get("vectors"),
            expected=len(texts),
            dimension=self.identity.dimension,
        )


class LocalLiteRTAdapter:
    """Test-only adapter around an injected LiteRT-like session.

    This module never imports, installs or downloads LiteRT. Production callers
    must use :class:`RuntimeEmbeddingProvider`; direct sessions are permitted
    only when ``isolated_test=True`` is explicit.
    """

    def __init__(
        self,
        session: object,
        identity: ModelIdentity,
        *,
        isolated_test: bool = False,
    ) -> None:
        if not isolated_test:
            raise SemanticScoringError("DIRECT_LITERT_FORBIDDEN")
        if not callable(getattr(session, "embed", None)):
            raise SemanticScoringError("LITERT_SESSION_INVALID")
        self.session = session
        self._identity = identity

    @property
    def identity(self) -> ModelIdentity:
        return self._identity

    def embed(
        self,
        texts: Sequence[str],
        *,
        deadline: float,
        cancel_event: threading.Event | None,
    ) -> tuple[tuple[float, ...], ...]:
        _check_cancel_deadline(deadline, cancel_event)
        try:
            result = self.session.embed(tuple(texts))
        except Exception as error:
            raise SemanticScoringError(
                "LITERT_INFERENCE_FAILURE", type(error).__name__
            ) from error
        _check_cancel_deadline(deadline, cancel_event)
        return _validated_vectors(
            result, expected=len(texts), dimension=self.identity.dimension
        )


class DerivedVectorStore:
    """Content-addressed vectors scoped by generation/model/preprocessing."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @staticmethod
    def cache_key(generation: str, model: ModelIdentity) -> str:
        _required_text(generation, "generation")
        return _digest(
            {
                "schema": ARTIFACT_SCHEMA,
                "generation": generation,
                "model_sha256": model.sha256,
                "preprocessing_hash": model.preprocessing_hash,
            }
        )

    def _manifest_path(self, generation: str, model: ModelIdentity) -> Path:
        return self.root / "manifests" / f"{self.cache_key(generation, model)}.json"

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _read(
        self, generation: str, model: ModelIdentity
    ) -> tuple[dict[str, Any], dict[str, list[float]]]:
        manifest_path = self._manifest_path(generation, model)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise SemanticScoringError("VECTOR_ARTIFACT_MISSING") from error
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SemanticScoringError("VECTOR_ARTIFACT_CORRUPT") from error
        expected = {
            "schema": ARTIFACT_SCHEMA,
            "generation": generation,
            "model_sha256": model.sha256,
            "preprocessing_hash": model.preprocessing_hash,
            "dimension": model.dimension,
        }
        if any(manifest.get(name) != value for name, value in expected.items()):
            raise SemanticScoringError("VECTOR_ARTIFACT_SCOPE_MISMATCH")
        filename = manifest.get("vectors_file")
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not filename.endswith(".vectors.json")
        ):
            raise SemanticScoringError("VECTOR_ARTIFACT_CORRUPT")
        path = self.root / "objects" / filename
        try:
            content = path.read_bytes()
        except OSError as error:
            raise SemanticScoringError("VECTOR_ARTIFACT_CORRUPT") from error
        if _sha_bytes(content) != manifest.get("vectors_sha256"):
            raise SemanticScoringError("VECTOR_ARTIFACT_CORRUPT")
        try:
            vectors = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SemanticScoringError("VECTOR_ARTIFACT_CORRUPT") from error
        if not isinstance(vectors, dict):
            raise SemanticScoringError("VECTOR_ARTIFACT_CORRUPT")
        normalized: dict[str, list[float]] = {}
        for canonical_id, raw in vectors.items():
            vector = _validated_vectors([raw], expected=1, dimension=model.dimension)[0]
            normalized[str(canonical_id)] = list(vector)
        if set(normalized) != set(manifest.get("source_hashes", {})):
            raise SemanticScoringError("VECTOR_ARTIFACT_CORRUPT")
        return manifest, normalized

    def load(
        self, generation: str, model: ModelIdentity
    ) -> tuple[dict[str, Any], dict[str, tuple[float, ...]]]:
        manifest, vectors = self._read(generation, model)
        return manifest, {key: tuple(value) for key, value in sorted(vectors.items())}

    def refresh(
        self,
        generation: str,
        model: ModelIdentity,
        sources: Sequence[SourceDocument],
        provider: EmbeddingProvider,
        budgets: SemanticBudgets,
        *,
        deadline: float,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        _required_text(generation, "generation")
        ordered = sorted(sources, key=lambda item: item.canonical_id)
        if len(ordered) > budgets.max_candidates:
            raise SemanticScoringError("CANDIDATE_BUDGET_EXCEEDED")
        if len({item.canonical_id for item in ordered}) != len(ordered):
            raise SemanticScoringError("CANONICAL_ID_DUPLICATE")
        request_bytes = sum(len(item.text.encode("utf-8")) for item in ordered)
        if request_bytes > budgets.max_request_bytes:
            raise SemanticScoringError("REQUEST_BYTES_BUDGET_EXCEEDED")
        corrupt_rebuilt = False
        try:
            old_manifest, old_vectors = self._read(generation, model)
        except SemanticScoringError as error:
            if error.reason_code not in {
                "VECTOR_ARTIFACT_MISSING",
                "VECTOR_ARTIFACT_CORRUPT",
            }:
                raise
            corrupt_rebuilt = error.reason_code == "VECTOR_ARTIFACT_CORRUPT"
            old_manifest, old_vectors = {}, {}
        old_hashes = old_manifest.get("source_hashes", {})
        changed = [
            item
            for item in ordered
            if old_hashes.get(item.canonical_id) != item.source_sha256
        ]
        vectors: dict[str, list[float]] = {
            item.canonical_id: old_vectors[item.canonical_id]
            for item in ordered
            if item.canonical_id in old_vectors
            and old_hashes.get(item.canonical_id) == item.source_sha256
        }
        batches = 0
        for offset in range(0, len(changed), budgets.max_batch_size):
            _check_cancel_deadline(deadline, cancel_event)
            batch = changed[offset : offset + budgets.max_batch_size]
            embedded = provider.embed(
                [item.text for item in batch],
                deadline=deadline,
                cancel_event=cancel_event,
            )
            for item, vector in zip(batch, embedded):
                vectors[item.canonical_id] = list(vector)
            batches += 1
        vectors = {key: vectors[key] for key in sorted(vectors)}
        vector_bytes = _canonical(vectors)
        if len(vector_bytes) > budgets.max_index_bytes:
            raise SemanticScoringError("INDEX_BYTES_BUDGET_EXCEEDED")
        vector_sha = _sha_bytes(vector_bytes)
        filename = f"{vector_sha}.vectors.json"
        manifest = {
            "schema": ARTIFACT_SCHEMA,
            "generation": generation,
            "model": model.record(),
            "model_sha256": model.sha256,
            "preprocessing_hash": model.preprocessing_hash,
            "dimension": model.dimension,
            "source_hashes": {
                item.canonical_id: item.source_sha256 for item in ordered
            },
            "vectors_file": filename,
            "vectors_sha256": vector_sha,
            "vector_count": len(vectors),
            "bytes": len(vector_bytes),
        }
        manifest_bytes = _canonical(manifest)
        if len(vector_bytes) + len(manifest_bytes) > budgets.max_memory_bytes:
            raise SemanticScoringError("MEMORY_BUDGET_EXCEEDED")
        self._atomic_write(self.root / "objects" / filename, vector_bytes)
        self._atomic_write(self._manifest_path(generation, model), manifest_bytes)
        return {
            "schema": "simplicio.fast.semantic-refresh-receipt/v1",
            "generation": generation,
            "cache_key": self.cache_key(generation, model),
            "artifact_sha256": vector_sha,
            "model": model.record(),
            "source_count": len(ordered),
            "embedded": len(changed),
            "reused": len(ordered) - len(changed),
            "removed": len(set(old_vectors) - {item.canonical_id for item in ordered}),
            "batches": batches,
            "bytes": len(vector_bytes),
            "corrupt_rebuilt": corrupt_rebuilt,
        }


def _tokens(value: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for raw in _WORD.findall(value):
        for piece in raw.split("_"):
            if not piece:
                continue
            parts = re.findall(
                r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+",
                piece,
            )
            tokens.extend(parts or [piece])
    return tuple(token.casefold() for token in tokens)


def lexical_score(query: str, text: str) -> float:
    """Deterministic token-overlap score in [0, 1]."""
    query_terms = set(_tokens(query))
    if not query_terms:
        return 0.0
    text_terms = set(_tokens(text))
    return len(query_terms.intersection(text_terms)) / len(query_terms)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise SemanticScoringError("INFERENCE_DIMENSION_MISMATCH")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    cosine = dot / (left_norm * right_norm) if left_norm and right_norm else 0.0
    return max(0.0, min(1.0, (cosine + 1.0) / 2.0))


class SemanticScorer:
    """Quality-first scorer with bounded Runtime inference and lexical fallback."""

    def __init__(
        self,
        *,
        provider: EmbeddingProvider | None = None,
        reranker: Reranker | None = None,
        store: DerivedVectorStore | None = None,
        budgets: SemanticBudgets | None = None,
        minimum_confidence: float = 0.12,
    ) -> None:
        if provider is not None and store is None:
            raise ValueError("a derived vector store is required with a provider")
        self.provider = provider
        self.reranker = reranker
        self.store = store
        self.budgets = budgets or SemanticBudgets()
        self.minimum_confidence = _finite(minimum_confidence, "minimum_confidence")
        if self.minimum_confidence > 1:
            raise ValueError("minimum_confidence must be <= 1")
        self._queue_lock = threading.Lock()
        self._pending = 0
        self.metrics: Counter[str] = Counter()

    def _enter(self) -> None:
        with self._queue_lock:
            if self._pending >= self.budgets.max_queue_depth:
                raise SemanticScoringError("INFERENCE_BACKPRESSURE")
            self._pending += 1

    def _leave(self) -> None:
        with self._queue_lock:
            self._pending -= 1

    def score(
        self,
        *,
        generation: str,
        query: str,
        candidates: Sequence[SourceDocument],
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        _required_text(generation, "generation")
        _required_text(query, "query")
        ordered = sorted(candidates, key=lambda item: item.canonical_id)
        if len(ordered) > self.budgets.max_candidates:
            raise SemanticScoringError("CANDIDATE_BUDGET_EXCEEDED")
        if len({item.canonical_id for item in ordered}) != len(ordered):
            raise SemanticScoringError("CANONICAL_ID_DUPLICATE")
        request_bytes = len(query.encode("utf-8")) + sum(
            len(item.text.encode("utf-8")) for item in ordered
        )
        if request_bytes > self.budgets.max_request_bytes:
            raise SemanticScoringError("REQUEST_BYTES_BUDGET_EXCEEDED")
        deadline = started + self.budgets.max_latency_ms / 1000
        self._enter()
        try:
            _check_cancel_deadline(deadline, cancel_event)
            return self._score(
                generation=generation,
                query=query,
                candidates=ordered,
                request_bytes=request_bytes,
                deadline=deadline,
                cancel_event=cancel_event,
                started=started,
            )
        finally:
            self._leave()

    def _score(
        self,
        *,
        generation: str,
        query: str,
        candidates: Sequence[SourceDocument],
        request_bytes: int,
        deadline: float,
        cancel_event: threading.Event | None,
        started: float,
    ) -> dict[str, Any]:
        lexical = {
            item.canonical_id: lexical_score(query, item.text) for item in candidates
        }
        semantic: dict[str, float] = {}
        reranked: dict[str, float] = {}
        refresh_receipt: dict[str, Any] | None = None
        fallback_reason = "INFERENCE_BACKEND_UNAVAILABLE"
        embed_ms = 0.0
        cache_hit = False
        if self.provider is not None and self.store is not None:
            try:
                embed_started = time.perf_counter()
                refresh_receipt = self.store.refresh(
                    generation,
                    self.provider.identity,
                    candidates,
                    self.provider,
                    self.budgets,
                    deadline=deadline,
                    cancel_event=cancel_event,
                )
                cache_hit = refresh_receipt["embedded"] == 0
                _manifest, vectors = self.store.load(generation, self.provider.identity)
                query_vector = self.provider.embed(
                    [query], deadline=deadline, cancel_event=cancel_event
                )[0]
                semantic = {
                    item.canonical_id: _cosine(query_vector, vectors[item.canonical_id])
                    for item in candidates
                }
                embed_ms = (time.perf_counter() - embed_started) * 1000
                fallback_reason = "NONE"
                self.metrics["semantic_success"] += 1
            except SemanticScoringError as error:
                fallback_reason = error.reason_code
                semantic = {}
                self.metrics["fallback"] += 1
        if self.reranker is not None and semantic:
            try:
                raw = self.reranker.rerank(
                    query,
                    candidates,
                    deadline=deadline,
                    cancel_event=cancel_event,
                )
                if set(raw) - {item.canonical_id for item in candidates}:
                    raise SemanticScoringError("RERANK_ID_UNKNOWN")
                reranked = {
                    key: _finite(value, "reranker score") for key, value in raw.items()
                }
                if any(value > 1 for value in reranked.values()):
                    raise SemanticScoringError("RERANK_SCORE_INVALID")
            except SemanticScoringError as error:
                fallback_reason = error.reason_code
                reranked = {}
                self.metrics["rerank_fallback"] += 1

        results: list[dict[str, Any]] = []
        for item in candidates:
            lexical_value = lexical[item.canonical_id]
            structural = item.structural_score
            semantic_value = semantic.get(item.canonical_id)
            rerank_value = reranked.get(item.canonical_id)
            if semantic_value is None:
                combined = 0.80 * lexical_value + 0.20 * structural
                method = "deterministic_lexical_structural"
                reason = fallback_reason
            else:
                auxiliary = (
                    0.5 * semantic_value + 0.5 * rerank_value
                    if rerank_value is not None
                    else semantic_value
                )
                combined = 0.45 * lexical_value + 0.15 * structural + 0.40 * auxiliary
                method = "runtime_semantic_auxiliary"
                reason = "NONE"
            results.append(
                {
                    "schema": SCORE_SCHEMA,
                    "canonical_id": item.canonical_id,
                    "score": round(combined, 12),
                    "confidence": round(combined, 12),
                    "reason": reason,
                    "method": method,
                    "provenance": {
                        "generation": generation,
                        "source_sha256": item.source_sha256,
                        "model_sha256": (
                            self.provider.identity.sha256
                            if semantic_value is not None and self.provider
                            else None
                        ),
                        "preprocessing_hash": (
                            self.provider.identity.preprocessing_hash
                            if semantic_value is not None and self.provider
                            else None
                        ),
                        "authority": "derived_auxiliary",
                    },
                    "components": {
                        "lexical": round(lexical_value, 12),
                        "structural": round(structural, 12),
                        "semantic": (
                            round(semantic_value, 12)
                            if semantic_value is not None
                            else None
                        ),
                        "reranker": (
                            round(rerank_value, 12)
                            if rerank_value is not None
                            else None
                        ),
                    },
                }
            )
        results.sort(key=lambda value: (-value["score"], value["canonical_id"]))
        selected: list[dict[str, Any]] = []
        selected_tokens = 0
        source_by_id = {item.canonical_id: item for item in candidates}
        for value in results:
            token_count = len(_tokens(source_by_id[value["canonical_id"]].text))
            if selected_tokens + token_count > self.budgets.max_selected_tokens:
                continue
            selected.append(value)
            selected_tokens += token_count
            if len(selected) >= self.budgets.max_selected:
                break
        top_confidence = selected[0]["confidence"] if selected else 0.0
        abstention = None
        if not selected or top_confidence < self.minimum_confidence:
            reason = (
                "NO_CANDIDATES"
                if not candidates
                else "NO_QUERY_COVERAGE"
                if not semantic and max(lexical.values(), default=0.0) == 0.0
                else "LOW_CONFIDENCE"
            )
            abstention = {
                "abstained": True,
                "reason": reason,
                "minimum_confidence": self.minimum_confidence,
                "observed_confidence": top_confidence,
            }
            selected = []
        latency_ms = (time.perf_counter() - started) * 1000
        self.metrics["requests"] += 1
        self.metrics["cache_hit" if cache_hit else "cache_miss"] += 1
        return {
            "schema": "simplicio.fast.semantic-ranking-receipt/v1",
            "generation": generation,
            "query_sha256": _sha_bytes(query.encode("utf-8")),
            "formula": {
                "version": FORMULA_VERSION,
                "lexical": 0.45 if semantic else 0.80,
                "structural": 0.15 if semantic else 0.20,
                "semantic": 0.40 if semantic else 0.0,
            },
            "model": self.provider.identity.record() if self.provider else None,
            "results": results,
            "selected": selected,
            "abstention": abstention,
            "fallback": {
                "used": not bool(semantic),
                "reason_code": fallback_reason,
            },
            "cache": {
                "hit": cache_hit,
                "refresh": refresh_receipt,
            },
            "budgets": self.budgets.record(),
            "usage": {
                "candidate_count": len(candidates),
                "selected_count": len(selected),
                "request_bytes": request_bytes,
                "selected_tokens": selected_tokens,
            },
            "metrics": {
                "embed_rerank_ms": embed_ms,
                "latency_ms": latency_ms,
                "candidates": len(candidates),
                "selected_spans": len(selected),
                "cache_hit": cache_hit,
                "fallback": not bool(semantic),
            },
            "authority": {
                "source": "snapshot_and_source_sha256",
                "semantic_score": "derived_auxiliary_only",
            },
        }


def semantic_capabilities(
    provider: EmbeddingProvider | None = None,
) -> dict[str, Any]:
    """Describe the optional lane without probing the network or downloading."""
    return {
        "schema": "simplicio.fast.semantic-capabilities/v1",
        "semantic_score_schema": SCORE_SCHEMA,
        "inference_backend": INFERENCE_BACKEND_SCHEMA,
        "runtime_first": True,
        "available": provider is not None,
        "mode": "runtime"
        if isinstance(provider, RuntimeEmbeddingProvider)
        else (
            "isolated_test" if isinstance(provider, LocalLiteRTAdapter) else "offline"
        ),
        "model": provider.identity.record() if provider else None,
        "implicit_model_download": False,
        "hard_dependency_litert": False,
        "offline_fallback": "deterministic_lexical_structural",
        "reason": "NONE" if provider else "INFERENCE_BACKEND_UNAVAILABLE",
        "parity": {
            "python": "reference_complete",
            "rust": "not_exposed",
            "reason": "RUST_SEMANTIC_SURFACE_UNAVAILABLE",
        },
    }


__all__ = [
    "ARTIFACT_SCHEMA",
    "EmbeddingProvider",
    "FORMULA_VERSION",
    "INFERENCE_BACKEND_SCHEMA",
    "InferenceBackend",
    "LocalLiteRTAdapter",
    "ModelIdentity",
    "Reranker",
    "RuntimeEmbeddingProvider",
    "SCORE_SCHEMA",
    "SemanticBudgets",
    "SemanticScorer",
    "SemanticScoringError",
    "SourceDocument",
    "DerivedVectorStore",
    "lexical_score",
    "semantic_capabilities",
]
