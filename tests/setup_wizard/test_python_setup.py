"""`setup` and `doctor` and the Python they find (#1842): a Python installed in this run is checked again, a Python that this
process cannot see yet asks for a new terminal, and the doctor row names the Python and its path."""
from __future__ import annotations

import os

import pytest

from simplicio_loop import prereqs, setup_cli

from .fakes import Fakes, check, run

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX modes and symlinks, as in test_flow.py")
WINGET_FIX = "winget install -e --id Python.Python.3.11"


def check_all_calls(fakes):
    return [call for call in fakes.calls if call[0] == "check_all"]


def test_a_python_installed_in_this_run_is_checked_again(home):
    fakes = Fakes()
    fakes.actions = [prereqs.Action(name="python", result="installed", detail="/u/python3.11")]
    run(fakes, home)
    assert len(check_all_calls(fakes)) == 2


def test_a_python_that_this_process_cannot_see_yet_asks_for_a_new_terminal(home):
    fakes = Fakes()
    fakes.checks = [check("python", "missing", fix=WINGET_FIX), check("gh")]
    fakes.actions = [prereqs.Action(name="python", result="installed", detail=f"`{WINGET_FIX}`")]
    code, text = run(fakes, home)
    assert code == setup_cli.PENDING
    assert "python: missing. Fix: open a new terminal and run `simplicio-loop setup` to confirm python" in text
    assert WINGET_FIX not in text.split("Pending", 1)[1]


def test_the_doctor_row_names_the_python_found_and_its_path(home):
    fakes = Fakes()  # check("python") is found at /usr/bin/python, version 1.0.0
    run(fakes, home)
    row = setup_cli.doctor_row(home / ".simplicio-loop")
    assert row["status"] == "ok" and "python 1.0.0 at /usr/bin/python" in row["summary"]


def test_the_doctor_row_warns_and_names_python_when_no_usable_python_was_found(home):
    fakes = Fakes()
    fakes.checks = [check("python", "missing", fix="uv python install 3.11"), check("gh")]
    run(fakes, home)
    row = setup_cli.doctor_row(home / ".simplicio-loop")
    assert row["status"] == "warn" and "python missing" in row["summary"] and "python 1.0.0" not in row["summary"]
