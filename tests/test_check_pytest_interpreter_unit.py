"""#1825: the local gate runs pytest through the interpreter that runs ``check.py``.

A ``pytest`` found on PATH can belong to another interpreter (for example a ``uv tool`` venv without
``jsonschema``), so collection fails for a reason unrelated to the repository. ``sys.executable -m
pytest`` always uses the environment the developer installed ``.[dev]`` into.
"""
from __future__ import annotations

import os
import stat
import sys

from scripts import check
from scripts.check_runtime import CommandResult


def _fake_pytest_on_path(tmp_path, monkeypatch):
    """An executable ``pytest`` first on PATH that records any use, as a foreign interpreter's would."""
    bin_dir = tmp_path / "foreign-bin"
    bin_dir.mkdir()
    marker = tmp_path / "foreign-pytest-was-used"
    script = bin_dir / "pytest"
    script.write_text("#!/bin/sh\necho used > '%s'\nexit 3\n" % marker, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    return marker


def test_pytest_command_is_the_running_interpreter_even_with_another_pytest_on_path(tmp_path, monkeypatch):
    _fake_pytest_on_path(tmp_path, monkeypatch)
    assert check._pytest_command() == [sys.executable, "-m", "pytest"]


def test_every_pytest_invocation_of_the_gate_goes_through_the_interpreter(tmp_path, monkeypatch):
    marker = _fake_pytest_on_path(tmp_path, monkeypatch)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        return CommandResult(0, stdout="pytest 8.0.0\n")

    monkeypatch.setattr(check, "_run_bounded", fake_run)
    check._have_pytest()  # the probe
    check._collect_marker_exclusions(["tests/test_x.py"], {}, "external_integration", "unparseable")
    calls.append(check._pytest_args(["tests/test_x.py"], only_core=True))
    assert len(calls) == 3
    for argv in calls:
        assert argv[:3] == [sys.executable, "-m", "pytest"], argv
    assert not marker.exists()
