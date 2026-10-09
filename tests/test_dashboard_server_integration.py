'''Integration tests for the dashboard server over real sockets (TDD red).

Every server binds 127.0.0.1 on port 0 and is always stopped. Every socket has a hard timeout.
The server module is imported only inside fixtures and test functions.
'''
import http.client
import json
import math
import os
import subprocess
import sys
import threading
import time
from urllib.parse import quote

import pytest

TOKEN = 'integration-token-0123'
AUTH = {'Authorization': 'Bearer ' + TOKEN}
SSE = {**AUTH, 'Accept': 'text/event-stream'}
CSP = "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'"
TIMEOUT = 5


def _emitter():
    from simplicio_loop.dashboard_events import load
    module = load()
    assert module is not None, 'dashboard_events emitter is missing'
    return module


def _make_run(root, layout, run_id, emitted=0, **state):
    run_dir = root / '.simplicio-loop' / layout / run_id
    run_dir.mkdir(parents=True)
    body = {'run_id': run_id, 'status': 'running', 'phase': 'intake', 'percent': 10,
            'repo': str(root), 'started_at': '2026-10-01T10:00:00Z',
            'updated_at': '2026-10-01T10:00:00Z'}
    body.update(state)
    (run_dir / 'state.json').write_text(json.dumps(body), encoding='utf-8')
    emitter = _emitter()
    for _ in range(emitted):
        emitter.emit(run_dir, 'phase_entered', source='runner', phase='intake', strict=True)
    return run_dir


@pytest.fixture
def repo_root(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    _make_run(root, 'loop-runs', 'live-1', emitted=5, status='running', updated_at='2026-10-03T10:00:00Z')
    _make_run(root, 'orchestrator/runs', 'orch-1', emitted=3, status='done', updated_at='2026-10-02T10:00:00Z')
    _make_run(root, 'loop-runs', 'legacy-1', emitted=0, status='done', phase='done', updated_at='2026-10-01T10:00:00Z')
    (root / 'secret.txt').write_text('outside every run dir', encoding='utf-8')
    return root


@pytest.fixture
def server_handle(repo_root):
    from simplicio_loop.dashboard import server
    handle = server.start(repo_root=repo_root, host='127.0.0.1', port=0, token=TOKEN)
    try:
        yield handle
    finally:
        handle.stop()


def _get(port, path, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=TIMEOUT)
    try:
        conn.request('GET', path, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
    finally:
        conn.close()


def _request(port, method, path, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=TIMEOUT)
    try:
        conn.request(method, path, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def _collect_seqs(port, path, headers, want, timeout=10):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    seqs = []
    try:
        conn.request('GET', path, headers=headers)
        resp = conn.getresponse()
        assert resp.status == 200, resp.status
        deadline = time.monotonic() + timeout
        named = False
        while len(seqs) < want and time.monotonic() < deadline:
            line = resp.readline()
            if not line:
                break
            if line.startswith(b'event:'):
                named = True  # a named frame (alert_*) is not a dashboard event, as in EventSource
            elif line in (b'\n', b'\r\n'):
                named = False
            elif line.startswith(b'data:') and not named:
                seqs.append(json.loads(line[5:])['seq'])
        return seqs
    finally:
        conn.close()


def test_sse_p95_latency_under_500ms_after_quiet_gap(server_handle, repo_root):
    emitter = _emitter()
    run_dir = repo_root / '.simplicio-loop' / 'loop-runs' / 'live-1'
    received = {}

    def reader(resp):
        named = False
        try:
            while True:
                line = resp.readline()
                if not line:
                    return
                if line.startswith(b'event:'):
                    named = True  # a named frame (alert_*) is not a dashboard event, as in EventSource
                elif line in (b'\n', b'\r\n'):
                    named = False
                elif line.startswith(b'data:') and not named:
                    received.setdefault(json.loads(line[5:])['seq'], time.monotonic())
        except Exception:
            return  # the test closes the socket during teardown

    conn = http.client.HTTPConnection('127.0.0.1', server_handle.port, timeout=10)
    try:
        conn.request('GET', '/api/runs/live-1/events', headers=SSE)
        resp = conn.getresponse()
        assert resp.status == 200, resp.status
        threading.Thread(target=reader, args=(resp,), daemon=True).start()
        latencies = []
        for _ in range(5):
            time.sleep(3)  # quiet gap before each append
            sent = time.monotonic()
            evt = emitter.emit(run_dir, 'phase_entered', source='runner', phase='intake', strict=True)
            while evt['seq'] not in received and time.monotonic() < sent + 2:
                time.sleep(0.005)
            assert evt['seq'] in received, 'event %s never reached the client' % evt['seq']
            latencies.append(received[evt['seq']] - sent)
    finally:
        conn.close()
    ordered = sorted(latencies)
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    assert p95 < 0.5, latencies


def test_reconnect_with_last_event_id_loses_and_duplicates_nothing(server_handle, repo_root):
    run_dir = _make_run(repo_root, 'loop-runs', 'live-2', emitted=100)
    path = '/api/runs/live-2/events'
    first = _collect_seqs(server_handle.port, path, SSE, 100)
    assert first == list(range(1, 101))
    emitter = _emitter()
    for _ in range(100):
        emitter.emit(run_dir, 'phase_entered', source='runner', phase='intake', strict=True)
    second = _collect_seqs(server_handle.port, path, {**SSE, 'Last-Event-ID': '100'}, 100)
    assert second == list(range(101, 201))
    assert first + second == list(range(1, 201))


def test_last_event_id_header_beats_since_seq_query(server_handle, repo_root):
    _make_run(repo_root, 'loop-runs', 'live-3', emitted=10)
    seqs = _collect_seqs(server_handle.port, '/api/runs/live-3/events?since_seq=0', {**SSE, 'Last-Event-ID': '7'}, 3)
    assert seqs == [8, 9, 10]


@pytest.mark.parametrize('cursor', ['abc', '1.5'])
def test_garbage_last_event_id_is_400(server_handle, cursor):
    status, _, _ = _get(server_handle.port, '/api/runs/live-1/events', {**SSE, 'Last-Event-ID': cursor})
    assert status == 400


def test_garbage_since_seq_query_is_400(server_handle):
    status, _, _ = _get(server_handle.port, '/api/runs/live-1/events?since_seq=abc', AUTH)
    assert status == 400


@pytest.mark.parametrize('artifact', ['..%2f..%2fsecret.txt', '%2e%2e%2f%2e%2e%2fsecret.txt', 'logs%5c..%5c..%5csecret.txt', '%2e%2e'])
def test_artifact_path_traversal_is_403(server_handle, artifact):
    status, _, _ = _get(server_handle.port, '/api/runs/live-1/artifacts/' + artifact, AUTH)
    assert status == 403


def test_foreign_origin_is_403(server_handle):
    status, _, _ = _get(server_handle.port, '/api/runs', {**AUTH, 'Origin': 'https://evil.example'})
    assert status == 403


def test_foreign_host_is_403(server_handle):
    status, _, _ = _get(server_handle.port, '/api/runs', {**AUTH, 'Host': 'evil.example'})
    assert status == 403


@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Bearer wrong'}, {'X-Simplicio-Token': 'wrong'}])
def test_missing_or_wrong_token_is_401(server_handle, headers):
    status, _, _ = _get(server_handle.port, '/api/runs', headers)
    assert status == 401


def test_wrong_query_token_is_401(server_handle):
    status, _, _ = _get(server_handle.port, '/api/runs?t=wrong')
    assert status == 401


@pytest.mark.parametrize('method', ['POST', 'PUT', 'DELETE'])
def test_mutating_methods_are_405(server_handle, method):
    status, _ = _request(server_handle.port, method, '/api/runs', AUTH)
    assert status == 405


def test_oversize_artifact_is_413(server_handle, repo_root):
    from simplicio_loop.dashboard import runs
    big = repo_root / '.simplicio-loop' / 'loop-runs' / 'live-1' / 'big.log'
    with open(big, 'wb') as fh:
        fh.truncate(runs.MAX_ARTIFACT_BYTES + 1)
    status, _, _ = _get(server_handle.port, '/api/runs/live-1/artifacts/big.log', AUTH)
    assert status == 413


def test_artifact_is_redacted_end_to_end(server_handle, repo_root):
    logs = repo_root / '.simplicio-loop' / 'loop-runs' / 'live-1' / 'logs'
    logs.mkdir()
    (logs / 'out.txt').write_text(
        'Authorization: Bearer abc123TOKENxyz\n'
        'sk-abcdefghijklmnopqrstuvwx\n'
        'ghp_abcdefghijklmnopqrstuvwxyz0123456789\n'
        'contact dev@example.com\n'
        'api_key=supersecretvalue\n'
        'plain line kept\n', encoding='utf-8')
    status, _, body = _get(server_handle.port, '/api/runs/live-1/artifacts/logs/out.txt', AUTH)
    assert status == 200
    text = body.decode('utf-8')
    for secret in ['abc123TOKENxyz', 'sk-abcdefghijklmnopqrstuvwx', 'ghp_abcdefghijklmnopqrstuvwxyz0123456789', 'dev@example.com', 'supersecretvalue']:
        assert secret not in text
    assert 'plain line kept' in text


def test_runs_endpoint_filters_status_repo_and_since(server_handle, repo_root):
    def ids(query):
        status, _, body = _get(server_handle.port, '/api/runs' + query, AUTH)
        assert status == 200
        return [r['run_id'] for r in json.loads(body)['runs']]

    assert ids('') == ['live-1', 'orch-1', 'legacy-1']
    assert ids('?status=done') == ['orch-1', 'legacy-1']
    assert ids('?status=running') == ['live-1']
    assert ids('?repo=' + quote(str(repo_root), safe='')) == ['live-1', 'orch-1', 'legacy-1']
    assert ids('?repo=' + quote('/nowhere', safe='')) == []
    assert ids('?since=2026-10-02T00:00:00Z') == ['live-1', 'orch-1']


def test_second_server_on_same_port_exits_3_and_names_holder(server_handle, repo_root):
    result = subprocess.run(
        [sys.executable, '-m', 'simplicio_loop.dashboard.server', '--port', str(server_handle.port)],
        cwd=str(repo_root), capture_output=True, text=True, timeout=30)
    output = result.stdout + result.stderr
    assert result.returncode == 3, output
    assert str(server_handle.port) in output
    assert str(os.getpid()) in output


def test_selftest_exits_zero():
    result = subprocess.run(
        [sys.executable, '-m', 'simplicio_loop.dashboard.server', '--selftest'],
        capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_budget_route_reports_limits_usage_and_a_labelled_projection(repo_root, server_handle):
    run_dir = repo_root / '.simplicio-loop' / 'loop-runs' / 'live-1'
    (run_dir / 'task-contract.json').write_text(json.dumps(
        {'tasks': [{'routing': {'budget': {'tokens': 600, 'usd': None, 'seconds': None}}}]}), encoding='utf-8')
    emitter = _emitter()
    emitter.emit(run_dir, 'phase_entered', source='runner', phase='executing', strict=True)
    emitter.emit(run_dir, 'token_usage', source='worker', phase='executing',
                 payload={'model': 'm', 'input_tokens': 300, 'output_tokens': 0}, strict=True)
    status, _, body = _get(server_handle.port, '/api/runs/live-1/budget', AUTH)
    assert status == 200
    data = json.loads(body)
    assert data['rows']['tokens']['state'] == 'PROJECTED_OVER'
    assert data['rows']['tokens']['proof_kind'] == 'estimado'
    assert data['usage']['by_phase'] == {'executing': 300}
    assert data['rows']['usd']['state'] == 'UNVERIFIED'


def test_budget_route_for_an_unknown_run_is_404(server_handle):
    status, _, _ = _get(server_handle.port, '/api/runs/nope/budget', AUTH)
    assert status == 404


def test_extras_route_reports_the_run_extras_and_404s_an_unknown_run(repo_root, server_handle):
    run_dir = repo_root / '.simplicio-loop' / 'loop-runs' / 'live-1'
    (run_dir / 'task-contract.json').write_text(json.dumps(
        {'tasks': [{'id': 't1', 'title': 'Budget panel'}]}), encoding='utf-8')
    emitter = _emitter()
    emitter.emit(run_dir, 'test_result', source='worker', payload={'command': 'pytest -q', 'tool': 'pytest'},
                 strict=True)
    emitter.emit(run_dir, 'token_usage', source='worker', lane='lane-a',
                 payload={'model': 'model-a', 'input_tokens': 300, 'output_tokens': 4}, strict=True)
    status, _, body = _get(server_handle.port, '/api/runs/live-1/extras', AUTH)
    assert status == 200
    data = json.loads(body)
    assert data['schema'] == 'simplicio.dashboard-extras/v1'
    assert data['last_command']['command'] == 'pytest -q' and data['last_command']['kind'] == 'test_result'
    assert data['tasks'] == [{'task_id': 't1', 'title': 'Budget panel'}]
    assert data['models'] == [{'lane': 'lane-a', 'model': 'model-a', 'input_tokens': 300, 'output_tokens': 4}]
    assert data['heartbeat'] == {'state': 'UNVERIFIED', 'reason': 'nenhuma lane com lease_id registrado', 'lanes': []}
    status, _, _ = _get(server_handle.port, '/api/runs/nope/extras', AUTH)
    assert status == 404

def test_history_endpoint_returns_records_filters_and_rejects_bad_values(server_handle, repo_root):
    def get(query):
        status, _, body = _get(server_handle.port, '/api/history' + query, AUTH)
        return status, json.loads(body)

    status, payload = get('')
    assert status == 200
    assert [r['run_id'] for r in payload['history']] == ['orch-1', 'live-1', 'legacy-1']  # same started_at: run_id desc
    assert all(r['schema'] == 'simplicio.dashboard-history/v1' for r in payload['history'])
    assert [r['run_id'] for r in get('?verdict=RUNNING')[1]['history']] == ['live-1']
    assert len(get('?limit=1')[1]['history']) == 1
    assert get('?verdict=NOPE')[0] == 400
    assert get('?since=yesterday')[0] == 400
    assert get('?min_cost_usd=abc')[0] == 400
    status, _, _ = _get(server_handle.port, '/api/history', {})
    assert status == 401


def test_budget_route_carries_the_comparison_with_the_previous_runs(repo_root, server_handle):
    status, _, body = _get(server_handle.port, '/api/runs/live-1/budget', AUTH)
    assert status == 200
    comparison = json.loads(body)['comparison']
    assert comparison['runs'] == 2  # orch-1 and legacy-1; the current run is skipped
    assert set(comparison['fields']) == {'duration_s', 'tokens', 'cost_usd', 'iterations'}
    assert comparison['fields']['tokens']['state'] == 'UNVERIFIED'

def test_history_compare_trends_heatmap_and_csv_routes(server_handle, repo_root):
    def get(path):
        status, headers, body = _get(server_handle.port, path, AUTH)
        return status, headers, body

    status, _, body = get('/api/history/compare?a=orch-1&b=live-1')
    assert status == 200
    cmp = json.loads(body)
    assert (cmp['a'], cmp['b']) == ('orch-1', 'live-1') and 'metrics' in cmp
    assert get('/api/history/compare?a=orch-1&b=nope')[0] == 404
    assert get('/api/history/compare?a=orch-1')[0] == 404
    status, _, body = get('/api/history/trends?bucket=month')
    assert status == 200 and json.loads(body)['trends'][0]['bucket'] == '2026-10'
    assert get('/api/history/trends?bucket=year')[0] == 400
    status, _, body = get('/api/history/heatmap')
    grid = json.loads(body)['heatmap']
    assert status == 200 and len(grid) == 7 and sum(map(sum, grid)) == 3
    status, headers, body = get('/api/history?format=csv')
    assert status == 200 and headers['content-type'].startswith('text/csv')
    lines = body.decode('utf-8').splitlines()
    assert lines[0].startswith('run_id,repo,verdict') and len(lines) == 4
    assert get('/api/history/other')[0] == 404


def test_history_lessons_route(server_handle, repo_root):
    base = repo_root / '.simplicio-loop' / 'orchestrator'
    base.mkdir(parents=True, exist_ok=True)
    (base / 'lessons.jsonl').write_text(json.dumps({'schema': 'simplicio.lesson/v1', 'fingerprint': 'f', 'lesson': 'keep gates small',
                                                    'hit_count': 2, 'last_seen': '2026-10-01T00:00:00Z'}) + '\n', encoding='utf-8')
    status, _, body = _get(server_handle.port, '/api/history/lessons', AUTH)
    assert status == 200 and json.loads(body)['lessons'][0]['lesson'] == 'keep gates small'
