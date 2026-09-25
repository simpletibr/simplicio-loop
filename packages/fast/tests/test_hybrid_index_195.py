from simplicio_fast.hybrid_index import HybridIndex, IndexError, parity

DOCS = {"a": "alpha beta", "b": "beta", "c": "gamma"}
V = {"a": [1.0, 0.0], "b": [0.8, 0.2], "c": [0.0, 1.0]}


def test_fallback_explicit():
    assert HybridIndex(DOCS).search("alpha")[0]["method"] == "lexical"


def test_hybrid_rerank_preserves_relevance():
    assert HybridIndex(DOCS, V).search("alpha", [1.0, 0.0])[0]["id"] == "a"


def test_stale_rejected():
    try:
        HybridIndex(DOCS, V).search("x", [1.0, 0.0], index_version="old")
        assert False
    except IndexError:
        pass


def test_python_deterministic_and_rust_null():
    x = HybridIndex(DOCS, V)
    assert x.search("beta", [1.0, 0.0]) == x.search("beta", [1.0, 0.0])
    assert parity([])["null_reason"] == "RUST_UNAVAILABLE"
