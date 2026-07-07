"""#100 — consuming REAL (schema-faithful) project-map.json /
precedent-index.json artifacts, standalone (no simplicio-mapper binary, no
network): the file-based fallback path every downstream consumer falls back
to when the mapper CLI isn't on PATH.
"""

from __future__ import annotations

from simplicio import mapper

from ._schema import assert_has_keys, assert_schema_id


def test_artifact_status_loads_real_fixture_project_map(sample_project):
    payload = mapper.artifact_status(sample_project)

    assert_schema_id(payload["project_map"], "simplicio.project-map/v1", where="artifact_status.project_map")
    assert payload["project_map"]["present"] is True
    assert payload["project_map"]["entry_points"] == ["src/app.py"]
    assert payload["project_map"]["module_names"] == ["src"]


def test_artifact_status_loads_real_fixture_precedent_index(sample_project):
    payload = mapper.artifact_status(sample_project)

    assert_schema_id(
        payload["precedent_index"],
        "simplicio.precedent-index/v1",
        where="artifact_status.precedent_index",
    )
    assert payload["precedent_index"]["present"] is True
    assert payload["precedent_index"]["items"] == 1


def test_build_mapper_context_surfaces_real_precedent_snippet(sample_project):
    context = mapper.build_mapper_context(str(sample_project), "src/app.py")

    # Fallback (no mapper CLI, no map-handoff pack) renders from the raw
    # artifacts directly — the real precedent summary/tags from the fixture
    # must reach the prompt context the task pipeline hands to the model.
    assert "src/app.py" in context
    assert "greet() returns a formatted hello string" in context


def test_inspect_target_contract_over_real_fixture(sample_project):
    payload = {
        "schema": "simplicio.dev-cli.inspect/v1",
        **mapper.inspect_target(str(sample_project), "src/app.py", goal="add a farewell helper"),
    }

    assert_schema_id(payload, "simplicio.dev-cli.inspect/v1", where="inspect_target")
    assert_has_keys(payload, {"context"}, where="inspect_target")
    assert "src/app.py" in payload["context"]
