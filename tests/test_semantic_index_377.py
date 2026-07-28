from __future__ import annotations

import pytest

from simplicio_mapper.semantic_index import (
    SEMANTIC_SCHEMA,
    SemanticIndexError,
    build_semantic_index,
    validate_semantic_index,
)


def test_deterministic_optional_index():
    items = [
        {"id": "a", "text": "UserService authenticate token"},
        {"id": "b", "text": "authenticate user token service"},
        {"id": "c", "text": "unrelated filesystem path"},
    ]
    first = build_semantic_index(items)
    second = build_semantic_index(items)
    assert first == second
    assert first["schema"] == SEMANTIC_SCHEMA
    assert first["policy"]["creates_factual_edges"] is False
    assert first["policy"]["optional"] is True
    assert validate_semantic_index(first)["index_digest"] == first["index_digest"]
    assert any(row["source_id"] == "a" for row in first["related_suggestions"])


def test_ml_mode_fail_closed_without_backend():
    with pytest.raises(SemanticIndexError, match="ml_backend_unavailable"):
        build_semantic_index([{"id": "a", "text": "x"}], enable_ml=True)
