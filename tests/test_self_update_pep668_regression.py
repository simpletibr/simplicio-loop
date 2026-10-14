"""Regression tests for Issue #1802: simplicio-loop update on PEP 668 environments.

Proves:
1. `is_pep668_environment` detects PEP 668 (EXTERNALLY-MANAGED) system environments.
2. `is_pep668_environment` ignores PEP 668 when in a virtualenv or when PIP_BREAK_SYSTEM_PACKAGES=1.
3. `run_update` halts before executing `pip` uninstall/install when PEP 668 is detected.
4. The diagnostic message clearly describes the externally-managed-environment and
   provides the recommended remediation commands: `venv`, `uv pip`, `pipx`,
   and `--break-system-packages` (when authorized).
5. Returns exit code 2 when stopped by PEP 668.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from simplicio_loop import self_update as su


def test_is_pep668_detects_marker_file(tmp_path):
    """When EXTERNALLY-MANAGED exists in the prefix lib directory, it is detected."""
    prefix = tmp_path / "system_python"
    lib_dir = prefix / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"
    lib_dir.mkdir(parents=True)
    marker = lib_dir / "EXTERNALLY-MANAGED"
    marker.write_text("[externally-managed]\nError=Use your OS package manager.\n", encoding="utf-8")

    is_managed, details = su.is_pep668_environment(
        prefix=str(prefix),
        base_prefix=str(prefix),
        environ={},
    )
    assert is_managed is True
    assert "Use your OS package manager" in (details or "")


def test_is_pep668_false_in_virtualenv(tmp_path):
    """In a virtualenv (sys.prefix != sys.base_prefix), PEP 668 does not block pip."""
    venv_prefix = tmp_path / "venv"
    base_prefix = tmp_path / "system"
    # Even if base_prefix has the marker:
    lib_dir = base_prefix / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"
    lib_dir.mkdir(parents=True)
    (lib_dir / "EXTERNALLY-MANAGED").write_text("blocked", encoding="utf-8")

    is_managed, _ = su.is_pep668_environment(
        prefix=str(venv_prefix),
        base_prefix=str(base_prefix),
        environ={},
    )
    assert is_managed is False


def test_is_pep668_bypassed_by_break_system_packages():
    """Setting PIP_BREAK_SYSTEM_PACKAGES=1 allows bypassing PEP 668."""
    is_managed, _ = su.is_pep668_environment(
        environ={"PIP_BREAK_SYSTEM_PACKAGES": "1"},
    )
    assert is_managed is False


def test_run_update_halts_before_pip_on_pep668(capsys):
    """run_update refuses to invoke pip uninstall/install on PEP 668 and prints remediation options."""
    calls = []
    rc = su.run_update(
        installed="3.43.16",
        fetch=lambda: "v3.44.0",
        runner=lambda cmd: calls.append(cmd) or 0,
        editable=False,
        externally_managed=True,
    )
    out = capsys.readouterr().out
    assert rc == 2
    assert calls == []  # No pip calls were made
    assert "externally-managed-environment" in out
    assert "venv" in out
    assert "uv pip" in out
    assert "pipx" in out
    assert "--break-system-packages" in out


def test_run_update_checks_pep668_before_legacy_uninstall(capsys):
    """When up-to-date but legacy distributions exist, PEP 668 stops before pip uninstall."""
    calls = []
    rc = su.run_update(
        installed="3.44.0",
        fetch=lambda: "v3.44.0",
        runner=lambda cmd: calls.append(cmd) or 0,
        editable=False,
        legacy=["simplicio-cli", "simplicio-mapper"],
        externally_managed=True,
    )
    out = capsys.readouterr().out
    assert rc == 2
    assert calls == []  # Did not attempt pip uninstall
    assert "externally-managed-environment" in out
    assert "venv" in out
    assert "uv pip" in out
    assert "pipx" in out


def test_run_update_proceeds_when_not_externally_managed():
    """In a normal virtualenv or non-PEP668 environment, pip install proceeds."""
    calls = []
    rc = su.run_update(
        installed="3.43.16",
        fetch=lambda: "v3.44.0",
        runner=lambda cmd: calls.append(cmd) or 0,
        editable=False,
        legacy=[],
        externally_managed=False,
    )
    assert rc == 0
    assert len(calls) == 2
    assert "install" in calls[0]
