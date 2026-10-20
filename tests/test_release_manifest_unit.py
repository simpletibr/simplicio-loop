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


def test_build_manifest_flags_a_stale_literal_behind_installed_version(tmp_path: Path):
    # simplicio_loop/__init__.py carries two literal fallbacks; the one behind `installed_version() or`
    # is a fallback too, so a stale copy must block the release instead of hiding behind the bare literal.
    (tmp_path / ".cursor-plugin").mkdir()
    (tmp_path / "simplicio_loop").mkdir()
    (tmp_path / "pyproject.toml").write_text('version = "1.1.0"\n')
    (tmp_path / ".cursor-plugin" / "plugin.json").write_text(json.dumps({"version": "1.1.0"}))
    (tmp_path / "simplicio_loop" / "__init__.py").write_text(
        "def __getattr__(name):\n"
        "    try:\n"
        "        from .distribution import installed_version\n"
        '        __version__ = installed_version() or "1.0.0"\n'
        "    except Exception:  # pragma: no cover\n"
        '        __version__ = "1.1.0"\n'
        "    return __version__\n")
    report = release_manifest.build_manifest(tmp_path)
    assert "source_fallback" in report["mismatches"]
    assert report["ready"] is False
    fallback = next(row for row in report["sources"] if row["name"] == "source_fallback")
    assert fallback["versions"] == ["1.0.0", "1.1.0"]


@pytest.mark.parametrize("line", [
    '__version__ = installed_version() or "1.0.0"',
    '__version__=installed_version()or"1.0.0"',
    "__version__ =  installed_version()   or   '1.0.0'",
])
def test_fallback_versions_reads_the_literal_behind_installed_version(tmp_path: Path, line: str):
    init = tmp_path / "__init__.py"
    init.write_text(line + "\n")
    assert release_manifest._fallback_versions(init) == ["1.0.0"]


def test_the_real_source_fallback_lists_both_literals():
    literals = release_manifest._fallback_versions(REPO / "simplicio_loop" / "__init__.py")
    assert len(literals) == 2
    assert len(set(literals)) == 1


def test_pyproject_version_oserror(tmp_path: Path):
    missing = tmp_path / "nope.toml"
    with pytest.raises(OSError):
        release_manifest._pyproject_version(missing)


def test_json_version_oserror(tmp_path: Path):
    missing = tmp_path / "nope.json"
    with pytest.raises(ValueError):
        release_manifest._json_version(missing)
