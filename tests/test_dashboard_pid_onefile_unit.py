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
    monkeypatch.setattr(cli, '_parent_pid', lambda pid: BOOTLOADER_PID if pid == SERVER_PID else None)


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


@pytest.mark.parametrize('platform', ['linux', 'darwin', 'win32'])
@pytest.mark.parametrize('reported', [True, 1, 0, -5, '222', 222.0, None])
def test_a_pid_that_cannot_be_the_server_is_never_recorded(tmp_path, monkeypatch, reported, platform):
    """--stop sends SIGTERM to the recorded pid. True is 1 for os.kill, and pid 1 is init.

    The parent check reads /proc and runs on Linux only, so the other systems rely on this rule alone.
    """
    monkeypatch.setattr(cli.sys, 'platform', platform)
    monkeypatch.setattr(cli, '_health', lambda port: {'pid': reported})

    cli.main(['--port', '0', '--no-browser', '--repo', str(tmp_path)])

    assert runs.read_state_file()['pid'] == BOOTLOADER_PID


def test_a_pid_that_is_not_a_child_of_the_spawned_process_is_not_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, '_health', lambda port: {'pid': SERVER_PID})
    monkeypatch.setattr(cli, '_parent_pid', lambda pid: 99999)  # some other process answers on that port
    monkeypatch.setattr(cli.sys, 'platform', 'linux')

    cli.main(['--port', '0', '--no-browser', '--repo', str(tmp_path)])

    assert runs.read_state_file()['pid'] == BOOTLOADER_PID


def test_a_child_of_the_spawned_process_is_recorded_on_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, '_health', lambda port: {'pid': SERVER_PID})
    monkeypatch.setattr(cli, '_parent_pid', lambda pid: BOOTLOADER_PID if pid == SERVER_PID else None)
    monkeypatch.setattr(cli.sys, 'platform', 'linux')

    cli.main(['--port', '0', '--no-browser', '--repo', str(tmp_path)])

    assert runs.read_state_file()['pid'] == SERVER_PID


def test_parent_pid_reads_proc_stat_even_when_the_command_name_has_spaces_and_parentheses(tmp_path, monkeypatch):
    stat = tmp_path / 'stat'
    stat.write_text('222 (my (odd) name) S 111 222 222 0 -1 4194560\n')
    real_open = open
    monkeypatch.setattr('builtins.open', lambda path, *a, **k: real_open(stat if str(path) == '/proc/222/stat' else path, *a, **k))
    assert cli._parent_pid(222) == 111
