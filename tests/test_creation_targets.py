from simplicio_mapper.context_pack import build_context_pack
from simplicio_mapper.retrieval_index import select_context_targets


def _retrieval_index():
    return {
        "schema": "simplicio.retrieval-index/v1",
        "documents": [],
        "document_count": 0,
        "document_frequency": {},
        "related_tests": {},
        "related_test_evidence": {},
        "call_graph": {"callees": {}, "callers": {}, "relations": []},
    }


def test_explicit_missing_target_is_reserved_for_creation(tmp_path):
    selection = select_context_targets(
        str(tmp_path),
        {"files": []},
        target="site/index.html",
        retrieval_index=_retrieval_index(),
    )

    assert selection["target_resolution"]["status"] == "reserved"
    assert selection["needs_broader_context"] is False
    assert selection["targets"][0]["path"] == "site/index.html"
    assert selection["targets"][0]["creation_target"] is True


def test_context_pack_emits_canonical_placeholder_for_creation_target(tmp_path):
    pack = build_context_pack(
        str(tmp_path),
        [{"path": "site/index.html", "ranges": [], "creation_target": True}],
        project_map={"files": [], "dependencies": {}},
        symbol_index={"symbols": []},
        call_graph={"edges": []},
        architecture_inventory={"layers": []},
    )

    assert pack["needs_broader_context"] is False
    assert pack["fidelity"]["gate"] == "ready"
    assert pack["files"][0]["path"] == "site/index.html"
    assert pack["files"][0]["snapshot_hash"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert pack["files"][0]["creation_target"] is True
