"""Regression tests for issue #243.

On a fresh repo, with the default config (SIMPLICIO_ENABLE_EMBED_INDEX unset,
no precedent-index.json, no native precedent binary), build_precedent_block()
used to crash with a raw KeyError from EmbeddingCache.lookup(): index_repo()
never populates the cache when embedding indexing is disabled, but the
similarity-scoring branch called cache.lookup() unconditionally whenever
rank_precedents() came back empty (which it always does on a fresh repo).
"""

import os

import pytest

from simplicio.cache import EmbeddingCache, EmbeddingCacheMissError
from simplicio.precedent import build_precedent_block


@pytest.fixture(autouse=True)
def no_embed_index_env(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_ENABLE_EMBED_INDEX", raising=False)


def _write_python_file(root):
    (root / "app.py").write_text(
        "def hello():\n    return 'hi'\n",
        encoding="utf-8",
    )


def test_build_precedent_block_fresh_repo_no_embed_index(tmp_path):
    """Fresh repo, embedding indexing off by default: must not crash."""
    _write_python_file(tmp_path)

    block = build_precedent_block(str(tmp_path), "python", "add a greeting")

    assert "[PRECEDENT]" in block
    assert "no match for" in block


def test_build_precedent_block_fresh_repo_embed_index_explicitly_off(tmp_path, monkeypatch):
    _write_python_file(tmp_path)
    monkeypatch.setenv("SIMPLICIO_ENABLE_EMBED_INDEX", "0")

    block = build_precedent_block(str(tmp_path), "python", "add a greeting")

    assert "[PRECEDENT]" in block
    assert "no match for" in block


def test_build_precedent_block_unknown_stack_still_falls_back(tmp_path):
    _write_python_file(tmp_path)

    block = build_precedent_block(str(tmp_path), "some-unknown-stack", "add a greeting")

    assert "[PRECEDENT]" in block
    assert "no scanner" in block


def test_embedding_cache_lookup_raises_clear_error_on_miss(tmp_path):
    """Defensive guard: EmbeddingCache.lookup() must never raise a raw
    KeyError on an unindexed text; it should raise a clear, actionable
    EmbeddingCacheMissError instead."""
    cache = EmbeddingCache(str(tmp_path))

    with pytest.raises(EmbeddingCacheMissError) as excinfo:
        cache.lookup(["some code block never embedded"])

    assert "not in the" in str(excinfo.value) or "embedding cache" in str(excinfo.value)


def test_embedding_cache_lookup_succeeds_when_all_texts_cached(tmp_path):
    cache = EmbeddingCache(str(tmp_path))
    texts = ["block a", "block b"]
    vectors = [[0.1, 0.2], [0.3, 0.4]]

    cache.add(texts, vectors)

    result = cache.lookup(texts)
    assert result.shape == (2, 2)


def test_embedding_cache_lookup_raises_on_partial_miss(tmp_path):
    cache = EmbeddingCache(str(tmp_path))
    cache.add(["known block"], [[0.1, 0.2]])

    with pytest.raises(EmbeddingCacheMissError):
        cache.lookup(["known block", "unknown block"])


def test_index_repo_skips_embedding_when_disabled(tmp_path):
    """index_repo() must not populate the cache when embedding indexing is
    disabled -- this is the precondition that made the original bug possible
    (index_repo() returning normally while the cache stayed empty)."""
    from simplicio.precedent import index_repo

    _write_python_file(tmp_path)
    cache, cands = index_repo(str(tmp_path), "python", verbose=False)

    assert cands  # grep found candidates via the python patterns
    assert cache.stats()["cached_blocks"] == 0

    os.environ.pop("SIMPLICIO_ENABLE_EMBED_INDEX", None)
