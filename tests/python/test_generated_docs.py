"""#101 — docs/PYTHON_PACKAGE_INTERDEPENDENCE.md is generated from
pyproject.toml, not hand-maintained, and this test is the CI-enforced drift
gate (mirrors `python3 scripts/gen_package_interdependence.py --check`,
which is also runnable standalone / as a pre-commit hook)."""

from __future__ import annotations

from scripts.gen_package_interdependence import (
    DOC_PATH,
    _load_project,
    _local_default_model,
    main,
    render,
)


def test_doc_on_disk_matches_generated_output():
    project = _load_project()
    generated = render(project, _local_default_model())
    on_disk = DOC_PATH.read_text(encoding="utf-8")

    assert on_disk == generated, (
        "docs/PYTHON_PACKAGE_INTERDEPENDENCE.md has drifted from pyproject.toml. "
        "Regenerate it: python3 scripts/gen_package_interdependence.py"
    )


def test_check_mode_exits_zero_when_doc_is_current():
    assert main(["--check"]) == 0


def test_doc_shows_the_real_current_version_and_no_stale_versions():
    project = _load_project()
    generated = render(project, _local_default_model())

    assert f"v{project['version']}" in generated
    assert "simplicio-cli 0.5.19" not in generated  # the stale version this replaced
    assert "simplicio-mapper 0.8.0" not in generated  # the stale version this replaced
    for req in project["dependencies"]:
        assert req in generated


def test_doc_documents_dev_cli_position_between_mapper_and_loop():
    project = _load_project()
    generated = render(project, _local_default_model())

    assert "simplicio-mapper" in generated
    assert "simplicio-loop" in generated
    assert "forbidden on the hot path" in generated
