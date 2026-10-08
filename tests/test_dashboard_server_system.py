'''System test for the dashboard server (TDD red): one real server, every read API, and the static shell.

The server module is imported inside the fixture so this file collects before the server exists.
'''
import http.client
import json

import pytest

TOKEN = 'system-token-9876'
AUTH = {'Authorization': 'Bearer ' + TOKEN}
CSP = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'"


@pytest.fixture
def dashboard(tmp_path):
    from simplicio_loop.dashboard import server
    from simplicio_loop.dashboard_events import load
    repo = tmp_path / 'repo'
    run_dir = repo / '.simplicio-loop' / 'loop-runs' / 'sys-run-1'
    run_dir.mkdir(parents=True)
    state = {'run_id': 'sys-run-1', 'status': 'running', 'phase': 'intake', 'percent': 25,
             'repo': str(repo), 'started_at': '2026-10-01T10:00:00Z',
             'updated_at': '2026-10-01T10:00:05Z'}
    (run_dir / 'state.json').write_text(json.dumps(state), encoding='utf-8')
    emitter = load()
    assert emitter is not None, 'dashboard_events emitter is missing'
    emitter.emit(run_dir, 'phase_entered', source='runner', phase='intake', strict=True)
    handle = server.start(repo_root=repo, host='127.0.0.1', port=0, token=TOKEN)
    try:
        yield handle
    finally:
        handle.stop()


def _get(port, path, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        conn.request('GET', path, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
    finally:
        conn.close()


def _json(handle, path):
    status, headers, body = _get(handle.port, path, AUTH)
    assert status == 200, (path, status, body[:200])
    assert headers['content-type'].startswith('application/json'), path
    return json.loads(body)


def test_every_read_api_returns_200_and_valid_json(dashboard):
    assert isinstance(_json(dashboard, '/api/health'), dict)
    runs = _json(dashboard, '/api/runs')
    assert 'sys-run-1' in [r['run_id'] for r in runs['runs']]
    detail = _json(dashboard, '/api/runs/sys-run-1')
    assert detail['run_id'] == 'sys-run-1'
    assert isinstance(_json(dashboard, '/api/queue'), (dict, list))
    agents = _json(dashboard, '/api/agents')
    tokens = _json(dashboard, '/api/tokens')
    assert 'UNVERIFIED' in json.dumps(agents)
    assert 'UNVERIFIED' in json.dumps(tokens)


def test_static_shell_is_200_with_csp(dashboard):
    status, headers, body = _get(dashboard.port, '/', AUTH)
    assert status == 200
    assert headers['content-security-policy'] == CSP
    assert b'<html' in body.lower()
