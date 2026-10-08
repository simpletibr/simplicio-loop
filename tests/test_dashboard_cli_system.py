'''System tests for the `simplicio-loop dashboard` CLI (issue #1401, slice 3b) - TDD red.

Each test runs the real CLI as a subprocess: python -m simplicio_loop.cli, the module behind the
simplicio-loop console script. Servers bind 127.0.0.1 only, and every test stops what it started
in a finally block. The state file lives under tmp_path.
'''
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

REPO = Path(__file__).resolve().parents[1]
ENTRY = 'simplicio_loop.cli'
SCHEMA = REPO / 'contracts' / 'dashboard-status' / 'v1' / 'schema.json'
TIMEOUT = 60
HTTP_TIMEOUT = 5


def _env(tmp_path):
    env = dict(os.environ)
    env['PYTHONPATH'] = str(REPO)
    env['SIMPLICIO_DASHBOARD_STATE'] = str(tmp_path / 'state' / 'dashboard.json')
    env['HOME'] = str(tmp_path / 'home')
    for name in ('DISPLAY', 'WAYLAND_DISPLAY', 'SIMPLICIO_MONITOR_PORT'):
        env.pop(name, None)
    return env


def _show(proc):
    return '\n'.join(['rc=%s' % proc.returncode, 'stdout:', proc.stdout, 'stderr:', proc.stderr])


def _run(env, command, *args):
    return subprocess.run([sys.executable, '-m', ENTRY, command, *args], env=env, cwd=str(REPO),
                          capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)


def _dashboard(env, *args):
    return _run(env, 'dashboard', *args)


def _start(env, repo):
    return _dashboard(env, '--repo', str(repo), '--port', '0', '--no-browser')


def _stop(env):
    return _dashboard(env, '--stop')


def _json(proc):
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise AssertionError('stdout is not JSON (%s)\n%s' % (exc, _show(proc)))


def _url_from(text):
    for word in text.split():
        if word.startswith('http://127.0.0.1:'):
            return word
    return None


def _get(port, path, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=HTTP_TIMEOUT)
    try:
        conn.request('GET', path, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def _repo_with_run(tmp_path):
    from simplicio_loop.dashboard_events import load
    emitter = load()
    assert emitter is not None, 'dashboard_events emitter is missing'
    root = tmp_path / 'repo'
    run_dir = root / '.simplicio-loop' / 'loop-runs' / 'live-1'
    run_dir.mkdir(parents=True)
    body = {'run_id': 'live-1', 'status': 'running', 'phase': 'verify', 'percent': 42,
            'repo': str(root), 'started_at': '2026-10-03T10:00:00Z', 'updated_at': '2026-10-03T10:00:00Z'}
    (run_dir / 'state.json').write_text(json.dumps(body), encoding='utf-8')
    (run_dir / 'manifest.json').write_text(json.dumps({'schema': 'simplicio.run-manifest/v1', 'run_id': 'live-1', 'repo': str(root)}), encoding='utf-8')
    emitter.emit(run_dir, 'phase_entered', source='runner', phase='intake', strict=True)
    return root


def test_start_prints_a_tokenized_loopback_url(tmp_path):
    env = _env(tmp_path)
    repo = _repo_with_run(tmp_path)
    try:
        proc = _start(env, repo)
    finally:
        _stop(env)
    assert proc.returncode == 0, _show(proc)
    assert 'http://127.0.0.1:' in proc.stdout and '?t=' in proc.stdout, _show(proc)


def test_second_start_reuses_the_running_dashboard(tmp_path):
    env = _env(tmp_path)
    repo = _repo_with_run(tmp_path)
    try:
        first = _start(env, repo)
        assert first.returncode == 0, _show(first)
        second = _start(env, repo)
    finally:
        _stop(env)
    assert second.returncode == 0, _show(second)
    assert 'reus' in (second.stdout + second.stderr).lower(), _show(second)


def test_status_matches_the_schema_and_never_prints_a_token(tmp_path):
    import jsonschema
    env = _env(tmp_path)
    repo = _repo_with_run(tmp_path)
    try:
        start = _start(env, repo)
        assert start.returncode == 0, _show(start)
        status = _dashboard(env, '--status')
    finally:
        _stop(env)
    assert status.returncode == 0, _show(status)
    assert 't=' not in status.stdout, _show(status)
    payload = _json(status)
    assert payload['running'] is True, _show(status)
    jsonschema.validate(payload, json.loads(SCHEMA.read_text(encoding='utf-8')))


def test_printed_url_serves_the_shell_and_the_runs_api(tmp_path):
    env = _env(tmp_path)
    repo = _repo_with_run(tmp_path)
    try:
        start = _start(env, repo)
        assert start.returncode == 0, _show(start)
        url = _url_from(start.stdout)
        assert url is not None and '?t=' in url, _show(start)
        parts = urlsplit(url)
        token = parse_qs(parts.query).get('t', [''])[0]
        page_status, _ = _get(parts.port, '/?t=' + token)
        api_status, body = _get(parts.port, '/api/runs', {'Authorization': 'Bearer ' + token})
    finally:
        _stop(env)
    assert page_status == 200, page_status
    assert api_status == 200, api_status
    assert 'runs' in json.loads(body), body[:200]


def test_stop_then_status_reports_not_running(tmp_path):
    env = _env(tmp_path)
    repo = _repo_with_run(tmp_path)
    try:
        start = _start(env, repo)
        assert start.returncode == 0, _show(start)
        stop = _stop(env)
        assert stop.returncode == 0, _show(stop)
        status = _dashboard(env, '--status')
    finally:
        _stop(env)
    assert status.returncode == 0, _show(status)
    assert _json(status)['running'] is False, _show(status)


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _wait_listening(port, limit=15.0):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError('nothing listens on 127.0.0.1:%d' % port)


def test_port_clash_exits_3_and_names_the_holder_pid(tmp_path):
    port = _free_port()
    holder = subprocess.Popen([sys.executable, '-m', 'http.server', str(port), '--bind', '127.0.0.1'],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    env = _env(tmp_path)
    repo = _repo_with_run(tmp_path)
    try:
        _wait_listening(port)
        proc = _dashboard(env, '--port', str(port), '--repo', str(repo), '--no-browser')
    finally:
        holder.kill()
        holder.wait(timeout=10)
        _stop(env)
    assert proc.returncode == 3, _show(proc)
    assert str(holder.pid) in proc.stdout + proc.stderr, _show(proc)


def test_snapshot_writes_a_file_and_starts_no_server(tmp_path):
    env = _env(tmp_path)
    repo = _repo_with_run(tmp_path)
    out = tmp_path / 'dashboard.html'
    try:
        proc = _dashboard(env, '--snapshot', str(out), '--repo', str(repo))
        state_written = Path(env['SIMPLICIO_DASHBOARD_STATE']).exists()
    finally:
        _stop(env)
    assert proc.returncode == 0, _show(proc)
    assert out.is_file(), _show(proc)
    assert not state_written, 'the snapshot run left a dashboard state file behind'


def test_tui_prints_something_when_stdout_is_a_pipe(tmp_path):
    env = _env(tmp_path)
    repo = _repo_with_run(tmp_path)
    try:
        proc = _dashboard(env, '--tui', '--repo', str(repo))
    finally:
        _stop(env)
    assert proc.returncode == 0, _show(proc)
    assert proc.stdout.strip(), _show(proc)


def test_progress_writes_the_panel_link_to_stderr_while_a_server_is_up(tmp_path):
    env = _env(tmp_path)
    repo = _repo_with_run(tmp_path)
    try:
        start = _start(env, repo)
        assert start.returncode == 0, _show(start)
        proc = _run(env, 'progress', 'live-1', '--repo', str(repo), '--once')
    finally:
        _stop(env)
    assert proc.returncode == 0, _show(proc)
    assert '?t=' in proc.stderr, _show(proc)


def test_progress_json_stays_parseable_with_empty_stderr(tmp_path):
    env = _env(tmp_path)
    repo = _repo_with_run(tmp_path)
    try:
        start = _start(env, repo)
        assert start.returncode == 0, _show(start)
        proc = _run(env, 'progress', 'live-1', '--repo', str(repo), '--format', 'json', '--once')
    finally:
        _stop(env)
    assert proc.returncode == 0, _show(proc)
    _json(proc)
    assert proc.stderr == '', _show(proc)


def test_progress_prints_no_panel_link_when_no_server_is_up(tmp_path):
    env = _env(tmp_path)
    repo = _repo_with_run(tmp_path)
    try:
        proc = _run(env, 'progress', 'live-1', '--repo', str(repo), '--once')
    finally:
        _stop(env)
    assert proc.returncode == 0, _show(proc)
    assert '?t=' not in proc.stdout + proc.stderr, _show(proc)
    assert 'http://127.0.0.1:' not in proc.stdout + proc.stderr, _show(proc)


def _pty_session(env, repo, key):
    '''Run `dashboard --tui` on a pseudo-terminal, send ``key`` once it drew, return (rc, output).'''
    import pty
    import select
    import signal as sig
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(str(REPO))
        os.execve(sys.executable, [sys.executable, '-m', ENTRY, 'dashboard', '--tui', '--repo', str(repo)], env)
    out, sent, deadline = b'', False, time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if ready:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
            if not sent and b'quit' in out:
                os.write(fd, key)
                sent = True
            done, status = os.waitpid(pid, os.WNOHANG)
            if done:
                return os.waitstatus_to_exitcode(status), out.decode('utf-8', 'replace')
        for _ in range(50):  # the pty closed (the child exited): collect it
            done, status = os.waitpid(pid, os.WNOHANG)
            if done:
                return os.waitstatus_to_exitcode(status), out.decode('utf-8', 'replace')
            time.sleep(0.1)
        os.kill(pid, sig.SIGKILL)
        os.waitpid(pid, 0)
        raise AssertionError('tui did not exit after %r; output:\n%s' % (key, out.decode('utf-8', 'replace')))
    finally:
        os.close(fd)


@pytest.mark.skipif(os.name != 'posix', reason='pty is POSIX only')
@pytest.mark.parametrize('key', [b'q', b'\x03'], ids=['q', 'ctrl-c'])
def test_tui_on_a_real_tty_starts_shows_status_and_exits_cleanly(tmp_path, key):
    env = _env(tmp_path)
    env['TERM'] = 'xterm'
    repo = _repo_with_run(tmp_path)
    rc, out = _pty_session(env, repo, key)
    assert rc == 0, out
    assert 'quit' in out
    assert '\x1b[?25h' in out, 'the cursor was not restored'
