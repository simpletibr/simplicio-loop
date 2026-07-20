try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: tomllib is stdlib only from 3.11+
    import tomli as tomllib  # type: ignore[no-redef]
from pathlib import Path

from simplicio import __version__


def test_package_version_matches_release_metadata() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert __version__ == project["version"]
    assert project["requires-python"] == ">=3.10"


def test_simplicio_ecosystem_dependency_floors_are_current() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert "simplicio-mapper>=0.24.1" in project["dependencies"]
    assert "simplicio-prompt>=1.14.1" in project["dependencies"]


def test_dev_cli_entrypoint_is_available_for_runtime_adapter() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert "simplicio" not in project["scripts"]
    assert project["scripts"]["simplicio-py"] == "simplicio.cli:main"
    assert project["scripts"]["simplicio-dev-cli"] == "simplicio.cli:main"
