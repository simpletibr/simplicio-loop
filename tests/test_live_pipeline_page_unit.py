'''Static checks on the Simplicio Live pipeline page sources (issue #1402, slice 4b-1, TDD red).

The files under simplicio_loop/dashboard/static/live/ do not exist yet, so every test here fails with
FileNotFoundError. The checks pin the page contract: forbidden patterns, reducer purity, the DOM ids,
exactly one module script, reduced-motion-only animations and the gzip budget.
'''
import io
import json
import re
import tarfile
from html.parser import HTMLParser
from pathlib import Path

import pytest

LIVE = Path(__file__).resolve().parents[1] / 'simplicio_loop' / 'dashboard' / 'static' / 'live'
PAGE_FILES = ['index.html', 'live.css', 'app.js', 'view.js', 'reducer.js', 'sse.js']
FORBIDDEN = [r'innerHTML', r'\beval\s*\(', r'https?://']
PURE_FORBIDDEN = re.compile(r'\bdocument\b|\bwindow\b|\bfetch\s*\(|\bDate\.now\b|\bnew\s+Date\s*\(|\bMath\.random\b')
REDUCER_EXPORTS = ['GATES', 'READY_VERDICTS', 'STALE_AFTER_MS', 'initialState', 'reduce', 'selectView']
DOM_TAGS = {
    'rail': 'sl-stage-rail',
    'ring': 'sl-donut',
    'conn': 'sl-connection-dot',
    'kpi-epm': 'sl-kpi-card',
    'kpi-heartbeat': 'sl-kpi-card',
    'kpi-stall': 'sl-kpi-card',
}
DOM_IDS = ['rail', 'ring', 'phase-stats', 'agora', 'gates', 'conn', 'kpi-epm', 'kpi-heartbeat', 'kpi-stall', 'empty']
MEDIA_NO_PREFERENCE = re.compile(r'@media\s*\(\s*prefers-reduced-motion:\s*no-preference\s*\)\s*\{')
ANIMATION_DECL = re.compile(r'(?<![\w-])animation(?:-[a-z-]+)?\s*:')


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang = None
        self.body_classes = []
        self.by_id = {}
        self.scripts = []
        self.stylesheets = []

    def handle_starttag(self, tag, attrs):
        data = {name: value for name, value in attrs}
        if tag == 'html':
            self.lang = data.get('lang')
        elif tag == 'body':
            self.body_classes = (data.get('class') or '').split()
        elif tag == 'script':
            self.scripts.append(data)
        elif tag == 'link' and 'stylesheet' in (data.get('rel') or '').split():
            self.stylesheets.append(data.get('href'))
        if data.get('id'):
            self.by_id.setdefault(data['id'], (tag, data))


def _read(name):
    return (LIVE / name).read_text(encoding='utf-8')


def _index():
    page = _Page()
    page.feed(_read('index.html'))
    return page


def _block_end(text, start):
    depth = 1
    for index in range(start, len(text)):
        if text[index] == '{':
            depth += 1
        elif text[index] == '}':
            depth -= 1
            if depth == 0:
                return index
    return len(text)


@pytest.mark.parametrize('name', PAGE_FILES)
@pytest.mark.parametrize('pattern', FORBIDDEN)
def test_page_sources_avoid_innerhtml_eval_and_absolute_urls(name, pattern):
    assert re.search(pattern, _read(name)) is None, (name, pattern)


def test_index_html_has_no_inline_style_script_or_event_handler():
    html = _read('index.html')
    assert re.search(r'\sstyle\s*=', html) is None, 'inline style attribute'
    assert re.search(r'\son[a-z]+\s*=', html, flags=re.IGNORECASE) is None, 'inline event handler'
    inline = [tag for tag in re.findall(r'<script\b[^>]*>', html, flags=re.IGNORECASE) if 'src=' not in tag.lower()]
    assert inline == [], 'inline script'


def test_reducer_is_pure_and_exports_the_contract():
    text = _read('reducer.js')
    hit = PURE_FORBIDDEN.search(text)
    assert hit is None, hit.group(0) if hit else ''
    for name in REDUCER_EXPORTS:
        pattern = r'export\s+(?:const|let|function)\s+%s\b|export\s*\{[^}]*\b%s\b' % (name, name)
        assert re.search(pattern, text), name


@pytest.mark.parametrize('dom_id', DOM_IDS)
def test_index_html_declares_the_contract_ids(dom_id):
    assert dom_id in _index().by_id, dom_id


def test_contract_ids_carry_their_contract_elements():
    by_id = _index().by_id
    for dom_id, tag in DOM_TAGS.items():
        assert dom_id in by_id and by_id[dom_id][0] == tag, (dom_id, by_id.get(dom_id))
    assert 'empty' in by_id and by_id['empty'][1].get('role') == 'status'


def test_index_html_has_exactly_one_module_script_for_the_live_app():
    page = _index()
    assert len(page.scripts) == 1, page.scripts
    assert page.scripts[0].get('type') == 'module'
    assert page.scripts[0].get('src') == '/static/live/app.js'


def test_index_html_sets_language_body_class_and_both_stylesheets():
    page = _index()
    assert page.lang == 'pt-BR'
    assert 'sl-page' in page.body_classes
    assert {'/static/components/simplicio-live.css', '/static/live/live.css'} <= set(page.stylesheets)


def test_package_json_marks_the_directory_as_an_esm_package():
    assert json.loads(_read('package.json')) == {'type': 'module', 'private': True}


def test_css_animations_sit_only_inside_reduced_motion_no_preference():
    css = _read('live.css')
    spans = [(match.end(), _block_end(css, match.end())) for match in MEDIA_NO_PREFERENCE.finditer(css)]
    for decl in ANIMATION_DECL.finditer(css):
        inside = any(start <= decl.start() < end for start, end in spans)
        assert inside, css[max(0, decl.start() - 60):decl.start() + 60]


def test_live_directory_gzips_under_40_kib():
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        archive.add(str(LIVE), arcname='live')
    assert buffer.getbuffer().nbytes < 40 * 1024, buffer.getbuffer().nbytes
