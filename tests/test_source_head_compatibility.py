"""Compatibility checks for the requested source-head integration train."""
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).parents[1]

# Measured from the source heads used by the 2026-09-13 integration audit.
SOURCE_HEAD_VERSIONS = {
    "simplicio-mapper": "0.26.31",
    "simplicio-fast": "2.0.32",
    "simplicio-cli": "0.18.12",
}


def _version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _bounds(dependency: str, name: str) -> tuple[str, str]:
    match = re.fullmatch(rf"{re.escape(name)}>=(\d+\.\d+\.\d+),<(\d+(?:\.\d+){{0,2}})", dependency)
    assert match, f"unexpected dependency declaration for {name}: {dependency}"
    return match.group(1), match.group(2)


def test_requested_source_heads_satisfy_loop_dependency_floors() -> None:
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = manifest["project"]["dependencies"]

    for name, source_version in SOURCE_HEAD_VERSIONS.items():
        declaration = next(
            dependency for dependency in dependencies
            if dependency.startswith(f"{name}>=")
        )
        floor, ceiling = _bounds(declaration, name)
        assert _version(floor) <= _version(source_version) < _version(ceiling), (
            f"{name} declaration {declaration} excludes requested source head "
            f"{source_version}"
        )
