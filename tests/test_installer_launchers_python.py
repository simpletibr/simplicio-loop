"""The public launchers, scripts/install.sh and scripts/install.ps1, start install_lib.py only with a Python that really runs and
is at least the minimum of pyproject.toml (#1842).

A stub that prints an error and exits 9009 stands in for the Microsoft Store alias. Every PATH match is tried, so a stub that
is listed first does not hide a real Python listed after it. Each run's PATH holds only the fake programs (and `dirname` for
install.sh), so no Python installed on this host is ever started. The PowerShell cases run only where pwsh is installed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")
STUB = "echo 'Python was not found; run without arguments to install from the Microsoft Store' >&2\nexit 9009\n"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="the fake programs are POSIX shell scripts")


def fake(folder, name, body):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return folder


def interpreter(folder, version, marker):
    """A python3 that answers the version probe with `version` and records every other call in `marker`."""
    return fake(folder, "python3", f'case "$1" in\n  -c) echo {version} ;;\n  *) echo "$@" > {marker} ;;\nesac\n')


@pytest.fixture
def tools(tmp_path):
    folder = tmp_path / "tools"
    folder.mkdir()
    (folder / "dirname").symlink_to(shutil.which("dirname"))
    return folder


def launch(command, path_dirs, tmp_path):
    env = {"PATH": os.pathsep.join(str(folder) for folder in path_dirs), "HOME": str(tmp_path / "home")}
    return subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          stdin=subprocess.DEVNULL, timeout=120, check=False, cwd=str(tmp_path))


def sh(path_dirs, tmp_path):
    return launch(["/bin/bash", str(REPO / "scripts" / "install.sh"), "claude"], path_dirs, tmp_path)


def ps1(path_dirs, tmp_path):
    return launch([PWSH, "-NoProfile", "-File", str(REPO / "scripts" / "install.ps1"), "claude"], path_dirs, tmp_path)


def installer_ran(marker):
    return marker.exists() and marker.read_text().split()[-1:] == ["claude"]


def test_install_sh_refuses_when_the_only_python_is_a_store_style_stub(tools, tmp_path):
    result = sh([tools, fake(tmp_path / "alias", "python3", STUB)], tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "No usable Python 3.11" in result.stderr and "uv python install 3.11" in result.stderr


def test_install_sh_skips_the_stub_listed_first_and_uses_the_real_python(tools, tmp_path):
    marker = tmp_path / "marker"
    real = interpreter(tmp_path / "real", "3.12", marker)
    result = sh([tools, fake(tmp_path / "alias", "python3", STUB), real], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert installer_ran(marker)


def test_install_sh_refuses_a_python_older_than_the_minimum(tools, tmp_path):
    marker = tmp_path / "marker"
    old = interpreter(tmp_path / "old", "3.9", marker)
    result = sh([tools, old], tmp_path)
    assert result.returncode == 1 and "No usable Python 3.11" in result.stderr and not marker.exists()


@pytest.mark.skipif(PWSH is None, reason="pwsh is not installed")
def test_install_ps1_refuses_when_the_only_python_is_a_store_style_stub(tmp_path):
    result = ps1([fake(tmp_path / "alias", "python3", STUB)], tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "No usable Python 3.11" in result.stderr and "winget install -e --id Python.Python.3.11" in result.stderr


@pytest.mark.skipif(PWSH is None, reason="pwsh is not installed")
def test_install_ps1_skips_the_stub_listed_first_and_uses_the_real_python(tmp_path):
    marker = tmp_path / "marker"
    real = interpreter(tmp_path / "real", "3.12", marker)
    result = ps1([fake(tmp_path / "alias", "python3", STUB), real], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert installer_ran(marker)


@pytest.mark.skipif(PWSH is None, reason="pwsh is not installed")
def test_install_ps1_refuses_a_python_older_than_the_minimum(tmp_path):
    marker = tmp_path / "marker"
    old = interpreter(tmp_path / "old", "3.9", marker)
    result = ps1([old], tmp_path)
    assert result.returncode == 1 and "No usable Python 3.11" in result.stderr and not marker.exists()
