'''Black-box integration tests for the dashboard /static route and the Simplicio Live page shell.

Issue #1402, slice 4b-1 (TDD red): the /static route and static/live/index.html do not exist yet, so these
tests fail with 404, 401 or an assertion mismatch. The server binds 127.0.0.1 on port 0 and is always stopped.
Every socket has a hard 5 s timeout.
'''
import http.client
import re

import pytest

HOST = '127.0.0.1'
TOKEN = 'static-integration-token-0123'
AUTH = {'Authorization': 'Bearer ' + TOKEN}
CSP = "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'"
TIMEOUT = 5


def _get(port, path, headers=None, method='GET'):
    conn = http.client.HTTPConnection(HOST, port, timeout=TIMEOUT)
    try:
        sent = {'Host': '%s:%d' % (HOST, port)}
        sent.update(headers or {})
        conn.request(method, path, headers=sent)
        resp = conn.getresponse()
        return resp.status, {name.lower(): value for name, value in resp.getheaders()}, resp.read()
    finally:
        conn.close()


def _mime(headers):
    return headers['content-type'].split(';')[0].strip().lower()


@pytest.fixture
def server_port(tmp_path):
    from simplicio_loop.dashboard import server
    root = tmp_path / 'repo'
    (root / '.simplicio-loop').mkdir(parents=True)
    (root / 'secret.txt').write_text('outside the static root', encoding='utf-8')
    handle = server.start(repo_root=root, host=HOST, port=0, token=TOKEN)
    try:
        yield handle.port
    finally:
        handle.stop()


def _kit_files(suffix):
    from simplicio_loop.dashboard import STATIC_DIR
    return sorted(path.relative_to(STATIC_DIR).as_posix() for path in STATIC_DIR.rglob('*' + suffix))


@pytest.mark.parametrize('rel, mime', [
    ('catalog.js', 'text/javascript'),
    ('catalog.css', 'text/css'),
    ('components/simplicio-live.css', 'text/css'),
])
def test_kit_script_and_stylesheet_are_served_without_a_token(server_port, rel, mime):
    status, headers, body = _get(server_port, '/static/' + rel)
    assert status == 200
    assert _mime(headers) == mime
    assert body


def test_kit_woff2_font_is_served_as_font_woff2_without_a_token(server_port):
    fonts = _kit_files('.woff2')
    assert fonts, 'the kit ships no .woff2 font under simplicio_loop/dashboard/static'
    status, headers, body = _get(server_port, '/static/' + fonts[0])
    assert status == 200
    assert _mime(headers) == 'font/woff2'
    assert body


@pytest.mark.parametrize('path', ['/static/catalog.js', '/static/nope.js', '/static/components', '/'])
def test_csp_and_nosniff_are_on_every_response(server_port, path):
    _, headers, _ = _get(server_port, path)
    assert headers.get('content-security-policy') == CSP
    assert headers.get('x-content-type-options') == 'nosniff'


@pytest.mark.parametrize('path', [
    '/static/../secret.txt',
    '/static/%2e%2e/secret.txt',
    '/static/..%5csecret.txt',
    '/static/%00',
])
def test_traversal_segments_are_rejected_with_403(server_port, path):
    status, _, _ = _get(server_port, path)
    assert status == 403


def test_directory_and_unknown_file_return_404(server_port):
    assert _get(server_port, '/static/components')[0] == 404
    assert _get(server_port, '/static/nope.js')[0] == 404


def test_post_to_static_is_405(server_port):
    assert _get(server_port, '/static/catalog.js', method='POST')[0] == 405


def test_foreign_host_is_refused_on_static(server_port):
    status, _, _ = _get(server_port, '/static/catalog.js', headers={'Host': 'evil.example'})
    assert status == 403


def test_api_without_a_token_is_401(server_port):
    assert _get(server_port, '/api/runs')[0] == 401


def test_root_without_a_token_is_401(server_port):
    assert _get(server_port, '/')[0] == 401


def test_root_with_the_token_serves_the_live_page_shell(server_port):
    status, headers, body = _get(server_port, '/', headers=AUTH)
    assert status == 200
    assert _mime(headers) == 'text/html'
    html = body.decode('utf-8')
    assert 'id="rail"' in html
    tags = re.findall(r'<script\b[^>]*>', html, flags=re.IGNORECASE)
    module_tags = [tag for tag in tags if 'type="module"' in tag.lower()]
    assert len(module_tags) == 1, tags
    assert [tag for tag in tags if 'src=' not in tag.lower()] == [], 'inline script'
    assert re.search(r'\sstyle\s*=', html) is None, 'inline style attribute'
    assert re.search(r'\son[a-z]+\s*=', html, flags=re.IGNORECASE) is None, 'inline event handler'
