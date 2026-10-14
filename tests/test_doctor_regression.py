"""Regression test for Issue #1809: bare 'simplicio-loop doctor' overview.

Proves:
1. `simplicio-loop doctor` without a subcommand runs the general stack health overview
   (equivalent to `doctor all`), without requiring `--storage` or any subcommand.
2. Returns a clean exit code (0 on ok/warn).
3. The parser's `--help` explicitly states that default is the stack health overview
   and describes the available subcommands.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop import cli_impl, doctor_overview as dov


def test_bare_doctor_runs_overview_cleanly(capsys, monkeypatch):
    """Bare `simplicio-loop doctor` runs the general health overview and exits with 0."""
    monkeypatch.setattr(
        dov.path_operators,
        "check",
        lambda **kw: [
            {"name": "simplicio-mapper", "path": None, "status": "absent", "reason_code": None, "found": None, "bundled": {}, "fix": None},
            {"name": "simplicio-dev-cli", "path": None, "status": "absent", "reason_code": None, "found": None, "bundled": "", "fix": None},
        ],
    )
    rc = cli_impl.main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "simplicio-loop doctor:" in out
    assert "login" in out
    assert "update" in out
    assert "distribution" in out
    assert "runtime" in out
    assert "operators" in out
    assert "disk" in out


def test_bare_doctor_json_parity_with_doctor_all(capsys, monkeypatch):
    """Bare `simplicio-loop doctor --json` outputs the same schema and checks as `doctor all --json`."""
    monkeypatch.setattr(
        dov.path_operators,
        "check",
        lambda **kw: [
            {"name": "simplicio-mapper", "path": None, "status": "absent", "reason_code": None, "found": None, "bundled": {}, "fix": None},
            {"name": "simplicio-dev-cli", "path": None, "status": "absent", "reason_code": None, "found": None, "bundled": "", "fix": None},
        ],
    )
    rc_bare = cli_impl.main(["doctor", "--json"])
    bare_data = json.loads(capsys.readouterr().out)
    assert rc_bare == 0
    assert bare_data["schema"] == "simplicio.doctor/v1"

    rc_all = cli_impl.main(["doctor", "all", "--json"])
    all_data = json.loads(capsys.readouterr().out)
    assert rc_all == 0

    bare_checks = [c["name"] for c in bare_data["checks"]]
    all_checks = [c["name"] for c in all_data["checks"]]
    assert bare_checks == all_checks
    assert "login" in bare_checks
    assert "disk" in bare_checks


def test_bare_doctor_does_not_require_storage_or_subcommand(capsys, monkeypatch):
    """Invoking bare `doctor` executes overview without requiring `--storage` or subcommand."""
    called = []
    monkeypatch.setattr(dov, "run", lambda *a, **kw: called.append((a, kw)) or 0)
    rc = cli_impl.main(["doctor"])
    assert rc == 0
    assert len(called) == 1
    # Check that doctor_overview.run was called with as_json=False, online=False
    args, kwargs = called[0]
    assert kwargs.get("as_json") is False
    assert kwargs.get("online") is False


def test_doctor_help_explains_default_overview_and_subcommands():
    """`simplicio-loop doctor --help` explicitly describes the default overview and subcommands."""
    repo_root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(repo_root)}
    proc = subprocess.run(
        [sys.executable, "-m", "simplicio_loop.cli", "doctor", "--help"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0
    help_text = proc.stdout
    # Mentions running without subcommand executes general overview / equivalent to doctor all
    assert "without a subcommand" in help_text
    assert "doctor all" in help_text
    assert "without requiring --storage" in help_text
    # Describes subcommands
    for subcmd in ("stack", "source", "all", "login", "mapper"):
        assert subcmd in help_text
