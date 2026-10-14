"""The install smoke installs the wheel WITH its declared dependencies (Parte de #1565).

The wheels here are tiny fakes built in the test and the dependency index is a local directory (`PIP_NO_INDEX` plus
`PIP_FIND_LINKS`), so the test needs no network. The smoke keeps `env`, so pip reads these variables.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.install_smoke import run_smoke

pytestmark = pytest.mark.skipif(importlib.util.find_spec("ensurepip") is None, reason="the smoke needs ensurepip")

VERSION = "9.9.9"


def _wheel(directory: Path, name: str, version: str, files: dict, requires=(), entry_points: str = "") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    dist = f"{name}-{version}.dist-info"
    meta = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n" + "".join(f"Requires-Dist: {r}\n" for r in requires)
    members = dict(files)
    members[f"{dist}/METADATA"] = meta
    members[f"{dist}/WHEEL"] = "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    if entry_points:
        members[f"{dist}/entry_points.txt"] = entry_points
    members[f"{dist}/RECORD"] = "".join(f"{path},,\n" for path in [*members, f"{dist}/RECORD"])
    path = directory / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for member, text in members.items():
            archive.writestr(member, text)
    return path


def _loop_wheel(directory: Path, requires=(), exit_code: int = 0) -> Path:
    cli = (
        "import os, sys\n"
        "import smokedep\n"
        "def main():\n"
        "    print('usage: simplicio-loop [-h]')\n"
        "    print('DAEMON=' + os.environ.get('SIMPLICIO_LOOP_DAEMON', 'unset'))\n"
        f"    return {exit_code}\n"
    )
    return _wheel(
        directory, "simplicio_loop", VERSION,
        {"simplicio_loop/__init__.py": f"__version__ = '{VERSION}'\n", "simplicio_loop/cli.py": cli},
        requires=requires, entry_points="[console_scripts]\nsimplicio-loop = simplicio_loop.cli:main\n",
    )


@pytest.fixture()
def index(tmp_path, monkeypatch):
    """A local dependency index with one package, `smokedep`. Nothing else resolves."""
    houses = tmp_path / "wheelhouse"
    _wheel(houses, "smokedep", "1.0", {"smokedep/__init__.py": ""})
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_FIND_LINKS", str(houses))
    monkeypatch.setenv("PIP_RETRIES", "0")
    monkeypatch.setenv("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    monkeypatch.delenv("SIMPLICIO_LOOP_DAEMON", raising=False)
    return tmp_path


def _smoke(tmp_path: Path, wheel: Path) -> dict:
    return run_smoke(tmp_path / "repo", expected_version=VERSION, keep=False, wheel_path=wheel)


def test_the_wheel_is_installed_with_its_declared_dependencies(index):
    result = _smoke(index, _loop_wheel(index / "dist", requires=["smokedep"]))
    assert result["ok"] is True, result
    command = result["install"]["command"].split()
    assert "--no-deps" not in command and "--no-index" not in command
    assert "no_deps" not in result["install"]
    assert result["cli_help"]["ok"] is True


def test_a_dependency_that_does_not_resolve_ends_as_install_failed_with_the_cause(index):
    result = _smoke(index, _loop_wheel(index / "dist", requires=["smokedep", "smokedep-missing"]))
    assert result["ok"] is False
    assert result["reason_code"] == "install_failed"
    assert result["install"]["ok"] is False
    assert "smokedep-missing" in result["cause"]
    assert "probe" not in result and "cli_help" not in result


def test_the_daemon_switch_is_not_set_for_the_help_run(index):
    result = _smoke(index, _loop_wheel(index / "dist", requires=["smokedep"]))
    assert "DAEMON=unset" in result["cli_help"]["stdout_tail"]


def test_a_help_run_with_a_non_zero_exit_fails_the_smoke(index):
    result = _smoke(index, _loop_wheel(index / "dist", requires=["smokedep"], exit_code=3))
    assert result["ok"] is False
    assert result["reason_code"] == "cli_help_failed"
    assert result["cli_help"]["returncode"] == 3
