import tomllib
from pathlib import Path

from simplicio import __version__


def test_package_version_matches_release_metadata() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["version"] == "0.5.19"
    assert __version__ == project["version"]
    assert project["requires-python"] == ">=3.10"


def test_simplicio_ecosystem_dependency_floors_are_current() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert "simplicio-mapper>=0.8.0" in project["dependencies"]
    assert "simplicio-prompt>=1.14.0" in project["dependencies"]


def test_dev_cli_entrypoint_is_available_for_runtime_adapter() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["scripts"]["simplicio"] == "simplicio.cli:main"
    assert project["scripts"]["simplicio-dev-cli"] == "simplicio.cli:main"
