import json
from pathlib import Path

import pytest

from scripts import release_manifest

REPO = Path(__file__).resolve().parents[1]


def test_release_manifest_proves_all_surfaces_match():
    report = release_manifest.build_manifest(REPO)
    assert report["schema"] == "simplicio.release-manifest/v1"
    assert report["ready"] is True
    assert report["mismatches"] == []
    json.dumps(report)


def test_release_manifest_accepts_matching_fixture(tmp_path: Path):
    (tmp_path / ".cursor-plugin").mkdir()
    (tmp_path / "simplicio_loop").mkdir()
    (tmp_path / "pyproject.toml").write_text('version = "1.2.3"\n')
    (tmp_path / ".cursor-plugin" / "plugin.json").write_text(json.dumps({"version": "1.2.3"}))
    (tmp_path / "simplicio_loop" / "__init__.py").write_text(
        '__version__ = "1.2.3"\n__version__ = "1.2.3"\n')
    assert release_manifest.build_manifest(tmp_path, tag="v1.2.3")["ready"] is True


def test_release_manifest_rejects_wrong_tag():
    report = release_manifest.build_manifest(REPO, tag="v0.0.0")
    assert any("tag" in error for error in report["errors"])


def test_release_manifest_detects_manifest_drift(tmp_path: Path):
    (tmp_path / ".cursor-plugin").mkdir()
    (tmp_path / "simplicio_loop").mkdir()
    (tmp_path / "pyproject.toml").write_text('version = "1.2.3"\n')
    (tmp_path / ".cursor-plugin" / "plugin.json").write_text('{"version":"1.2.4"}')
    (tmp_path / "simplicio_loop" / "__init__.py").write_text('__version__ = "1.2.3"\n')
    report = release_manifest.build_manifest(tmp_path)
    assert report["ready"] is False
    assert "cursor_plugin" in report["mismatches"]


def test_build_manifest_missing_version(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('name = "x"\n')
    with pytest.raises(ValueError):
        release_manifest._pyproject_version(tmp_path / "pyproject.toml")


def test_build_manifest_json_version_errors(tmp_path: Path):
    bad = tmp_path / "package.json"
    bad.write_text("not json")
    with pytest.raises(ValueError):
        release_manifest._json_version(bad)


def test_build_manifest_fallback_versions(tmp_path: Path):
    init = tmp_path / "__init__.py"
    init.write_text('__version__ = "9.9.9"\nX = 1\n')
    vs = release_manifest._fallback_versions(init)
    assert vs == ["9.9.9"]


def test_pyproject_version_oserror(tmp_path: Path):
    missing = tmp_path / "nope.toml"
    with pytest.raises(OSError):
        release_manifest._pyproject_version(missing)


def test_json_version_oserror(tmp_path: Path):
    missing = tmp_path / "nope.json"
    with pytest.raises(ValueError):
        release_manifest._json_version(missing)
