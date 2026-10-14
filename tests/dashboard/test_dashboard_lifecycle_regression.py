'''Regression tests for Dashboard lifecycle and port-in-use issues (#1805, #1806).

DOD Layer 1.3:
- Issue #1805: second start deletes state.json of a live dashboard and loses its token.
- Issue #1806: port-in-use message blames the wrong process and reports TIME_WAIT as in use.
'''
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop.dashboard import cli, runs, server

TOKEN = 'lifecycle-token-1234567890'


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv('SIMPLICIO_DASHBOARD_STATE', str(tmp_path / 'state' / 'dashboard.json'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))


def test_forget_state_never_deletes_when_health_is_live(tmp_path, monkeypatch):
    '''Issue #1805: _forget_state() MUST NEVER delete state.json if dashboard is alive at /api/health.'''
    state_file = runs.state_file_path()
    runs.write_state_file({'pid': 99999, 'port': 8765, 'token': TOKEN, 'repos': [str(tmp_path)]})
    assert state_file.exists()

    # When /api/health responds with 200 and pid, _forget_state() must NOT delete state.json
    monkeypatch.setattr(cli, '_health', lambda port: {'status': 'ok', 'pid': 99999})
    cli._forget_state()
    assert state_file.exists(), 'state.json was unexpectedly deleted while dashboard was live'

    # When /api/health reports None (server is dead), _forget_state() deletes state.json
    monkeypatch.setattr(cli, '_health', lambda port: None)
    cli._forget_state()
    assert not state_file.exists(), 'state.json should be removed when dashboard is dead'


def test_second_start_reuses_live_process_and_preserves_token(tmp_path, monkeypatch, capsys):
    '''Issue #1805: A second start on an active port must reuse live process and keep original token.'''
    handle = server.start(repo_root=tmp_path, host='127.0.0.1', port=0, token=TOKEN)
    try:
        state_file = runs.state_file_path()
        runs.write_state_file({'pid': os.getpid(), 'port': handle.port, 'token': TOKEN, 'repos': [str(tmp_path)]})

        # Second call to _serve with matching port should succeed, return 0 and keep token
        rc = cli._serve(port=handle.port, repos=[str(tmp_path)], run_id=None, open_browser=False)
        assert rc == 0
        captured = capsys.readouterr()
        assert 'reusing the dashboard already running' in captured.err
        assert ('t=' + TOKEN) in captured.out

        # State file must still exist and still contain the original token
        assert state_file.exists()
        current_state = runs.read_state_file(state_file)
        assert current_state['token'] == TOKEN
        assert current_state['port'] == handle.port
    finally:
        handle.stop()


def test_status_checks_health_before_reporting_inactive(tmp_path, monkeypatch):
    '''Issue #1805: --status must check /api/health before reporting inactive.'''
    # Simulate state file where token was somehow missing or damaged
    state_file = runs.state_file_path()
    runs.write_state_file({'pid': 12345, 'port': 8765, 'token': '', 'repos': [str(tmp_path)]})

    # _live returns None because token is missing, but server on port 8765 is answering /api/health
    monkeypatch.setattr(cli, '_health', lambda port: {'status': 'ok', 'pid': 12345, 'uptime_s': 42.0, 'observed_runs': 3})

    payload = cli.status_payload()
    assert payload['running'] is True, 'status_payload must verify /api/health before reporting inactive'
    assert payload['port'] == 8765
    assert payload['pid'] == 12345

    # If /api/health also returns None, then it should report inactive
    monkeypatch.setattr(cli, '_health', lambda port: None)
    payload_dead = cli.status_payload()
    assert payload_dead['running'] is False


def test_holder_pid_ignores_tailscale_ip_and_time_wait(monkeypatch):
    '''Issue #1806: _holder_pid must verify bind to 127.0.0.1 and ignore other IPs or TIME_WAIT.'''
    # Mock /proc/net/tcp content:
    # Row 1: port 8765 on Tailscale IP 100.64.0.1 (hex 01004064:223D) in state 0A (LISTEN) -> should be ignored!
    # Row 2: port 8765 on 127.0.0.1 (hex 0100007F:223D) in state 06 (TIME_WAIT) -> should be ignored!
    fake_tcp = io.StringIO(
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        "   0: 01004064:223D 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 99999 1 00000000 100 0 0 10 0\n"
        "   1: 0100007F:223D 00000000:0000 06 00000000:00000000 00:00000000 00000000  1000        0 88888 1 00000000 100 0 0 10 0\n"
    )

    def fake_open(filename, *args, **kwargs):
        if filename == '/proc/net/tcp':
            return fake_tcp
        raise FileNotFoundError(filename)

    monkeypatch.setattr('builtins.open', fake_open)
    monkeypatch.setattr(sys, 'platform', 'linux')

    # Neither the Tailscale proxy on 100.64.0.1 nor the TIME_WAIT socket on 127.0.0.1 should be blamed!
    holder = cli._holder_pid(8765)
    assert holder is None, f'Unexpected holder blamed: {holder}'


def test_server_socket_uses_so_reuseaddr():
    '''Issue #1806: server socket must use SO_REUSEADDR (allow_reuse_address=True).'''
    assert server._Server.allow_reuse_address is True


def test_port_auto_resolves_to_free_port():
    '''Issue #1806: --port auto must be supported and resolve to port 0 (free port).'''
    assert cli._port('auto') == 0
    assert cli._port('AUTO') == 0


def test_port_collision_message_suggests_free_port(capsys, monkeypatch, tmp_path):
    '''Issue #1806: on port collision, error message suggests free port and --port auto.'''
    log = tmp_path / 'server.log'
    log.write_text('startup failed', encoding='utf-8')
    monkeypatch.setattr(cli, '_holder_pid', lambda port: 1234)
    monkeypatch.setattr(cli, 'find_free_port', lambda: 49152)

    rc = cli._start_failed(3, 8765, log)
    assert rc == 3
    captured = capsys.readouterr().err
    assert 'in use on 127.0.0.1 by pid 1234' in captured
    assert '--port 49152' in captured
    assert '--port auto' in captured
