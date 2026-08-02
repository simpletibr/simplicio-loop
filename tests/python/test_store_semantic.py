"""Contract and state-machine tests for the canonical semantic store (#476)."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from simplicio_mapper.contract import validate_instance
from simplicio_mapper.store import SemanticStore, SemanticStoreError


def _schema(name: str) -> dict:
    root = Path(__file__).parents[2] / "contracts/mapper-store/v1/schemas"
    return json.loads((root / name).read_text(encoding="utf-8"))


def test_initialize_is_honest_about_optional_vector_capability(tmp_path: Path) -> None:
    store = SemanticStore(tmp_path / "semantic.sqlite")
    payload = store.initialize()
    assert payload["schema"] == "simplicio.mapper-store.semantic-api/v1"
    assert payload["capabilities"]["ann_claimed"] is False
    assert payload["capabilities"]["vector_backend"] == "brute-force"
    assert validate_instance(store.verify(), _schema("semantic-status.schema.json")) == []
    assert store.verify()["valid"] is True


def test_upsert_is_idempotent_and_preserves_provenance(tmp_path: Path) -> None:
    store = SemanticStore(tmp_path / "semantic.sqlite")
    first = store.upsert(
        "item-1",
        "A document with provenance.",
        kind="document",
        source="runtime",
        provenance={"path": "a.md", "source_sha256": "abc"},
        embedding=[1.0, 0.0],
        model="test-model",
    )
    second = store.upsert(
        "item-1", "A document with provenance.", source="runtime", embedding=[1.0, 0.0], model="test-model"
    )
    assert first["status"] == "inserted"
    assert second["status"] == "unchanged"
    assert store.recall("provenance", mode="fts")["results"][0]["stable_id"] == "item-1"
    with sqlite3.connect(tmp_path / "semantic.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM semantic_items").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM semantic_revisions").fetchone()[0] == 0


def test_same_content_reconciles_lineage_chunks_and_embedding(tmp_path: Path) -> None:
    database = tmp_path / "semantic.sqlite"
    store = SemanticStore(database)
    store.upsert(
        "item",
        "same content",
        source="old",
        provenance={"revision": "one"},
        metadata={"owner": "old"},
        embedding=[1.0, 0.0],
        model="model",
    )
    result = store.upsert(
        "item",
        "same content",
        source="new",
        provenance={"revision": "two"},
        metadata={"owner": "new"},
        chunks=[{"chunk_id": "item:0", "content": "same content", "provenance": {"part": 2}}],
        embedding=[0.0, 1.0],
        model="model",
    )
    assert result["status"] == "updated"
    with sqlite3.connect(database) as connection:
        item = connection.execute(
            "SELECT source, provenance_json, metadata_json FROM semantic_items WHERE stable_id='item'"
        ).fetchone()
        vector = connection.execute(
            "SELECT vector_json FROM semantic_embeddings WHERE stable_id='item' AND model='model'"
        ).fetchone()
    assert item == ("new", '{"revision":"two"}', '{"owner":"new"}')
    assert json.loads(vector[0]) == [0.0, 1.0]


def test_redaction_is_fail_closed_across_payloads_and_tombstones(tmp_path: Path) -> None:
    database = tmp_path / "semantic.sqlite"
    store = SemanticStore(database)
    with pytest.raises(SemanticStoreError, match="REDACTION_REQUIRED"):
        store.upsert("unsafe", "secret", redact=False)
    store.upsert(
        "secret",
        "password=abc123 Bearer abc.def.ghi",
        provenance={"client_secret": "value", "note": "token=value"},
        metadata={"api_key": "another"},
    )
    store.tombstone("secret", reason="password=delete-me", provenance={"token": "gone"})
    with sqlite3.connect(database) as connection:
        values = connection.execute(
            "SELECT content, provenance_json, metadata_json FROM semantic_items WHERE stable_id='secret'"
        ).fetchone()
        tombstone = connection.execute(
            "SELECT reason, provenance_json FROM semantic_tombstones WHERE stable_id='secret'"
        ).fetchone()
    assert all("abc123" not in value and "another" not in value and "value" not in value for value in values)
    assert all("delete-me" not in value and "gone" not in value for value in tombstone)


def test_changed_content_revises_by_stable_id_and_rebuilds_fts(tmp_path: Path) -> None:
    store = SemanticStore(tmp_path / "semantic.sqlite")
    store.upsert("item", "old text", source="dev")
    store.upsert("item", "new unicode acentuação", source="dev")
    assert store.recall("old", mode="fts")["results"] == []
    assert store.recall("acentuação", mode="fts")["results"][0]["stable_id"] == "item"
    assert store.rebuild()["status"] == "rebuilt"
    assert store.verify()["valid"] is True
    with sqlite3.connect(tmp_path / "semantic.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM semantic_revisions").fetchone()[0] == 1


def test_embedding_model_and_dimension_compatibility_fail_before_insert(tmp_path: Path) -> None:
    store = SemanticStore(tmp_path / "semantic.sqlite")
    store.upsert("one", "one", embedding=[1.0, 0.0], model="model-a")
    with pytest.raises(SemanticStoreError, match="EMBEDDING_DIMENSION_MISMATCH"):
        store.upsert("two", "two", embedding=[1.0], model="model-a")
    with pytest.raises(SemanticStoreError, match="EMBEDDING_MODEL_MISMATCH"):
        store.upsert("three", "three", embedding=[1.0, 0.0], model="model-b")
    with sqlite3.connect(tmp_path / "semantic.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM semantic_items").fetchone()[0] == 1


def test_hybrid_returns_separate_scores_and_stable_tie_break(tmp_path: Path) -> None:
    store = SemanticStore(tmp_path / "semantic.sqlite")
    store.upsert("b", "same words", source="fixture", embedding=[1.0, 0.0], model="model")
    store.upsert("a", "same words", source="fixture", embedding=[1.0, 0.0], model="model")
    response = store.recall("same", mode="hybrid", query_embedding=[1.0, 0.0], model="model", dimensions=2)
    assert [row["stable_id"] for row in response["results"]] == ["a", "b"]
    assert all({"fts_score", "vector_score", "hybrid_score"} <= row.keys() for row in response["results"])
    assert response["method"] == "hybrid"
    assert response["ann_claimed"] is False
    assert validate_instance(response, _schema("semantic-recall.schema.json")) == []


def test_tombstone_removes_recall_but_keeps_audit_and_allows_revival(tmp_path: Path) -> None:
    store = SemanticStore(tmp_path / "semantic.sqlite")
    store.upsert("gone", "sensitive secret", source="runtime", provenance={"job": "x"})
    assert store.delete("gone")["status"] == "tombstoned"
    assert store.recall("sensitive", mode="fts")["results"] == []
    assert store.verify()["tombstones"] == 1
    assert store.upsert("gone", "new content", source="runtime")["status"] == "revived"
    assert store.recall("new", mode="fts")["results"][0]["stable_id"] == "gone"


def test_relations_require_live_endpoints_and_are_idempotent(tmp_path: Path) -> None:
    store = SemanticStore(tmp_path / "semantic.sqlite")
    store.upsert("left", "left", source="mapper")
    store.upsert("right", "right", source="mapper")
    first = store.upsert_relation("left", "right", "supports", provenance={"source": "mapper"})
    second = store.upsert_relation("left", "right", "supports", provenance={"source": "mapper"})
    assert first["relation_id"] == second["relation_id"]
    store.delete("right")
    with pytest.raises(SemanticStoreError, match="RELATION_ENDPOINT_MISSING"):
        store.upsert_relation("left", "right", "supports")


def test_tombstone_removes_relations_and_embeddings(tmp_path: Path) -> None:
    database = tmp_path / "semantic.sqlite"
    store = SemanticStore(database)
    store.upsert("left", "left", embedding=[1.0, 0.0], model="model")
    store.upsert("right", "right", embedding=[0.0, 1.0], model="model")
    store.upsert_relation("left", "right", "supports")
    store.tombstone("right")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM semantic_relations").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM semantic_embeddings WHERE stable_id='right'").fetchone()[
                0
            ]
            == 0
        )


def test_malformed_fts_query_and_content_redaction_are_explicit(tmp_path: Path) -> None:
    store = SemanticStore(tmp_path / "semantic.sqlite", max_content_chars=20)
    result = store.upsert("secret", "api_key=abc123", source="test")
    assert result["content_hash"] != ""
    with sqlite3.connect(tmp_path / "semantic.sqlite") as connection:
        assert "[REDACTED]" in connection.execute("SELECT content FROM semantic_items").fetchone()[0]
    with pytest.raises(SemanticStoreError, match="CONTENT_LIMIT"):
        store.upsert("large", "x" * 21, source="test")
    with pytest.raises(SemanticStoreError, match="QUERY_INVALID"):
        store.recall('"unterminated', mode="fts")


def test_schema_contract_fixture_and_missing_store_are_supported(tmp_path: Path) -> None:
    fixture = json.loads(
        (Path(__file__).parents[2] / "contracts/mapper-store/v1/fixtures/semantic/golden.json").read_text()
    )
    store = SemanticStore(tmp_path / "semantic.sqlite")
    upsert_fixture = {key: value for key, value in fixture.items() if key != "content_hash"}
    response = store.upsert(**upsert_fixture)
    assert response["stable_id"] == fixture["stable_id"]
    assert (
        validate_instance(
            {
                **fixture,
                "tombstone": False,
            },
            _schema("semantic-item.schema.json"),
        )
        == []
    )
    assert fixture["content_hash"] == response["content_hash"]
    with pytest.raises(SemanticStoreError, match="STORE_NOT_INITIALIZED"):
        SemanticStore(tmp_path / "missing.sqlite", auto_create=False).upsert("x", "x")


def test_validation_errors_are_typed(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SemanticStore(tmp_path / "bad.sqlite", max_content_chars=0)
    store = SemanticStore(tmp_path / "semantic.sqlite")
    with pytest.raises(SemanticStoreError, match="IDENTITY_INVALID"):
        store.upsert("", "x")
    with pytest.raises(SemanticStoreError, match="PROVENANCE_INVALID"):
        store.upsert("bad", "x", provenance={"bad": {1, 2}})
    with pytest.raises(SemanticStoreError, match="EMBEDDING_INVALID"):
        store.upsert("nan", "x", embedding=[math.nan], model="m")
    with pytest.raises(SemanticStoreError, match="EMBEDDING_DIMENSION_MISMATCH"):
        store.upsert("dim", "x", embedding=[1.0, 0.0], model="m", dimensions=1)
    with pytest.raises(SemanticStoreError, match="EMBEDDING_INVALID"):
        store.upsert("missing-vector", "x", model="m")
    with pytest.raises(SemanticStoreError, match="EMBEDDING_LIMIT"):
        store.upsert("empty-vector", "x", embedding=[], model="m")
    with pytest.raises(SemanticStoreError, match="CHUNK_INVALID"):
        store.upsert("bad-chunk", "x", chunks=["not-a-mapping"])
    with pytest.raises(SemanticStoreError, match="PROVENANCE_LIMIT"):
        store.upsert("large-provenance", "x", provenance={"payload": "x" * 200_001})
    with pytest.raises(SemanticStoreError, match="IDENTITY_INVALID"):
        store.upsert(1, "x")
    with pytest.raises(SemanticStoreError, match="TOMBSTONE_INVALID"):
        store.tombstone("missing", reason="")


def test_capabilities_and_read_only_initialization_are_typed(tmp_path: Path) -> None:
    store = SemanticStore(tmp_path / "semantic.sqlite")
    store.initialize()
    assert store.capabilities()["schema"] == "simplicio.mapper-store.semantic-api/v1"
    with pytest.raises(SemanticStoreError, match="STORE_READ_ONLY"):
        SemanticStore(tmp_path / "other.sqlite", auto_create=False).initialize()


def test_vector_recall_uses_deterministic_query_and_reports_results(tmp_path: Path) -> None:
    store = SemanticStore(tmp_path / "semantic.sqlite")
    store.upsert("vector", "semantic words", source="vector", embedding=[1.0, 0.0], model="model")
    response = store.recall("semantic words", mode="vector")
    assert response["method"] == "brute-force"
    assert response["results"][0]["stable_id"] == "vector"
    assert response["results"][0]["source"] == "vector"
    with pytest.raises(SemanticStoreError, match="EMBEDDING_DIMENSION_MISMATCH"):
        store.recall("x", mode="vector", query_embedding=[1.0], dimensions=2)
    with pytest.raises(SemanticStoreError, match="EMBEDDING_MODEL_MISMATCH"):
        store.recall("x", mode="vector", query_embedding=[1.0, 0.0], model="other")
    with pytest.raises(SemanticStoreError, match="MODE_INVALID"):
        store.recall("x", mode="bad")
    with pytest.raises(SemanticStoreError, match="LIMIT_INVALID"):
        store.recall("x", limit=0)


def test_empty_chunks_default_and_missing_delete_are_safe(tmp_path: Path) -> None:
    store = SemanticStore(tmp_path / "semantic.sqlite")
    store.upsert("empty", "text", chunks=[])
    with pytest.raises(SemanticStoreError, match="ITEM_NOT_FOUND"):
        store.delete("missing")
    with pytest.raises(SemanticStoreError, match="RELATION_INVALID"):
        store.upsert_relation("", "b", "kind")


def test_limits_reject_unbounded_chunks_and_queries(tmp_path: Path) -> None:
    store = SemanticStore(tmp_path / "semantic.sqlite")
    with pytest.raises(SemanticStoreError, match="CHUNK_LIMIT"):
        store.upsert("many", "x", chunks=({"content": "x"} for _ in range(4097)))
    with pytest.raises(SemanticStoreError, match="QUERY_LIMIT"):
        store.recall("x" * 20_001)


def test_rebuild_and_verify_detect_index_corruption(tmp_path: Path) -> None:
    database = tmp_path / "semantic.sqlite"
    store = SemanticStore(database)
    store.upsert("item", "rebuild me")
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM semantic_fts")
    assert store.verify()["valid"] is False
    assert store.rebuild()["fts_rows"] == 1
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO semantic_fts(stable_id, chunk_id, content) VALUES ('orphan', 'orphan', 'orphan')"
        )
    report = store.verify()
    assert report["valid"] is False
    assert report["orphan_fts"] == 1


def test_missing_fts_capability_is_reported_without_false_ann(tmp_path: Path) -> None:
    capabilities = {
        "fts5": False,
        "sqlite_vec": False,
        "vector_backend": "brute-force",
        "ann_claimed": False,
        "fallback_reason": "SQLITE_VEC_UNAVAILABLE",
    }
    store = SemanticStore(tmp_path / "no-fts.sqlite")
    with patch.object(SemanticStore, "_capabilities", return_value=capabilities):
        store.initialize()
        assert store.verify()["valid"] is True
        with pytest.raises(SemanticStoreError, match="FTS5_UNAVAILABLE"):
            store.rebuild()
