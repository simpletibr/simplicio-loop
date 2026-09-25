"""Strict compatibility facade for Runtime-owned semantic inference (#186).

No LiteRT package is imported, downloaded or invoked here.  Neural embeddings
must enter through ``RuntimeEmbeddingProvider`` and all ranking delegates to the
canonical semantic scorer.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Sequence

from .semantic_scoring import (
    DerivedVectorStore,
    EmbeddingProvider,
    InferenceBackend,
    ModelIdentity,
    RuntimeEmbeddingProvider,
    SemanticBudgets,
    SemanticScorer,
    SemanticScoringError,
    SourceDocument,
)

SCHEMA = "simplicio.fast.litert-embeddings/v2"
LiteRTEmbeddingError = SemanticScoringError


def _runtime_provider(
    *,
    provider: EmbeddingProvider | None,
    backend: InferenceBackend | None,
    model: ModelIdentity | None,
) -> RuntimeEmbeddingProvider:
    if provider is not None and backend is not None:
        raise SemanticScoringError("INFERENCE_PROVIDER_CONFLICT")
    candidate: EmbeddingProvider | None = provider
    if candidate is None and backend is not None:
        if model is None:
            raise SemanticScoringError("INFERENCE_MODEL_IDENTITY_REQUIRED")
        candidate = RuntimeEmbeddingProvider(backend, model)
    if candidate is None:
        raise SemanticScoringError("INFERENCE_BACKEND_REQUIRED")
    if not isinstance(candidate, RuntimeEmbeddingProvider):
        raise SemanticScoringError("DIRECT_LITERT_FORBIDDEN")
    return candidate


def deterministic_embed(text: str, *, dims: int = 32) -> list[float]:
    """Compatibility tombstone for the removed synthetic-vector algorithm."""
    del text, dims
    raise SemanticScoringError(
        "DETERMINISTIC_EMBEDDING_REMOVED",
        "use RuntimeEmbeddingProvider or deterministic lexical reranking",
    )


def embed(
    text: str,
    *,
    enable_litert: bool = False,
    dims: int | None = None,
    provider: EmbeddingProvider | None = None,
    backend: InferenceBackend | None = None,
    model: ModelIdentity | None = None,
    timeout_s: float = 2.0,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Return one Runtime-verified embedding; never synthesize a fallback."""
    del enable_litert  # retained solely for call-signature compatibility
    if not isinstance(text, str):
        raise SemanticScoringError("INFERENCE_INPUT_INVALID")
    if timeout_s <= 0:
        raise SemanticScoringError("INFERENCE_DEADLINE_EXCEEDED")
    runtime = _runtime_provider(provider=provider, backend=backend, model=model)
    if dims is not None and dims != runtime.identity.dimension:
        raise SemanticScoringError("INFERENCE_DIMENSION_MISMATCH")
    vector = runtime.embed(
        [text],
        deadline=time.monotonic() + timeout_s,
        cancel_event=cancel_event,
    )[0]
    return {
        "schema": SCHEMA,
        "backend": "simplicio-runtime",
        "dims": runtime.identity.dimension,
        "vector": list(vector),
        "model": runtime.identity.record(),
        "fact": False,
        "inferred": True,
        "fallback": False,
        "reason_code": "NONE",
    }


def rerank(
    query: str,
    documents: Sequence[tuple[str, str]],
    *,
    top_k: int = 5,
    provider: EmbeddingProvider | None = None,
    store: DerivedVectorStore | None = None,
    generation: str = "compatibility-generation",
) -> list[dict[str, Any]]:
    """Delegate ranking to ``SemanticScorer`` with stable reason codes."""
    if not isinstance(top_k, int) or top_k < 1:
        raise SemanticScoringError("RERANK_TOP_K_INVALID")
    if provider is not None:
        provider = _runtime_provider(provider=provider, backend=None, model=None)
        if store is None:
            raise SemanticScoringError("VECTOR_STORE_REQUIRED")
    try:
        sources = tuple(
            SourceDocument.create(str(document_id), text)
            for document_id, text in documents
        )
    except (TypeError, ValueError) as error:
        raise SemanticScoringError("RERANK_INPUT_INVALID", str(error)) from error
    budgets = SemanticBudgets(
        max_candidates=max(1, len(sources)),
        max_selected=max(1, min(top_k, max(1, len(sources)))),
    )
    receipt = SemanticScorer(
        provider=provider,
        store=store,
        budgets=budgets,
        minimum_confidence=0.0,
    ).score(generation=generation, query=query, candidates=sources)
    return [
        {
            "id": row["canonical_id"],
            "score": row["score"],
            "method": row["method"],
            "reason_code": row["reason"],
            "source_sha256": row["provenance"]["source_sha256"],
        }
        for row in receipt["results"][:top_k]
    ]


__all__ = [
    "SCHEMA",
    "LiteRTEmbeddingError",
    "deterministic_embed",
    "embed",
    "rerank",
]
