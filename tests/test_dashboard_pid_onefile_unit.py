"""`dashboard --stop` must work when the server is a child of the one-file bootloader (issue #1576).

A one-file build starts a bootloader first, and the bootloader starts the Python server. Popen.pid is the
bootloader. /api/health answers with the pid of the server. --stop kills the recorded pid only when
health reports the same pid, so the state file must hold the pid that health reports.
"""
import os

import pytest

from simplicio_loop.dashboard import cli, runs

BOOTLOADER_PID = 111
SERVER_PID = 222


class _Bootloader:
    pid = BOOTLOADER_PID
    returncode = None

    def poll(self):
        return None


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('SIMPLICIO_DASHBOARD_STATE', str(tmp_path / 'state' / 'dashboard.json'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setattr(cli, '_spawn', lambda port, repos, log: _Bootloader())
    monkeypatch.setattr(cli, '_startup', lambda log: (4321, 'tok'))


def test_the_state_file_holds_the_pid_that_health_reports(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_health', lambda port: {'pid': SERVER_PID})

    assert cli.main(['--port', '0', '--no-browser', '--repo', str(tmp_path)]) == 0

    assert runs.read_state_file()['pid'] == SERVER_PID
    assert 'simplicio-live: http://127.0.0.1:4321/?t=tok' in capsys.readouterr().out


def test_stop_kills_the_server_and_succeeds(tmp_path, monkeypatch, capsys):
    answers = {'alive': True}
    monkeypatch.setattr(cli, '_health', lambda port: {'pid': SERVER_PID} if answers['alive'] else None)
    cli.main(['--port', '0', '--no-browser', '--repo', str(tmp_path)])
    killed = []
    monkeypatch.setattr(os, 'kill', lambda pid, sig: (killed.append(pid), answers.update(alive=False)))

    assert cli.main(['--stop']) == 0

    assert killed == [SERVER_PID]
    assert 'dashboard stopped (pid 222)' in capsys.readouterr().out


def test_a_second_start_reuses_the_server(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_health', lambda port: {'pid': SERVER_PID})
    cli.main(['--port', '0', '--no-browser', '--repo', str(tmp_path)])
    spawned = []
    monkeypatch.setattr(cli, '_spawn', lambda *a: spawned.append(a))

    assert cli.main(['--port', '0', '--no-browser', '--repo', str(tmp_path)]) == 0

    assert spawned == []
    assert 'reusing the dashboard already running (pid 222)' in capsys.readouterr().err


def test_without_a_health_answer_the_spawned_pid_is_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, '_health', lambda port: None)

    cli.main(['--port', '0', '--no-browser', '--repo', str(tmp_path)])

    assert runs.read_state_file()['pid'] == BOOTLOADER_PID
