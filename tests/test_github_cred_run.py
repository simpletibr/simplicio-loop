"""The real `github_cred._run` (#1657, point 8): a real program, no fake `run`. A `shell=True` mutant must die here."""
from __future__ import annotations

import os
import sys

import pytest

from simplicio_loop import github_cred

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX shell semantics")

ENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}


def test_argv_is_one_literal_list_and_never_goes_through_a_shell(tmp_path):
    marker = tmp_path / "marker"
    argument = f"a b; touch {marker} $HOME `touch {marker}` $(touch {marker})"
    code, out = github_cred._run([sys.executable, "-c", "import sys; print(sys.argv[1])", argument], ENV, None)
    assert (code, out) == (0, argument + "\n")  # with shell=True the list becomes `sh -c python ...` and prints nothing
    assert not marker.exists()


def test_input_text_reaches_stdin_and_without_it_stdin_is_empty():
    read_stdin = [sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"]
    assert github_cred._run(read_stdin, ENV, "protocol=https\n") == (0, "'protocol=https\\n'\n")
    assert github_cred._run(read_stdin, ENV, None) == (0, "''\n")  # DEVNULL: EOF at once, never a wait for the terminal


def test_only_stdout_and_the_exit_code_come_back():
    program = [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(42)"]
    assert github_cred._run(program, ENV, None) == (42, "out\n")


def test_the_child_gets_exactly_the_given_environment(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghp_FAKEFAKEFAKEFAKEFAKE0042")
    program = [sys.executable, "-c", "import os; print(sorted(k for k in os.environ if k in ('GH_TOKEN', 'ONLY_HERE')))"]
    assert github_cred._run(program, {**ENV, "ONLY_HERE": "1"}, None) == (0, "['ONLY_HERE']\n")


def test_a_missing_program_is_none_not_an_exception(tmp_path):
    assert github_cred._run([str(tmp_path / "nope")], ENV, None) == (None, "")
