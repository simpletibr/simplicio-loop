'''The app shell of the Simplicio Live page: sidebar links, view markers and the served shell files.

The pure route, tab and count rules are checked by tests/fixtures/shell/shell_model_check.mjs under node.
'''
import http.client
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HOST = '127.0.0.1'
TOKEN = 'shell-static-token-0123'
TIMEOUT = 5
REPO = Path(__file__).resolve().parents[1]
VIEWS = ['painel', 'tarefas', 'tarefa', 'caixa', 'decisoes', 'custos', 'historico']


def _get(port, path):
    conn = http.client.HTTPConnection(HOST, port, timeout=TIMEOUT)
    try:
        conn.request('GET', path, headers={'Host': '%s:%d' % (HOST, port)})
        resp = conn.getresponse()
        return resp.status, resp.getheader('Content-Type', ''), resp.read().decode('utf-8', 'replace')
    finally:
        conn.close()


@pytest.fixture
def server_port(tmp_path):
    from simplicio_loop.dashboard import server
    root = tmp_path / 'repo'
    (root / '.simplicio-loop').mkdir(parents=True)
    handle = server.start(repo_root=root, host=HOST, port=0, token=TOKEN)
    try:
        yield handle.port
    finally:
        handle.stop()


def _index_html():
    from simplicio_loop.dashboard import STATIC_DIR
    return (STATIC_DIR / 'live' / 'index.html').read_text(encoding='utf-8')


def test_sidebar_links_every_view_once():
    html = _index_html()
    for view in VIEWS:
        assert html.count('data-view-link="%s"' % view) == 1, view
    assert set(re.findall(r'data-view-link="([a-z]+)"', html)) == set(VIEWS)


def test_every_data_view_marker_names_a_known_view():
    html = _index_html()
    markers = re.findall(r'data-view="([^"]+)"', html)
    assert markers, 'the page declares no view sections'
    for marker in markers:
        for name in marker.split():
            assert name in VIEWS, marker


def test_each_view_has_at_least_one_section():
    html = _index_html()
    for view in VIEWS:
        assert any(view in marker.split() for marker in re.findall(r'data-view="([^"]+)"', html)), view


def test_the_shell_files_are_served_without_a_token(server_port):
    for path, mime in [('/static/shell/shell.css', 'text/css'), ('/static/shell/shell.js', 'javascript'),
                       ('/static/shell/shell-model.js', 'javascript')]:
        status, ctype, body = _get(server_port, path)
        assert status == 200, path
        assert mime in ctype, (path, ctype)
        assert body.strip(), path


@pytest.mark.skipif(shutil.which('node') is None, reason='node is needed for the shell model check')
def test_shell_model_rules_hold_under_node():
    script = REPO / 'tests' / 'fixtures' / 'shell' / 'shell_model_check.mjs'
    done = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert 'shell model: ok' in done.stdout
