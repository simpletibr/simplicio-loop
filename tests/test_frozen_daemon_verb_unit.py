"""In a frozen build or on Windows, ``daemon status|stop|serve`` never becomes a loop task (issue #1633).

The binary has no daemon client, so ``daemon.client.main`` hands the command line to ``cli.main``. That parser
does not know the verb ``daemon``, so it used to treat ``daemon status`` as the prose of a task and run a turbo
survey in the current directory.
"""
from __future__ import annotations

import os
import sys

import pytest

from simplicio_loop import cli, frozen
from simplicio_loop.daemon import client, control, protocol

LOOP_SCRIPTS = {"simplicio-loop": "simplicio_loop.daemon.client:main"}


@pytest.fixture
def turbo_calls(monkeypatch, tmp_path):
    """Replace the turbo entry point with a recorder; the test runs in an empty directory."""
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return 0

    monkeypatch.setattr("simplicio_loop.turbo_cli.run", fake_run)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(protocol.OPT_OUT_ENV, raising=False)
    return calls


@pytest.fixture
def frozen_build(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert not protocol.supported()


@pytest.mark.parametrize("verb, code", [("status", 3), ("stop", 0), ("serve", protocol.EX_UNAVAILABLE)])
def test_frozen_daemon_verb_prints_a_line_and_runs_no_task(frozen_build, turbo_calls, capsys, tmp_path, verb, code):
    assert client.main(["daemon", verb]) == code
    out, err = capsys.readouterr()
    line = (out + err).strip()
    assert len(line.splitlines()) == 1 and "daemon is not used" in line, line
    assert turbo_calls == []
    assert os.listdir(tmp_path) == []  # no .simplicio-loop/ in the current directory


def test_frozen_dispatch_of_the_loop_binary_runs_no_task(frozen_build, turbo_calls, capsys):
    assert frozen.dispatch(["/opt/bin/simplicio-loop", "daemon", "status"], LOOP_SCRIPTS) == 3
    assert "daemon is not used" in capsys.readouterr().out
    assert turbo_calls == []


def test_windows_gets_the_same_answer(monkeypatch, turbo_calls, capsys):
    monkeypatch.setattr(sys, "platform", "win32")
    assert not protocol.supported()
    assert client.main(["daemon", "stop"]) == 0
    assert "daemon is not used" in capsys.readouterr().out
    assert turbo_calls == []


@pytest.mark.parametrize("arguments", [["daemon"], ["daemon", "restart"], ["daemon", "--help"]])
def test_an_unknown_daemon_verb_is_refused_with_the_valid_ones(frozen_build, turbo_calls, capsys, arguments):
    assert client.main(arguments) == 2
    err = capsys.readouterr().err
    assert "serve" in err and "status" in err and "stop" in err, err
    assert turbo_calls == []


def test_where_the_daemon_runs_the_verb_goes_to_the_daemon_control(monkeypatch, turbo_calls):
    """No blanket answer: where a daemon exists (SIMPLICIO_LOOP_DAEMON=0 still reaches cli.main) the verb is real."""
    monkeypatch.setattr(protocol, "supported", lambda: True)
    seen = []
    monkeypatch.setattr(control, "main", lambda arguments: seen.append(list(arguments)) or 7)
    assert cli.main(["daemon", "status"]) == 7
    assert seen == [["status"]]
    assert turbo_calls == []


def test_a_single_unknown_word_is_refused_with_the_valid_commands(turbo_calls, capsys):
    assert cli.main(["statu"]) == 2
    err = capsys.readouterr().err
    assert "unknown command 'statu'" in err
    for name in ("install", "turbo", "doctor", "update"):
        assert name in err, err
    assert turbo_calls == []


def test_prose_of_several_words_is_still_a_task(turbo_calls):
    assert cli.main(["fix", "the", "login", "bug"]) == 0
    assert [call[0][1] for call in turbo_calls] == [["fix the login bug"]]


def test_a_quoted_one_word_task_is_not_an_unknown_command(turbo_calls):
    assert cli.main(["fix the bug"]) == 0
    assert [call[0][1] for call in turbo_calls] == [["fix the bug"]]
