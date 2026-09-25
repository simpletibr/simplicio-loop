"""Tests for scripts/check-version-sync.py (issue #102)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check-version-sync.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_version_sync", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cvs = _load_module()


def _write_aligned_tree(root: Path, version: str = "1.2.3") -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "fixture"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    pkg = root / "simplicio_mapper"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        f'"""fixture package."""\n\n__version__ = "{version}"\n',
        encoding="utf-8",
    )


def test_repo_sources_are_currently_aligned() -> None:
    ok, sources, messages = cvs.check_versions(REPO_ROOT)
    assert ok, messages
    assert len(set(sources.values())) == 1
    assert messages[0].startswith("[ok] version ")


def test_main_exits_zero_on_current_repo() -> None:
    assert cvs.main(["--root", str(REPO_ROOT)]) == 0


def test_aligned_fixture_passes(tmp_path: Path) -> None:
    _write_aligned_tree(tmp_path, "9.9.9")
    ok, sources, messages = cvs.check_versions(tmp_path)
    assert ok
    assert sources["pyproject.toml"] == "9.9.9"
    assert sources["simplicio_mapper/__init__.py"] == "9.9.9"
    assert cvs.main(["--root", str(tmp_path)]) == 0


def test_deliberate_mismatch_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_aligned_tree(tmp_path, "1.0.0")
    (tmp_path / "simplicio_mapper" / "__init__.py").write_text(
        '"""fixture package."""\n\n__version__ = "1.0.1"\n',
        encoding="utf-8",
    )
    ok, sources, messages = cvs.check_versions(tmp_path)
    assert not ok
    assert sources["simplicio_mapper/__init__.py"] == "1.0.1"
    assert sources["pyproject.toml"] == "1.0.0"
    assert cvs.main(["--root", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "version mismatch" in err
    assert "pyproject.toml" in err


def test_missing_init_version_fails(tmp_path: Path) -> None:
    _write_aligned_tree(tmp_path, "2.0.0")
    (tmp_path / "simplicio_mapper" / "__init__.py").write_text(
        '"""no version here."""\n',
        encoding="utf-8",
    )
    assert cvs.main(["--root", str(tmp_path)]) == 1


def test_init_reads_first_assignment_not_importlib_override(tmp_path: Path) -> None:
    """Static fallback string is the SoT for the guard even when runtime overrides."""
    (tmp_path / "pyproject.toml").write_text(
        'version = "3.0.0"\n', encoding="utf-8"
    )
    pkg = tmp_path / "simplicio_mapper"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        '''"""fixture."""
__version__ = "3.0.0"
try:
    from importlib.metadata import version as _v
    __version__ = _v("simplicio-mapper")
except Exception:
    pass
''',
        encoding="utf-8",
    )
    ok, sources, _ = cvs.check_versions(tmp_path)
    assert ok
    assert sources["simplicio_mapper/__init__.py"] == "3.0.0"
