"""Unit tests for `simplicio.component_manifest` (issue #232).

Covers: manifest parsing/validation, the self-contained PEP-440-lite range
checker, `pyproject.toml`/`uv.lock` introspection, compatibility grading,
drift detection, and building this repo's own component-release manifest.
"""

from __future__ import annotations

import pytest

from simplicio import component_manifest as cm

# --------------------------------------------------------------------------- #
# parse_component_manifest
# --------------------------------------------------------------------------- #


def _valid_raw(**overrides):
    payload = {
        "schema": "simplicio.component-release/v1",
        "name": "simplicio-mapper",
        "version": "0.24.0",
        "commit": "abc123",
        "schema_versions": {"MAPPER_ARTIFACT_SCHEMA": "simplicio.canonical-map-manifest/v1"},
        "compatibility_range": ">=0.16.0",
        "compatibility_target": "simplicio-cli",
    }
    payload.update(overrides)
    return payload


def test_parse_component_manifest_happy_path():
    manifest = cm.parse_component_manifest(_valid_raw())
    assert manifest.schema == cm.COMPONENT_MANIFEST_SCHEMA
    assert manifest.name == "simplicio-mapper"
    assert manifest.version == "0.24.0"
    assert manifest.commit == "abc123"
    assert manifest.schema_versions == {"MAPPER_ARTIFACT_SCHEMA": "simplicio.canonical-map-manifest/v1"}
    assert manifest.compatibility_range == ">=0.16.0"
    assert manifest.compatibility_target == "simplicio-cli"
    assert manifest.to_dict()["name"] == "simplicio-mapper"


def test_parse_component_manifest_minimal_required_fields_only():
    raw = {"schema": "simplicio.component-release/v1", "name": "simplicio-mapper", "version": "0.24.0"}
    manifest = cm.parse_component_manifest(raw)
    assert manifest.commit is None
    assert manifest.schema_versions == {}
    assert manifest.compatibility_range is None


def test_parse_component_manifest_rejects_non_dict():
    with pytest.raises(cm.ComponentManifestError, match="must be a dict"):
        cm.parse_component_manifest("not-a-dict")  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["schema", "name", "version"])
def test_parse_component_manifest_rejects_missing_required_field(field):
    raw = _valid_raw()
    del raw[field]
    with pytest.raises(cm.ComponentManifestError, match=field):
        cm.parse_component_manifest(raw)


def test_parse_component_manifest_rejects_unsupported_schema():
    raw = _valid_raw(schema="simplicio.component-release/v99")
    with pytest.raises(cm.ComponentManifestError, match="unsupported component manifest schema"):
        cm.parse_component_manifest(raw)


def test_parse_component_manifest_rejects_wrong_typed_commit():
    raw = _valid_raw(commit=123)
    with pytest.raises(cm.ComponentManifestError, match="'commit'"):
        cm.parse_component_manifest(raw)


def test_parse_component_manifest_rejects_wrong_typed_schema_versions():
    raw = _valid_raw(schema_versions={"K": 1})
    with pytest.raises(cm.ComponentManifestError, match="schema_versions"):
        cm.parse_component_manifest(raw)


def test_parse_component_manifest_rejects_wrong_typed_compatibility_range():
    raw = _valid_raw(compatibility_range=123)
    with pytest.raises(cm.ComponentManifestError, match="compatibility_range"):
        cm.parse_component_manifest(raw)


def test_parse_component_manifest_rejects_empty_name():
    raw = _valid_raw(name="   ")
    with pytest.raises(cm.ComponentManifestError, match="name"):
        cm.parse_component_manifest(raw)


# --------------------------------------------------------------------------- #
# version compare / range parsing
# --------------------------------------------------------------------------- #


def test_compare_versions_basic_ordering():
    assert cm.compare_versions("0.23.1", "0.24.0") == -1
    assert cm.compare_versions("0.24.0", "0.23.1") == 1
    assert cm.compare_versions("0.24.0", "0.24.0") == 0


def test_compare_versions_prerelease_ordering():
    assert cm.compare_versions("1.0.0rc1", "1.0.0") == -1
    assert cm.compare_versions("1.0.0dev0", "1.0.0a1") == -1


def test_parse_version_rejects_garbage():
    with pytest.raises(ValueError):
        cm.parse_version("not-a-version")


def test_parse_range_multi_clause():
    clauses = cm.parse_range(">=0.23.1,<1.0.0")
    assert clauses == [(">=", "0.23.1"), ("<", "1.0.0")]


def test_parse_range_rejects_garbage_clause():
    with pytest.raises(ValueError):
        cm.parse_range("not a real range")


@pytest.mark.parametrize(
    "version,range_spec,expected",
    [
        ("0.24.0", ">=0.23.1", True),
        ("0.23.0", ">=0.23.1", False),
        ("0.23.1", ">=0.23.1", True),
        ("0.5.0", ">=0.23.1,<1.0.0", False),
        ("0.30.0", ">=0.23.1,<1.0.0", True),
        ("1.0.0", ">=0.23.1,<1.0.0", False),
        ("0.24.0", "==0.24.0", True),
        ("0.24.1", "==0.24.0", False),
        ("0.24.0", "!=0.24.0", False),
        ("1.4.2", "~=1.4", True),
        ("2.0.0", "~=1.4", False),
    ],
)
def test_version_satisfies(version, range_spec, expected):
    assert cm.version_satisfies(version, range_spec) is expected


# --------------------------------------------------------------------------- #
# pyproject.toml / uv.lock introspection (against THIS repo's real files)
# --------------------------------------------------------------------------- #


def test_declared_dependency_range_reads_real_pyproject():
    # This is the exact case the issue reports as verified: the floor pin.
    assert cm.declared_dependency_range("simplicio-mapper") == ">=0.26.10,<0.27"


def test_declared_dependency_range_unknown_package_returns_none():
    assert cm.declared_dependency_range("not-a-real-dependency-xyz") is None


def test_declared_own_version_matches_pyproject():
    from pathlib import Path

    import tomllib

    root = Path(__file__).resolve().parents[2]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert cm.declared_own_version() == data["project"]["version"]


def test_tested_dependency_version_reads_real_uv_lock():
    version, reason = cm.tested_dependency_version("simplicio-mapper")
    assert version == "0.26.10"
    assert reason == "locked_in_uv.lock"


def test_tested_dependency_version_missing_lockfile(tmp_path):
    version, reason = cm.tested_dependency_version("simplicio-mapper", root=tmp_path)
    assert version is None
    assert reason == "no_lockfile_found"


def test_tested_dependency_version_package_absent_from_lockfile(tmp_path):
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "some-other-package"\nversion = "1.0.0"\n', encoding="utf-8"
    )
    version, reason = cm.tested_dependency_version("simplicio-mapper", root=tmp_path)
    assert version is None
    assert reason == "not_present_in_lockfile"


def test_tested_dependency_version_unparseable_lockfile(tmp_path):
    (tmp_path / "uv.lock").write_text("not { valid toml :::", encoding="utf-8")
    version, reason = cm.tested_dependency_version("simplicio-mapper", root=tmp_path)
    assert version is None
    assert reason.startswith("lockfile_unparseable")


# --------------------------------------------------------------------------- #
# compatibility check
# --------------------------------------------------------------------------- #


def _manifest(version="0.24.0", **overrides):
    return cm.parse_component_manifest(_valid_raw(version=version, **overrides))


def test_check_component_compatibility_compatible():
    result = cm.check_component_compatibility(_manifest("0.24.0"), ">=0.23.1")
    assert result.status == cm.COMPATIBLE
    assert result.to_dict()["status"] == cm.COMPATIBLE


def test_check_component_compatibility_incompatible():
    result = cm.check_component_compatibility(_manifest("0.10.0"), ">=0.23.1")
    assert result.status == cm.INCOMPATIBLE


def test_check_component_compatibility_needs_review_no_range():
    result = cm.check_component_compatibility(_manifest("0.24.0"), None)
    assert result.status == cm.NEEDS_REVIEW
    assert "no declared compatibility range" in result.reason


def test_check_component_compatibility_needs_review_unparseable_range():
    result = cm.check_component_compatibility(_manifest("0.24.0"), "garbage-range")
    assert result.status == cm.NEEDS_REVIEW


def test_check_version_against_range_bare_version():
    result = cm.check_version_against_range("0.24.0", ">=0.23.1", name="simplicio-mapper")
    assert result.status == cm.COMPATIBLE
    assert result.candidate_version == "0.24.0"


# --------------------------------------------------------------------------- #
# drift detection
# --------------------------------------------------------------------------- #


def test_detect_drift_not_installed():
    result = cm.detect_drift(
        name="simplicio-mapper", installed=None, declared_range=">=0.23.1", tested_against="0.23.1"
    )
    assert result.has_drift is True
    assert result.kind == "not_installed"


def test_detect_drift_out_of_range():
    result = cm.detect_drift(
        name="simplicio-mapper", installed="0.10.0", declared_range=">=0.23.1", tested_against=None
    )
    assert result.has_drift is True
    assert result.kind == "out_of_range"


def test_detect_drift_stale_vs_tested_but_in_range():
    """The exact issue #232 scenario: installed 0.24.0 satisfies the >=0.23.1
    floor, but the lockfile only ever verified 0.23.1 — report drift without
    claiming the combination is broken."""
    result = cm.detect_drift(
        name="simplicio-mapper", installed="0.24.0", declared_range=">=0.23.1", tested_against="0.23.1"
    )
    assert result.has_drift is True
    assert result.kind == "stale_vs_tested"
    assert "0.23.1" in result.reason
    assert "0.24.0" in result.reason


def test_detect_drift_clean_when_installed_matches_tested_and_range():
    result = cm.detect_drift(
        name="simplicio-mapper", installed="0.23.1", declared_range=">=0.23.1", tested_against="0.23.1"
    )
    assert result.has_drift is False
    assert result.kind is None


def test_detect_drift_no_range_no_tested_never_raises():
    result = cm.detect_drift(name="x", installed="1.0.0", declared_range=None, tested_against=None)
    assert result.has_drift is False


def test_detect_drift_unparseable_range_reports_not_raises():
    result = cm.detect_drift(
        name="simplicio-mapper", installed="0.24.0", declared_range="garbage", tested_against=None
    )
    assert result.has_drift is True
    assert result.kind == "unparseable_range"


# --------------------------------------------------------------------------- #
# own manifest
# --------------------------------------------------------------------------- #


def test_own_schema_versions_finds_real_constants():
    schemas = cm.own_schema_versions()
    assert schemas.get("EVENT_SCHEMA") == "simplicio.dev-cli-event/v1"
    assert schemas.get("COMPONENT_MANIFEST_SCHEMA") == "simplicio.component-release/v1"
    assert all(v.startswith("simplicio.") for v in schemas.values())


def test_own_commit_returns_a_real_sha_in_this_repo():
    commit = cm.own_commit()
    assert commit is None or (isinstance(commit, str) and len(commit) == 40)


def test_own_commit_fails_open_outside_a_git_repo(tmp_path):
    assert cm.own_commit(tmp_path) is None


def test_build_own_manifest_shape():
    manifest = cm.build_own_manifest()
    assert manifest.schema == cm.COMPONENT_MANIFEST_SCHEMA
    assert manifest.name == "simplicio-cli"
    assert manifest.compatibility_target == "simplicio-mapper"
    assert manifest.compatibility_range == ">=0.26.10,<0.27"
    assert manifest.version  # non-empty
    assert "EVENT_SCHEMA" in manifest.schema_versions
