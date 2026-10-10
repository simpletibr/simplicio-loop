'''Integration tests of ``GET /api/runs/<id>/langfuse`` over a real loopback server (issue #1610).

The route answers from local files only: with the Langfuse host unreachable the panel and its other routes still answer, and no
key of the exporter ever appears in a body.
'''
from __future__ import annotations

import http.client
import json
import time

import pytest

from tests.test_dashboard_langfuse_view_unit import (OFF, PUBLIC, RUN_ID, SECRET, T0, TRACE_ID, _report, export, lf_dir, make_repo, on,
                                                     outbox)

TOKEN = 'langfuse-route-token-0123'
AUTH = {'Authorization': 'Bearer ' + TOKEN}
TIMEOUT = 5


@pytest.fixture
def serve(tmp_path):
    from simplicio_loop.dashboard import server
    handles = []

    def start(toml, **kwargs):
        ref = make_repo(tmp_path, toml, **kwargs)
        handle = server.start(repo_root=ref['repo'], host='127.0.0.1', port=0, token=TOKEN)
        handles.append(handle)
        return ref, handle.port

    yield start
    for handle in handles:
        handle.stop()


def _get(port, path, headers=AUTH):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=TIMEOUT)
    try:
        conn.request('GET', path, headers=headers)
        reply = conn.getresponse()
        return reply.status, reply.read(), reply
    finally:
        conn.close()


def test_off_answers_only_the_chip(serve):
    _, port = serve(None)
    status, body, reply = _get(port, '/api/runs/%s/langfuse' % RUN_ID)
    assert status == 200 and json.loads(body) == OFF
    assert reply.getheader('Content-Type').startswith('application/json')
    assert reply.getheader('Cache-Control') == 'no-store'


def test_enabled_answers_the_trace_link_chip_and_queue(serve):
    ref, port = serve(on(), report=_report(), gates={'tests': True})
    outbox(ref).enqueue('traces', {'x': 1})
    status, body, _ = _get(port, '/api/runs/%s/langfuse' % RUN_ID)
    data = json.loads(body)
    assert status == 200
    assert data['trace']['url'] == 'https://langfuse.example.test/trace/%s' % TRACE_ID
    assert data['queue'] == 1 and data['chip']['state'] in ('sending', 'late')


def test_the_route_needs_the_token_and_a_known_run(serve):
    _, port = serve(on())
    assert _get(port, '/api/runs/%s/langfuse' % RUN_ID, headers={})[0] == 401
    assert _get(port, '/api/runs/no-such-run/langfuse')[0] == 404
    assert _get(port, '/api/runs/%s/langfuse?x=1' % RUN_ID)[0] == 200


def test_with_langfuse_down_the_panel_still_answers_fast_and_without_keys(serve, monkeypatch):
    monkeypatch.setenv('LANGFUSE_SECRET_KEY', SECRET)
    monkeypatch.setenv('LANGFUSE_PUBLIC_KEY', PUBLIC)
    ref, port = serve(on('http://127.0.0.1:1'), report=_report(), gates={'tests': True})  # nothing listens on port 1
    lf_dir(ref).mkdir(parents=True, exist_ok=True)
    (lf_dir(ref) / 'credentials.json').write_text(json.dumps({'public_key': PUBLIC, 'secret_key': SECRET}), encoding='utf-8')
    export(ref, now=float(T0 + 600))
    outbox(ref).enqueue('traces', {'x': 1})
    started = time.monotonic()
    status, body, _ = _get(port, '/api/runs/%s/langfuse' % RUN_ID)
    assert status == 200 and time.monotonic() - started < 3
    assert SECRET not in body.decode() and PUBLIC not in body.decode()
    assert json.loads(body)['trace']['url'] == 'http://127.0.0.1:1/trace/%s' % TRACE_ID
    for path in ('/api/health', '/api/runs', '/api/runs/%s' % RUN_ID):
        assert _get(port, path)[0] == 200


def test_a_corrupt_exporter_state_is_an_error_chip_not_a_server_error(serve):
    ref, port = serve(on(), report=_report(), gates={'tests': True})
    lf_dir(ref).mkdir(parents=True, exist_ok=True)
    (lf_dir(ref) / 'ledger.json').write_text('{broken', encoding='utf-8')
    status, body, _ = _get(port, '/api/runs/%s/langfuse' % RUN_ID)
    assert status == 200 and json.loads(body)['chip']['state'] == 'error'
