'''Static checks on the Simplicio Live iteration and quality panel sources (issue #1403, slice 1403a, TDD red).

iterations.js and panels.js do not exist yet and index.html has no iteration or quality panel, so these tests fail
on a missing file, a missing id, a wrong tag or a missing text. The checks follow tests/test_live_pipeline_page_unit.py.
'''
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

LIVE = Path(__file__).resolve().parents[1] / 'simplicio_loop' / 'dashboard' / 'static' / 'live'
NEW_FILES = ['iterations.js', 'panels.js']
FORBIDDEN = [r'innerHTML', r'\beval\s*\(', r'https?://']
PURE_FORBIDDEN = re.compile(r'\bdocument\b|\bwindow\b|\bfetch\s*\(|\bDate\.now\b|\bnew\s+Date\s*\(|\bMath\.random\b')
INLINE_STYLE = re.compile(r'setAttribute\(\s*.style.|\.style\s*[.=]')
CSS_TEXT = re.compile(r'\bcssText\b')
PANEL_IDS = {
    'iterations': 'sl-timeline',
    'convergence': 'sl-sparkline',
    'convergence-note': 'p',
    'dod': 'ul',
    'quality': 'ul',
}


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.by_id = {}

    def handle_starttag(self, tag, attrs):
        data = {name: value for name, value in attrs}
        if data.get('id'):
            self.by_id.setdefault(data['id'], (tag, data))


def _read(name):
    return (LIVE / name).read_text(encoding='utf-8')


def _index():
    page = _Page()
    page.feed(_read('index.html'))
    return page.by_id


@pytest.mark.parametrize('name', NEW_FILES)
def test_new_panel_modules_exist(name):
    assert (LIVE / name).is_file(), name


@pytest.mark.parametrize('name', NEW_FILES)
@pytest.mark.parametrize('pattern', FORBIDDEN)
def test_panel_sources_avoid_innerhtml_eval_and_absolute_urls(name, pattern):
    assert re.search(pattern, _read(name)) is None, (name, pattern)


@pytest.mark.parametrize('name', NEW_FILES)
def test_panel_sources_never_set_inline_style_or_use_csstext(name):
    text = _read(name)
    assert INLINE_STYLE.search(text) is None, name
    assert CSS_TEXT.search(text) is None, name


def test_iterations_module_is_pure():
    hit = PURE_FORBIDDEN.search(_read('iterations.js'))
    assert hit is None, hit.group(0) if hit else ''


@pytest.mark.parametrize('dom_id, tag', sorted(PANEL_IDS.items()))
def test_index_html_declares_the_panel_ids(dom_id, tag):
    by_id = _index()
    assert dom_id in by_id, dom_id
    assert by_id[dom_id][0] == tag, (dom_id, by_id[dom_id][0])


def test_app_fetches_quality_matrix_artifact():
    assert 'quality-matrix.json' in _read('app.js')
