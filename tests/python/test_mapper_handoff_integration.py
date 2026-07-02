"""mapper 0.13 integration: `inspect` evidence in artifact_status, `handoff`
context-pack in build_mapper_context — always fail-open to the artifact-file
path so projects without the binary (or with SIMPLICIO_MAPPER_CLI=0) behave
exactly as before."""
import json

import pytest

from simplicio import mapper


@pytest.fixture(autouse=True)
def _clear_cli_cache():
    mapper._MAPPER_CLI_CACHE.clear()
    yield
    mapper._MAPPER_CLI_CACHE.clear()


def _write_project_map(tmp_path):
    art_dir = tmp_path / ".simplicio"
    art_dir.mkdir()
    (art_dir / "project-map.json").write_text(json.dumps({
        "schema": "simplicio.project-map/v2",
        "generated_at": "2026-07-02T00:00:00Z",
        "entry_points": ["src/app.py"],
        "files": [{"path": "src/app.py", "language": "python", "importance": 3}],
    }), encoding="utf-8")


def test_run_mapper_json_disabled_by_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_MAPPER_CLI", "0")
    assert mapper.run_mapper_json(tmp_path, "inspect") is None


def test_run_mapper_json_missing_binary_is_none(monkeypatch, tmp_path):
    monkeypatch.delenv("SIMPLICIO_MAPPER_CLI", raising=False)
    monkeypatch.setattr(mapper.shutil, "which", lambda _name: None)
    assert mapper.run_mapper_json(tmp_path, "inspect") is None


def test_artifact_status_embeds_inspection_evidence(monkeypatch, tmp_path):
    _write_project_map(tmp_path)
    monkeypatch.setattr(mapper, "map_inspection", lambda _root: {
        "schema": "simplicio.map-inspection/v1",
        "evidence": {"artifacts": {"project_map": {"exists": True, "size_bytes": 321}}},
        "warnings": ["deep pass stale"],
    })
    payload = mapper.artifact_status(tmp_path)
    assert payload["project_map"]["present"] is True
    assert payload["inspection"]["schema"] == "simplicio.map-inspection/v1"
    assert payload["inspection"]["evidence"]["project_map"]["exists"] is True
    assert payload["inspection"]["warnings"] == ["deep pass stale"]


def test_artifact_status_without_mapper_cli_keeps_legacy_shape(monkeypatch, tmp_path):
    _write_project_map(tmp_path)
    monkeypatch.setattr(mapper, "map_inspection", lambda _root: None)
    payload = mapper.artifact_status(tmp_path)
    assert "inspection" not in payload
    assert payload["project_map"]["present"] is True


def test_build_mapper_context_prefers_handoff_pack(monkeypatch, tmp_path):
    _write_project_map(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("import os\n", encoding="utf-8")
    monkeypatch.setattr(mapper, "map_handoff", lambda _root: {
        "schema": "simplicio.map-handoff/v1",
        "context_pack": {
            "pack_hash": "abc123",
            "needs_broader_context": False,
            "dependencies": {"runtime": ["orjson"]},
            "files": [{
                "path": "src/app.py", "language": "python",
                "symbols": [{"name": "main", "kind": "function"}],
                "imports": ["os"],
            }],
            "recent_changes": [{"path": "src/app.py", "status": "modified"}],
        },
    })
    context = mapper.build_mapper_context(tmp_path, "src/app.py")
    assert "simplicio.map-handoff/v1" in context
    assert "Pack hash: abc123" in context
    assert "symbols=main" in context
    assert "Target fallback:" in context


def test_build_mapper_context_falls_back_when_pack_insufficient(monkeypatch, tmp_path):
    _write_project_map(tmp_path)
    monkeypatch.setattr(mapper, "map_handoff", lambda _root: {
        "context_pack": {"needs_broader_context": True, "files": [{"path": "x"}]},
    })
    context = mapper.build_mapper_context(tmp_path, "src/app.py")
    assert "Mapper artifact:" in context
    assert "map-handoff" not in context


def test_build_mapper_context_falls_back_without_handoff(monkeypatch, tmp_path):
    _write_project_map(tmp_path)
    monkeypatch.setattr(mapper, "map_handoff", lambda _root: None)
    context = mapper.build_mapper_context(tmp_path, "src/app.py")
    assert "Mapper artifact:" in context


def test_map_ask_returns_results_list(monkeypatch, tmp_path):
    monkeypatch.setattr(mapper, "run_mapper_json", lambda root, sub, *, extra=(), timeout=30: {
        "schema": "simplicio.ask/v1",
        "query": {"verb": extra[0], "arg": extra[1] if len(extra) > 1 else None},
        "results": [{"path": "src/app.py", "symbol": "main"}, "not-a-dict"],
        "total": 1,
    })
    results = mapper.map_ask(tmp_path, "impact", "src/app.py")
    assert results == [{"path": "src/app.py", "symbol": "main"}]


def test_map_ask_rejects_unknown_verb(tmp_path):
    assert mapper.map_ask(tmp_path, "delete-everything", "x") is None


def test_map_ask_none_when_cli_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(mapper, "run_mapper_json", lambda *a, **k: None)
    assert mapper.map_ask(tmp_path, "impact", "src/app.py") is None


def test_inspect_target_embeds_impact_and_affected_tests(monkeypatch, tmp_path):
    _write_project_map(tmp_path)
    monkeypatch.setattr(mapper, "map_inspection", lambda _root: None)
    monkeypatch.setattr(mapper, "map_handoff", lambda _root: None)

    def fake_ask(root, verb, arg=""):
        if verb == "impact":
            return [{"path": "src/api.py", "kind": "dependent"}]
        if verb == "tests-for":
            return [{"path": "tests/test_app.py"}]
        return None

    monkeypatch.setattr(mapper, "map_ask", fake_ask)
    payload = mapper.inspect_target(tmp_path, "src/app.py")
    assert payload["impact"] == [{"path": "src/api.py", "kind": "dependent"}]
    assert payload["affected_tests"] == [{"path": "tests/test_app.py"}]


def test_inspect_target_omits_ask_keys_when_unavailable(monkeypatch, tmp_path):
    _write_project_map(tmp_path)
    monkeypatch.setattr(mapper, "map_inspection", lambda _root: None)
    monkeypatch.setattr(mapper, "map_handoff", lambda _root: None)
    monkeypatch.setattr(mapper, "map_ask", lambda *a, **k: None)
    payload = mapper.inspect_target(tmp_path, "src/app.py")
    assert "impact" not in payload
    assert "affected_tests" not in payload
