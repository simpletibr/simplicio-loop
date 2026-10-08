'''Black-box tests for GET /api/coordination over real sockets (TDD red until the route exists).

Every server binds 127.0.0.1 on port 0 and is always stopped. Every socket has a hard timeout.
The server module is imported only inside fixtures and test functions.
'''
import http.client
import json

import pytest

TOKEN = 'coordination-token-0123'
AUTH = {'Authorization': 'Bearer ' + TOKEN}
TIMEOUT = 5
ROUTE = '/api/coordination'
COLUMN_KEYS = ['ready', 'claimed', 'running', 'verifying', 'done', 'blocked']
BACKLOG_PARTS = ('.simplicio-loop', 'orchestrator', 'backlog', 'backlog.jsonl')


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    return root


@pytest.fixture
def server_handle(repo):
    from simplicio_loop.dashboard import server
    handle = server.start(repo_root=repo, host='127.0.0.1', port=0, token=TOKEN)
    try:
        yield handle
    finally:
        handle.stop()


def _request(port, method, path, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=TIMEOUT)
    try:
        conn.request(method, path, headers=headers or {})
        resp = conn.getresponse()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
    finally:
        conn.close()


def _write_backlog(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(record) + '\n' for record in records), encoding='utf-8')
    return path


def _drain_records():
    return [
        {'kind': 'master', 'goal': 'Drain the coordination fixture'},
        {'kind': 'item', 'id': 'A', 'goal': 'first', 'status': 'done', 'priority': 1, 'depends_on': []},
        {'kind': 'item', 'id': 'B', 'goal': 'second', 'status': 'ready', 'priority': 2, 'depends_on': ['A']},
        {'kind': 'item', 'id': 'C', 'goal': 'third', 'status': 'claimed', 'priority': 3, 'depends_on': [],
         'worker': 'w1'},
        {'kind': 'item', 'id': 'D', 'goal': 'fourth', 'status': 'ready', 'priority': 4, 'depends_on': ['C']},
    ]


def test_coordination_without_token_is_401(server_handle):
    status, _, _ = _request(server_handle.port, 'GET', ROUTE)
    assert status == 401


def test_coordination_with_wrong_token_is_401(server_handle):
    status, _, _ = _request(server_handle.port, 'GET', ROUTE, {'Authorization': 'Bearer not-the-token'})
    assert status == 401


def test_coordination_with_token_on_repo_without_backlog_is_unverified(server_handle):
    status, headers, body = _request(server_handle.port, 'GET', ROUTE, AUTH)
    assert status == 200
    assert headers['content-type'].startswith('application/json')
    payload = json.loads(body)
    assert payload['status'] == 'UNVERIFIED'
    assert payload['reason']
    assert [column['key'] for column in payload['columns']] == COLUMN_KEYS
    assert all(column['count'] == 0 for column in payload['columns'])
    assert payload['items'] == []
    assert payload['edges'] == []
    assert payload['drain'] is None
    assert payload['slots'] == []


def test_coordination_reads_repo_backlog_and_is_measured(server_handle, repo):
    _write_backlog(repo.joinpath(*BACKLOG_PARTS), _drain_records())
    status, _, body = _request(server_handle.port, 'GET', ROUTE, AUTH)
    assert status == 200
    payload = json.loads(body)
    assert payload['status'] == 'MEASURED'
    assert isinstance(payload['revision'], int)
    counts = {column['key']: column['count'] for column in payload['columns']}
    assert counts == {'ready': 1, 'claimed': 1, 'running': 0, 'verifying': 0, 'done': 1, 'blocked': 1}
    items = {item['id']: item for item in payload['items']}
    assert sorted(items) == ['A', 'B', 'C', 'D']
    assert items['B']['column'] == 'ready' and items['B']['blocked_by'] == []
    assert items['D']['column'] == 'blocked' and items['D']['blocked_by'] == ['C']
    edges = {(edge['from'], edge['to']): edge['satisfied'] for edge in payload['edges']}
    assert edges == {('A', 'B'): True, ('C', 'D'): False}
    drain = payload['drain']
    assert (drain['total'], drain['done'], drain['remaining'], drain['blocked']) == (4, 1, 3, 1)


def test_backlog_env_var_overrides_repo_default_path(server_handle, repo, tmp_path, monkeypatch):
    elsewhere = _write_backlog(tmp_path / 'elsewhere' / 'backlog.jsonl', _drain_records())
    monkeypatch.setenv('SIMPLICIO_BACKLOG_FILE', str(elsewhere))
    status, _, body = _request(server_handle.port, 'GET', ROUTE, AUTH)
    assert status == 200
    assert json.loads(body)['status'] == 'MEASURED'


def test_backlog_env_var_pointing_at_missing_file_ignores_repo_backlog(server_handle, repo, tmp_path, monkeypatch):
    _write_backlog(repo.joinpath(*BACKLOG_PARTS), _drain_records())
    monkeypatch.setenv('SIMPLICIO_BACKLOG_FILE', str(tmp_path / 'missing.jsonl'))
    status, _, body = _request(server_handle.port, 'GET', ROUTE, AUTH)
    assert status == 200
    assert json.loads(body)['status'] == 'UNVERIFIED'


def test_coordination_is_read_only_post_is_405(server_handle):
    status, _, _ = _request(server_handle.port, 'POST', ROUTE, AUTH)
    assert status == 405
