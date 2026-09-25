from __future__ import annotations

import pytest

from simplicio_fast.litert_embeddings import LiteRTEmbeddingError, embed, rerank
from simplicio_fast.semantic_scoring import INFERENCE_BACKEND_SCHEMA, ModelIdentity


class Backend:
    def capabilities(self):
        return {
            "schema": INFERENCE_BACKEND_SCHEMA,
            "operations": ["embeddings"],
        }

    def infer(self, request, *, deadline, cancel_event):
        return {
            "schema": "simplicio.inference-result/v1",
            "model_sha256": request["model"]["sha256"],
            "vectors": [[float(len(text)), 1.0] for text in request["inputs"]],
        }


def model():
    return ModelIdentity(
        model="fixture",
        version="1",
        sha256="1" * 64,
        preprocessing="fixture-v1",
        dimension=2,
        max_tokens=128,
        license="test-only",
    )


def test_runtime_embed_and_deep_offline_rerank():
    a = embed("UserService authenticate token", backend=Backend(), model=model())
    b = embed("UserService authenticate token", backend=Backend(), model=model())
    assert a == b
    assert a["backend"] == "simplicio-runtime"
    assert a["reason_code"] == "NONE"
    ranked = rerank(
        "authenticate token",
        [("a", "UserService authenticate token"), ("b", "filesystem path helper")],
        top_k=2,
    )
    assert ranked[0]["id"] == "a"
    assert all(row["reason_code"] for row in ranked)


def test_direct_or_missing_litert_mode_fails_closed():
    with pytest.raises(LiteRTEmbeddingError) as raised:
        embed("x", enable_litert=True)
    assert raised.value.reason_code == "INFERENCE_BACKEND_REQUIRED"


def test_model_identity_and_dimension_cannot_be_omitted_or_overridden():
    with pytest.raises(LiteRTEmbeddingError) as raised:
        embed("x", backend=Backend())
    assert raised.value.reason_code == "INFERENCE_MODEL_IDENTITY_REQUIRED"
    with pytest.raises(LiteRTEmbeddingError) as raised:
        embed("x", backend=Backend(), model=model(), dims=3)
    assert raised.value.reason_code == "INFERENCE_DIMENSION_MISMATCH"
