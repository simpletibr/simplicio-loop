'''Security review of the Simplicio Live server over real sockets (TDD red first).

Every server binds 127.0.0.1 on port 0 and is always stopped. Every socket has a hard timeout.
Requests are raw http.client or socket exchanges so the wire bytes are what gets checked.
'''
import hashlib
import http.client
import json
import socket
import time
from pathlib import Path

import pytest

TOKEN = 'review-token-0123456789abcdef'
AUTH = {'Authorization': 'Bearer ' + TOKEN}
TIMEOUT = 5
RUN_ID = 'live-1'
REPO_ROOT_MARKER = 'OUTSIDE-MARKER'
DASHBOARD_EVENT = 'simplicio.dashboard-event/v1'

# Realistic but fake secret shapes. Each must never reach any response body or header.
SK_OPENAI = 'sk-Abc123Def456Ghi789Jkl012'
SK_ANTHROPIC = 'sk-ant-api03-Zq9Xw8Vt7Ru6Sp5Qo4Nm3Lk2'
GHP = 'ghp_Abcdefghijklmnopqrstuvwxyz0123456789'
GITHUB_PAT = 'github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJ'
AKIA = 'AKIAIOSFODNN7EXAMPLE'
AWS_SECRET = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'
BEARER_VALUE = 'eyJhbGciOiJIUzI1NiJ9.payloadpart123'
PRIVATE_BODY = 'MIIEpAIBAAKCAQEAexamplebodyonly'
PASSWORD_VALUE = 'hunter2'
TOKEN_VALUE = 'abc123def4xyz'
NESTED_KEY_VALUE = 'plain-looking-but-sensitive'
SECRET_MARKERS = (SK_OPENAI, SK_ANTHROPIC, GHP, GITHUB_PAT, AKIA, AWS_SECRET, BEARER_VALUE,
                  PRIVATE_BODY, PASSWORD_VALUE, TOKEN_VALUE, NESTED_KEY_VALUE)
SECRET_TEXT = '\n'.join([
    'openai ' + SK_OPENAI,
    'anthropic ' + SK_ANTHROPIC,
    'github ' + GHP,
    'pat ' + GITHUB_PAT,
    'aws ' + AKIA,
    'aws_secret_access_key = ' + AWS_SECRET,
    'Authorization: Bearer ' + BEARER_VALUE,
    '-----BEGIN PRIVATE KEY-----',
    PRIVATE_BODY,
    '-----END PRIVATE KEY-----',
    'password=' + PASSWORD_VALUE,
    'token=' + TOKEN_VALUE,
])


def _server():
    from simplicio_loop.dashboard import server
    return server


def _event(seq, kind='phase_entered', phase='executing', payload=None):
    return json.dumps({'schema': DASHBOARD_EVENT, 'seq': seq, 'ts': '2026-10-01T10:00:00.000Z',
                       'kind': kind, 'phase': phase, 'source': 'runner', 'payload': payload or {}})


def _make_run(root, layout='loop-runs', run_id=RUN_ID, state=None):
    run_dir = root / '.simplicio-loop' / layout / run_id
    run_dir.mkdir(parents=True)
    body = {'run_id': run_id, 'status': 'running', 'phase': 'executing', 'percent': 10,
            'repo': str(root), 'started_at': '2026-10-01T10:00:00Z',
            'updated_at': '2026-10-03T10:00:00Z'}
    body.update(state or {})
    (run_dir / 'state.json').write_text(json.dumps(body), encoding='utf-8')
    return run_dir


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    run = _make_run(root)
    (run / 'events.jsonl').write_text(_event(1) + '\n' + _event(2) + '\n', encoding='utf-8')
    (root / 'secret.txt').write_text('outside every run dir ' + REPO_ROOT_MARKER, encoding='utf-8')
    return root


@pytest.fixture
def run_dir(repo):
    return repo / '.simplicio-loop' / 'loop-runs' / RUN_ID


@pytest.fixture
def handle(repo):
    handle = _server().start(repo, host='127.0.0.1', port=0, token=TOKEN, heartbeat_seconds=0.2)
    try:
        yield handle
    finally:
        handle.stop()


def _request(port, method, path, headers=None):
    '''(status, lower-cased headers, body bytes) for one request with a hard timeout.'''
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=TIMEOUT)
    try:
        conn.request(method, path, headers=dict(headers or {}))
        resp = conn.getresponse()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
    finally:
        conn.close()


def _raw(port, payload: bytes) -> bytes:
    '''Send raw bytes and read until the server closes: the exact bytes on the wire.'''
    with socket.create_connection(('127.0.0.1', port), timeout=TIMEOUT) as sock:
        sock.sendall(payload)
        chunks = []
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
    return b''.join(chunks)


def _split(wire: bytes):
    head, _, body = wire.partition(b'\r\n\r\n')
    lines = head.decode('latin-1').split('\r\n')
    status = int(lines[0].split(' ')[1])
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(':')
        headers[name.strip().lower()] = value.strip()
    return status, headers, body


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()}


def _sse_text(port, path, headers, min_data=1, timeout=TIMEOUT):
    '''Read the start of an SSE stream until ``min_data`` data lines (or the deadline), then close.'''
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    text = []
    try:
        conn.request('GET', path, headers=dict(headers))
        resp = conn.getresponse()
        assert resp.status == 200, resp.status
        deadline = time.monotonic() + timeout
        count = 0
        while count < min_data and time.monotonic() < deadline:
            line = resp.readline().decode('utf-8', 'replace')
            if not line:
                break
            text.append(line)
            if line.startswith('data:'):
                count += 1
        return ''.join(text)
    finally:
        conn.close()


def _assert_no_secret(body: bytes):
    text = body.decode('utf-8', 'replace')
    for marker in SECRET_MARKERS:
        assert marker not in text, 'secret leaked: %s' % marker[:12]
    assert '-----BEGIN PRIVATE KEY-----' not in text


# --- 1. CSP and hardening headers -----------------------------------------------------------

def _directives(csp: str) -> dict:
    out = {}
    for part in csp.split(';'):
        bits = part.split()
        if bits:
            out[bits[0]] = bits[1:]
    return out


def test_csp_has_hardening_directives_and_no_unsafe_keywords(handle):
    csp = _request(handle.port, 'GET', '/', {'Host': '127.0.0.1:%d' % handle.port,
                                              'Authorization': 'Bearer ' + TOKEN})[1]['content-security-policy']
    directives = _directives(csp)
    assert directives['base-uri'] == ["'none'"]
    assert directives['form-action'] == ["'none'"]
    assert directives['object-src'] == ["'none'"]
    assert directives['frame-ancestors'] == ["'none'"]
    assert directives['default-src'] == ["'none'"]
    assert "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp and 'unsafe-hashes' not in csp
    assert 'data:' not in csp and 'blob:' not in csp and '*' not in csp


@pytest.mark.parametrize('path, auth', [
    ('/', AUTH), ('/api/health', {}), ('/api/runs', AUTH), ('/api/runs', {}),
    ('/static/live/app.js', {}), ('/static/nope.js', {}),
])
def test_every_response_carries_the_framing_and_isolation_headers(handle, path, auth):
    headers = {'Host': '127.0.0.1:%d' % handle.port, **auth}
    _, got, _ = _request(handle.port, 'GET', path, headers)
    assert got['x-frame-options'] == 'DENY'
    assert got['cross-origin-resource-policy'] == 'same-origin'
    assert got['cross-origin-opener-policy'] == 'same-origin'
    assert got['x-content-type-options'] == 'nosniff'
    assert got['referrer-policy'] == 'no-referrer'
    assert got['cache-control'] == 'no-store'


def _live_sources():
    live = Path(_server().__file__).resolve().parent / 'static' / 'live'
    return sorted(p for p in live.iterdir() if p.suffix in ('.js', '.html'))


def test_live_sources_have_no_eval_new_function_or_string_timers():
    import re
    bad = re.compile(r"\beval\s*\(|\bnew\s+Function\s*\(|\bset(?:Timeout|Interval)\s*\(\s*['\"`]|\bFunction\s*\(\s*['\"`]")
    offenders = [p.name for p in _live_sources() if bad.search(p.read_text(encoding='utf-8'))]
    assert offenders == []


def test_live_html_has_no_inline_script_style_handlers_or_javascript_urls():
    import re
    html = (Path(_server().__file__).resolve().parent / 'static' / 'live' / 'index.html').read_text(encoding='utf-8')
    assert not re.search(r'<script(?![^>]*\bsrc=)[^>]*>', html, re.I)
    assert not re.search(r'<style\b', html, re.I)
    assert not re.search(r'\sstyle\s*=', html, re.I)
    assert not re.search(r'\son[a-z]+\s*=', html, re.I)
    assert not re.search(r'javascript:', html, re.I)


def test_server_source_never_allows_unsafe_keywords():
    source = Path(_server().__file__).read_text(encoding='utf-8')
    assert 'unsafe-inline' not in source and 'unsafe-eval' not in source


# --- 2. Token handling ---------------------------------------------------------------------

@pytest.mark.parametrize('headers, query', [
    ({'Authorization': 'Bearer ' + TOKEN[:-1]}, ''),
    ({'Authorization': 'Bearer ' + TOKEN + 'x'}, ''),
    ({'Authorization': 'Bearer '}, ''),
    ({'Authorization': 'Bearer'}, ''),
    ({'Authorization': 'Basic ' + TOKEN}, ''),
    ({'X-Simplicio-Token': ''}, ''),
    ({'Authorization': 'Bearer ' + 'a' * 10000}, ''),
    ({'X-Simplicio-Token': 'z' * 10000}, ''),
    ({}, '?t='),
    ({}, '?t=' + 'b' * 10000),
    ({}, '?t=' + TOKEN[:-1]),
    ({}, ''),
])
def test_wrong_empty_prefix_or_oversize_token_is_401_on_every_read_route(handle, headers, query):
    for path in ('/api/runs', '/api/queue', '/api/tokens', '/api/runs/%s' % RUN_ID,
                 '/api/runs/%s/events' % RUN_ID, '/', '/api/runs/%s/artifacts/secret.txt' % RUN_ID):
        status, _, body = _request(handle.port, 'GET', path + query,
                                   {'Host': '127.0.0.1:%d' % handle.port, **headers})
        assert status == 401, (path, status)
        assert b'outside every run dir' not in body


def test_query_token_wins_over_a_correct_header_when_it_is_wrong(handle):
    # The query form is checked first; a wrong ?t= is refused even with a right Bearer header.
    status, _, _ = _request(handle.port, 'GET', '/api/runs?t=wrong-token-value', AUTH)
    assert status == 401


def test_empty_query_token_falls_back_to_the_header(handle):
    status, _, _ = _request(handle.port, 'GET', '/api/runs?t=', AUTH)
    assert status == 200


def test_token_is_never_echoed_in_any_status_body_or_header(handle):
    port = handle.port
    wrong = 'NOT-' + TOKEN
    cases = [
        ('GET', '/api/runs?t=' + TOKEN[:-1], {}),
        ('GET', '/api/runs/no-such-run?t=' + TOKEN, {}),
        ('GET', '/api/runs/no-such-run', {'Authorization': 'Bearer ' + TOKEN}),
        ('GET', '/api/runs?since=' + TOKEN, AUTH),
        ('GET', '/api/runs/%s/events' % RUN_ID, {'Last-Event-ID': TOKEN, **AUTH}),
        ('GET', '/api/runs/%s/artifacts/%s' % (RUN_ID, TOKEN), AUTH),
        ('GET', '/api/nope?t=' + TOKEN, AUTH),
        ('POST', '/api/runs?t=' + TOKEN, AUTH),
        ('GET', '/api/health', {'Host': 'evil.example', 'X-Simplicio-Token': TOKEN}),
        ('GET', '/static/%2e%2e/' + TOKEN, {'Host': 'evil.example'}),
        ('GET', '/', {'Authorization': 'Bearer ' + wrong}),
        ('GET', '/api/runs', {'Authorization': 'Bearer ' + wrong, 'Origin': 'null'}),
    ]
    for method, path, headers in cases:
        status, got_headers, body = _request(port, method, path,
                                             {'Host': '127.0.0.1:%d' % port, **headers})
        assert TOKEN.encode() not in body, (method, path, status)
        assert TOKEN not in json.dumps(got_headers), (method, path, status)


def test_token_is_not_echoed_by_protocol_error_pages(handle):
    port = handle.port
    for raw in (
        b'GET /api/health HTTP/9.9\r\nHost: 127.0.0.1:%d\r\n\r\n' % port,
        b'TRACE /api/runs HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nAuthorization: Bearer %s\r\n\r\n' % (port, TOKEN.encode()),
        b'FOO /api/runs HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nAuthorization: Bearer %s\r\n\r\n' % (port, TOKEN.encode()),
        b'GET /api/runs HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nX-Big: %s\r\n\r\n' % (port, b'q' * 70000),
    ):
        status, _, body = _split(_raw(port, raw))
        assert TOKEN.encode() not in body and TOKEN.encode() not in raw.split(b'\r\n')[0]
        assert status >= 400


def test_protocol_error_pages_carry_the_security_headers(handle):
    port = handle.port
    for raw in (b'GET /api/health HTTP/9.9\r\nHost: 127.0.0.1:%d\r\n\r\n' % port, b'FOO /api/health HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n\r\n' % port,
                b'GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nX-Big: %s\r\n\r\n' % (port, b'q' * 70000)):
        status, headers, _ = _split(_raw(port, raw))
        assert status >= 400
        assert 'frame-ancestors' in headers.get('content-security-policy', '')
        assert headers.get('x-content-type-options') == 'nosniff'


def test_protocol_error_closes_the_connection_and_never_serves_a_pipelined_request(handle):
    port = handle.port
    host = b'Host: 127.0.0.1:%d\r\n' % port
    for bad in (b'GET /api/health HTTP/9.9\r\n', b'GARBAGE\r\n', b'FOO /api/health HTTP/1.1\r\n'):
        wire = _raw(port, bad + host + b'\r\n' + b'GET /api/health HTTP/1.1\r\n' + host + b'\r\n')
        assert wire.startswith(b'HTTP/1.'), (bad, wire[:60])  # a status line, never an HTTP/0.9-style bare body
        assert wire.count(b'HTTP/1.') == 1, (bad, wire)  # the pipelined request after the error is not processed
        assert _split(wire)[0] >= 400


def test_health_discloses_only_the_probe_fields_and_no_path_or_token(handle, repo):
    status, _, body = _request(handle.port, 'GET', '/api/health', {'Host': '127.0.0.1:%d' % handle.port})
    assert status == 200
    info = json.loads(body)
    assert set(info) == {'status', 'version', 'pid', 'uptime_s', 'observed_runs'}
    assert str(repo).encode() not in body
    assert TOKEN.encode() not in body


@pytest.mark.parametrize('path', [
    '/static/live/app.py', '/static/live/app', '/static/live/.env', '/static/live/key.pem',
    '/static/live/app.js.map', '/static/live/', '/static/live', '/static/', '/static/live/app.jsx',
])
def test_static_serves_only_the_allowed_extensions(handle, path):
    status, _, body = _request(handle.port, 'GET', path, {'Host': '127.0.0.1:%d' % handle.port})
    assert status in (403, 404), (path, status)
    assert b'import ' not in body


def test_static_serves_the_allowed_kit_files(handle):
    for path in ('/static/live/app.js', '/static/live/live.css', '/static/live/index.html'):
        status, _, _ = _request(handle.port, 'GET', path, {'Host': '127.0.0.1:%d' % handle.port})
        assert status == 200, path


# --- 3. Path traversal --------------------------------------------------------------------

STATIC_TRAVERSAL = [
    '/static/%2e%2e/server.py',
    '/static/..%2f..%2fserver.py',
    '/static/..%5c..%5cserver.py',
    '/static/..\\..\\server.py',
    '/static/live/app.js%00.txt',
    '/static//etc/passwd.txt',
    '/static/%2fetc%2fpasswd.txt',
    '/static/live/../../../../../../../etc/passwd.txt',
    '/static/live/..%2f..%2f..%2fserver.py',
    '/static/%252e%252e/server.py',
    '/static/%252e%252e%252fserver.py',
    '/static/live/app.js/',
]


@pytest.mark.parametrize('path', STATIC_TRAVERSAL)
def test_static_traversal_variants_are_refused_and_never_return_a_file(handle, path):
    status, _, body = _request(handle.port, 'GET', path, {'Host': '127.0.0.1:%d' % handle.port})
    assert status in (403, 404), (path, status)
    assert b'def ' not in body and b'import ' not in body and b'root:' not in body


ARTIFACT_TRAVERSAL = [
    '%2e%2e%2fsecret.txt',
    '..%2fsecret.txt',
    '..%2F..%2Fsecret.txt',
    '%252e%252e%252fsecret.txt',
    '..%252fsecret.txt',
    '..%5csecret.txt',
    '..\\secret.txt',
    'x%00.txt',
    '%2Fetc%2Fpasswd',
    '/etc/passwd',
    '..//secret.txt',
    './secret.txt',
    '%2e/secret.txt',
    '%2e%2e',
    '.',
    '',
]


@pytest.mark.parametrize('rel', ARTIFACT_TRAVERSAL)
def test_artifact_traversal_variants_are_403_or_404(handle, rel):
    status, _, body = _request(handle.port, 'GET', '/api/runs/%s/artifacts/%s' % (RUN_ID, rel), AUTH)
    assert status in (403, 404), (rel, status)
    assert REPO_ROOT_MARKER.encode() not in body


RUN_ID_TRAVERSAL = ['..%2F..', '%2e%2e', '..%5C..', 'live-1%2F..', '%00', '..', '.', 'live-1%2e%2e']


@pytest.mark.parametrize('run_id', RUN_ID_TRAVERSAL)
def test_run_id_with_traversal_is_404_on_every_run_route(handle, run_id):
    for suffix in ('', '/events', '/artifacts/secret.txt'):
        status, _, body = _request(handle.port, 'GET', '/api/runs/%s%s' % (run_id, suffix), AUTH)
        assert status in (403, 404), (run_id, suffix, status)
        assert REPO_ROOT_MARKER.encode() not in body


def test_symlink_inside_run_dir_pointing_outside_is_refused(handle, run_dir, repo):
    (run_dir / 'link.txt').symlink_to(repo / 'secret.txt')
    (run_dir / 'dirlink').symlink_to(repo)
    for rel in ('link.txt', 'dirlink/secret.txt'):
        status, _, body = _request(handle.port, 'GET', '/api/runs/%s/artifacts/%s' % (RUN_ID, rel), AUTH)
        assert status in (403, 404), (rel, status)
        assert REPO_ROOT_MARKER.encode() not in body


def test_symlinked_state_json_outside_run_dir_is_never_read(handle, run_dir, repo):
    outside = repo / 'outside-state.json'
    outside.write_text(json.dumps({'status': 'done', 'note': REPO_ROOT_MARKER}), encoding='utf-8')
    (run_dir / 'state.json').unlink()
    (run_dir / 'state.json').symlink_to(outside)
    for path in ('/api/runs/%s' % RUN_ID, '/api/runs', '/api/queue'):
        status, _, body = _request(handle.port, 'GET', path, AUTH)
        assert status == 200
        assert REPO_ROOT_MARKER.encode() not in body, path


def test_symlinked_manifest_and_plan_outside_run_dir_are_never_read(handle, run_dir, repo):
    outside = repo / 'outside.json'
    outside.write_text(json.dumps({'note': REPO_ROOT_MARKER}), encoding='utf-8')
    (run_dir / 'manifest.json').symlink_to(outside)
    (run_dir / 'plan.json').symlink_to(outside)
    status, _, body = _request(handle.port, 'GET', '/api/runs/%s' % RUN_ID, AUTH)
    assert status == 200
    assert REPO_ROOT_MARKER.encode() not in body


def test_symlinked_events_jsonl_outside_run_dir_is_never_streamed(handle, run_dir, repo):
    outside = repo / 'outside-events.jsonl'
    outside.write_text(_event(1, payload={'note': REPO_ROOT_MARKER}) + '\n', encoding='utf-8')
    (run_dir / 'events.jsonl').unlink()
    (run_dir / 'events.jsonl').symlink_to(outside)
    text = _sse_text(handle.port, '/api/runs/%s/events' % RUN_ID, AUTH, min_data=1)
    assert REPO_ROOT_MARKER not in text


def test_symlinked_receipts_dir_outside_run_dir_is_not_indexed(handle, run_dir, repo):
    outside = repo / 'outside-receipts'
    outside.mkdir()
    (outside / 'leak.json').write_text(json.dumps({'schema': 'x'}), encoding='utf-8')
    (run_dir / 'receipts').symlink_to(outside)
    status, _, body = _request(handle.port, 'GET', '/api/runs/%s' % RUN_ID, AUTH)
    assert status == 200
    names = [row['name'] for row in json.loads(body)['receipts']]
    assert not any('leak.json' in name for name in names), names


def test_symlinked_completion_receipt_outside_run_dir_is_never_read(handle, run_dir, repo):
    outside = repo / 'outside-completion.json'
    outside.write_text(json.dumps({'ready': True, 'verdict': 'VERIFIED', 'note': REPO_ROOT_MARKER}), encoding='utf-8')
    (run_dir / 'completion-receipt.json').symlink_to(outside)
    status, _, body = _request(handle.port, 'GET', '/api/runs', AUTH)
    assert status == 200
    assert REPO_ROOT_MARKER.encode() not in body


def test_symlinked_run_directory_is_not_discovered(handle, repo):
    elsewhere = repo.parent / 'elsewhere-run'
    elsewhere.mkdir()
    (elsewhere / 'state.json').write_text(json.dumps({'status': 'done', 'note': REPO_ROOT_MARKER}), encoding='utf-8')
    (repo / '.simplicio-loop' / 'loop-runs' / 'linked-run').symlink_to(elsewhere)
    status, _, body = _request(handle.port, 'GET', '/api/runs/linked-run', AUTH)
    assert status == 404
    assert REPO_ROOT_MARKER.encode() not in body


def test_artifact_content_types_never_render_an_active_document(handle, run_dir):
    for name in ('page.html', 'page.xhtml', 'vector.svg', 'doc.xml'):
        (run_dir / name).write_text('<html><script>x</script></html>', encoding='utf-8')
        status, headers, _ = _request(handle.port, 'GET', '/api/runs/%s/artifacts/%s' % (RUN_ID, name), AUTH)
        assert status == 200, name
        assert headers['content-type'].startswith('text/plain'), (name, headers['content-type'])


# --- 4. Methods ----------------------------------------------------------------------------

METHOD_TARGETS = ['/api/health', '/api/runs', '/api/runs/%s' % RUN_ID, '/api/runs/%s/events' % RUN_ID,
                  '/api/runs/%s/artifacts/secret.txt' % RUN_ID, '/static/live/app.js', '/', '/api/tokens']


@pytest.mark.parametrize('method', ['POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD', 'TRACE', 'CONNECT'])
def test_non_get_methods_are_405_with_no_run_data_and_no_side_effects(handle, repo, method):
    before = _tree(repo)
    for path in METHOD_TARGETS:
        conn = http.client.HTTPConnection('127.0.0.1', handle.port, timeout=TIMEOUT)
        try:
            conn.request(method, path,
                         headers={'Host': '127.0.0.1:%d' % handle.port, 'Content-Type': 'application/json', **AUTH})
            resp = conn.getresponse()
            body = resp.read()
            assert resp.status == 405, (method, path, resp.status)
            assert json.loads(body or b'{}') == {'error': 'Method Not Allowed'} or method == 'HEAD'
            assert REPO_ROOT_MARKER.encode() not in body and RUN_ID.encode() not in body
        finally:
            conn.close()
    assert _tree(repo) == before


def test_head_is_refused_with_405_and_no_body_bytes_on_the_wire(handle):
    wire = _raw(handle.port, b'HEAD /api/health HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nConnection: close\r\n\r\n'
                % handle.port)
    status, headers, body = _split(wire)
    assert status == 405
    assert body == b''
    assert 'frame-ancestors' in headers.get('content-security-policy', '')


def test_head_on_a_get_route_is_405_even_with_the_token(handle):
    wire = _raw(handle.port, b'HEAD /api/runs HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nAuthorization: Bearer %s\r\n'
                b'Connection: close\r\n\r\n' % (handle.port, TOKEN.encode()))
    status, _, body = _split(wire)
    assert status == 405
    assert body == b''


def test_get_is_side_effect_free_over_every_read_route(handle, repo):
    before = _tree(repo)
    for path in ('/api/runs', '/api/queue', '/api/agents', '/api/tokens', '/api/health',
                 '/api/runs/%s' % RUN_ID, '/api/runs/%s/artifacts/secret.txt' % RUN_ID, '/'):
        _request(handle.port, 'GET', path, AUTH)
    _sse_text(handle.port, '/api/runs/%s/events' % RUN_ID, AUTH, min_data=1)
    assert _tree(repo) == before


# --- 5. Redaction --------------------------------------------------------------------------

def test_every_secret_shape_in_an_artifact_is_masked(handle, run_dir):
    (run_dir / 'notes.txt').write_text(SECRET_TEXT, encoding='utf-8')
    status, _, body = _request(handle.port, 'GET', '/api/runs/%s/artifacts/notes.txt' % RUN_ID, AUTH)
    assert status == 200
    _assert_no_secret(body)


def test_secrets_in_nested_json_keys_and_key_names_are_masked_in_detail(handle, run_dir):
    plan = {'steps': [{'auth': {'apiKey': NESTED_KEY_VALUE, 'label': SK_OPENAI}}],
            'note': GHP, 'credentials': {'value': PASSWORD_VALUE}, SK_ANTHROPIC: 'x'}
    (run_dir / 'plan.json').write_text(json.dumps(plan), encoding='utf-8')
    status, _, body = _request(handle.port, 'GET', '/api/runs/%s' % RUN_ID, AUTH)
    assert status == 200
    _assert_no_secret(body)


def test_secrets_in_state_reach_no_run_list_queue_or_detail_response(handle, run_dir):
    state = json.loads((run_dir / 'state.json').read_text(encoding='utf-8'))
    state.update({'label': SK_OPENAI, 'note': SECRET_TEXT, 'nested': {'token': TOKEN_VALUE}})
    (run_dir / 'state.json').write_text(json.dumps(state), encoding='utf-8')
    for path in ('/api/runs', '/api/queue', '/api/runs/%s' % RUN_ID):
        status, _, body = _request(handle.port, 'GET', path, AUTH)
        assert status == 200, path
        _assert_no_secret(body)


def test_secrets_in_receipt_and_sidecar_files_reach_no_run_response(handle, run_dir):
    (run_dir / 'evidence-receipt.json').write_text(json.dumps({'status': 'MEASURED', 'note': GHP}), encoding='utf-8')
    (run_dir / 'completion-receipt.json').write_text(json.dumps({'ready': False, 'note': SK_ANTHROPIC}), encoding='utf-8')
    (run_dir / 'execution-route.json').write_text(json.dumps({'note': AKIA}), encoding='utf-8')
    (run_dir / 'loop').mkdir()
    (run_dir / 'loop' / 'watcher_state.json').write_text(json.dumps({'status': 'x', 'note': GITHUB_PAT}), encoding='utf-8')
    for path in ('/api/runs', '/api/runs/%s' % RUN_ID):
        status, _, body = _request(handle.port, 'GET', path, AUTH)
        assert status == 200, path
        _assert_no_secret(body)


def test_secret_in_a_receipt_schema_id_is_masked_in_the_validation_reason(handle, run_dir):
    (run_dir / 'receipts').mkdir()
    (run_dir / 'receipts' / 'r1.json').write_text(json.dumps({'schema': SK_ANTHROPIC}), encoding='utf-8')
    status, _, body = _request(handle.port, 'GET', '/api/runs/%s' % RUN_ID, AUTH)
    assert status == 200
    _assert_no_secret(body)


def test_secrets_in_the_sse_event_stream_are_masked(handle, run_dir):
    events = [_event(3, kind='log_line', payload={'line': SECRET_TEXT, 'token': TOKEN_VALUE}),
              _event(4, kind='gate_evaluated', payload={'gate': 'tests', 'verdict': 'fail', 'message': SECRET_TEXT})]
    with (run_dir / 'events.jsonl').open('a', encoding='utf-8') as fh:
        fh.write('\n'.join(events) + '\n')
    text = _sse_text(handle.port, '/api/runs/%s/events' % RUN_ID, AUTH, min_data=4)
    assert 'data:' in text
    for marker in SECRET_MARKERS:
        assert marker not in text, marker[:12]


def test_secret_in_a_gate_message_is_masked_in_the_alert_frames(handle, run_dir):
    events = [_event(3, kind='gate_evaluated', payload={'gate': 'tests', 'verdict': 'fail',
                                                        'message': 'leaked ' + SK_OPENAI})]
    with (run_dir / 'events.jsonl').open('a', encoding='utf-8') as fh:
        fh.write('\n'.join(events) + '\n')
    text = _sse_text(handle.port, '/api/runs/%s/events' % RUN_ID, AUTH, min_data=99, timeout=2)
    assert SK_OPENAI not in text
    assert 'alert_snapshot' in text or 'alert_raised' in text


def test_token_monitor_status_is_redacted_before_it_is_returned(handle, monkeypatch):
    class _Hook:
        @staticmethod
        def get_status():
            return {'log_lines': ['upstream key ' + SK_OPENAI, 'password=' + PASSWORD_VALUE],
                    'models_seen': [{'model': SK_ANTHROPIC}], 'api_key': NESTED_KEY_VALUE}

    monkeypatch.setattr(_server(), '_load_hook', lambda: _Hook)
    status, _, body = _request(handle.port, 'GET', '/api/tokens', AUTH)
    assert status == 200
    _assert_no_secret(body)


# --- 6. Host, Origin and DNS rebinding -----------------------------------------------------

FOREIGN_HOSTS = ['evil.com', '127.0.0.1.evil.com', 'localhost.evil.com', 'evil.com:%(port)d',
                 '127.0.0.1.evil.com:%(port)d', '127.0.0.1:1', '127.0.0.1:', 'LOCALHOST:%(port)d',
                 '127.0.0.1', 'localhost', '[::1]:%(port)d', '0.0.0.0:%(port)d', '', 'null']


@pytest.mark.parametrize('host', FOREIGN_HOSTS)
@pytest.mark.parametrize('path, auth', [('/api/health', {}), ('/api/runs', AUTH), ('/static/live/app.js', {}),
                                        ('/', AUTH)])
def test_foreign_or_portless_host_is_403_even_with_a_valid_token(handle, host, path, auth):
    headers = {'Host': host % {'port': handle.port}, **auth}
    status, _, body = _request(handle.port, 'GET', path, headers)
    assert status == 403, (host, path, status)
    assert TOKEN.encode() not in body


@pytest.mark.parametrize('origin', [
    'null', 'http://evil.com', 'https://127.0.0.1:%(port)d', 'http://127.0.0.1:1',
    'http://127.0.0.1:%(other)d', 'http://127.0.0.1.evil.com:%(port)d', 'http://localhost:1',
    'http://127.0.0.1:%(port)d/', 'http://127.0.0.1', 'file://', '', 'http://[::1]:%(port)d',
])
def test_foreign_origin_is_403_on_read_and_static_routes(handle, origin):
    values = {'port': handle.port, 'other': handle.port + 1}
    headers = {'Host': '127.0.0.1:%d' % handle.port, 'Origin': origin % values, **AUTH}
    for path in ('/api/runs', '/static/live/app.js', '/api/health'):
        status, _, _ = _request(handle.port, 'GET', path, headers)
        assert status == 403, (origin, path, status)


def test_same_origin_loopback_host_is_accepted_with_and_without_origin(handle):
    good = {'Host': '127.0.0.1:%d' % handle.port}
    assert _request(handle.port, 'GET', '/api/health', good)[0] == 200
    assert _request(handle.port, 'GET', '/api/health',
                    {**good, 'Origin': 'http://127.0.0.1:%d' % handle.port})[0] == 200
    assert _request(handle.port, 'GET', '/api/runs', {'Host': 'localhost:%d' % handle.port, **AUTH})[0] == 200
    assert _request(handle.port, 'GET', '/api/runs', {'Host': 'localhost:%d' % handle.port,
                                                      'Origin': 'http://localhost:%d' % handle.port,
                                                      **AUTH})[0] == 200


def test_foreign_host_with_a_correct_token_leaks_nothing_on_any_route(handle):
    for path in ('/api/runs', '/api/runs/%s' % RUN_ID, '/api/runs/%s/events' % RUN_ID, '/api/tokens',
                 '/api/runs/%s/artifacts/secret.txt' % RUN_ID):
        status, _, body = _request(handle.port, 'GET', path,
                                   {'Host': 'evil.com', 'Origin': 'http://evil.com', **AUTH})
        assert status == 403
        assert REPO_ROOT_MARKER.encode() not in body and RUN_ID.encode() not in body


def test_symlink_inside_the_static_kit_pointing_outside_is_never_served(handle, repo, monkeypatch, tmp_path):
    kit = tmp_path / 'kit'
    kit.mkdir()
    (kit / 'ok.js').write_text('console.log(1);', encoding='utf-8')
    outside = repo / 'outside.js'
    outside.write_text('// ' + REPO_ROOT_MARKER, encoding='utf-8')
    (kit / 'escape.js').symlink_to(outside)
    monkeypatch.setattr(_server(), 'STATIC_DIR', kit)
    status, _, _ = _request(handle.port, 'GET', '/static/ok.js', {'Host': '127.0.0.1:%d' % handle.port})
    assert status == 200
    status, _, body = _request(handle.port, 'GET', '/static/escape.js', {'Host': '127.0.0.1:%d' % handle.port})
    assert status == 404
    assert REPO_ROOT_MARKER.encode() not in body
