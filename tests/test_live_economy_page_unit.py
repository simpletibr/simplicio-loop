'''Static checks on the Simplicio Live global economy panel sources (issue #1404, slice 1404a, TDD red).

economy.js does not exist yet, index.html has no economy panel and app.js does not poll /api/tokens, so these tests
fail on a missing file, a missing id, a wrong tag or a missing request. The checks follow
tests/test_live_iterations_page_unit.py.
'''
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

LIVE = Path(__file__).resolve().parents[1] / 'simplicio_loop' / 'dashboard' / 'static' / 'live'
ECONOMY = 'economy.js'
FORBIDDEN = [r'innerHTML', r'\beval\s*\(', r'https?://']
PURE_FORBIDDEN = re.compile(r'\bdocument\b|\bwindow\b|\bfetch\s*\(|\bDate\.now\b|\bnew\s+Date\s*\(|\bMath\.random\b')
INLINE_STYLE = re.compile(r'setAttribute\(\s*.style|\.style\s*[.=]')
CSS_TEXT = re.compile(r'\bcssText\b')
SET_INTERVAL = re.compile(r'setInterval\(([^\n]+?),\s*([^,\n]+?)\s*\)')
PANEL_IDS = {
    'economy': 'section',
    'economy-gauge': 'sl-donut',
    'kpi-saved': 'sl-kpi-card',
    'kpi-requests': 'sl-kpi-card',
    'kpi-intercept': 'sl-kpi-card',
    'economy-series': 'sl-sparkline',
    'economy-note': 'p',
    'agents-cost': 'ul',
}
MIN_TOKEN_POLL_MS = 15000


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


def _value(expr, text, depth=0):
    # Resolves an integer literal, a product of them, or an identifier declared as const/let/var NAME = <expr>.
    if depth > 5:
        return None
    total = 1
    for part in expr.split('*'):
        part = part.strip()
        if re.fullmatch(r'\d[\d_]*', part):
            total *= int(part.replace('_', ''))
            continue
        found = re.search(r'\b(?:const|let|var)\s+' + re.escape(part) + r'\s*=\s*([^;\n]+);', text)
        if found is None:
            return None
        inner = _value(found.group(1), text, depth + 1)
        if inner is None:
            return None
        total *= inner
    return total


def _token_delays(text):
    return [_value(delay, text) for callee, delay in SET_INTERVAL.findall(text) if 'token' in callee.lower()]


@pytest.mark.parametrize('dom_id, tag', sorted(PANEL_IDS.items()))
def test_index_html_declares_the_economy_ids(dom_id, tag):
    by_id = _index()
    assert dom_id in by_id, dom_id
    assert by_id[dom_id][0] == tag, (dom_id, by_id[dom_id][0])


def test_agents_cost_list_has_the_checks_class():
    by_id = _index()
    assert 'agents-cost' in by_id, 'agents-cost'
    assert 'checks' in (by_id['agents-cost'][1].get('class') or '').split()


def test_economy_module_exists():
    assert (LIVE / ECONOMY).is_file(), ECONOMY


@pytest.mark.parametrize('pattern', FORBIDDEN)
def test_economy_source_avoids_innerhtml_eval_and_absolute_urls(pattern):
    assert re.search(pattern, _read(ECONOMY)) is None, (ECONOMY, pattern)


def test_economy_source_never_sets_inline_style_or_uses_csstext():
    text = _read(ECONOMY)
    assert INLINE_STYLE.search(text) is None, ECONOMY
    assert CSS_TEXT.search(text) is None, ECONOMY


def test_economy_module_is_pure():
    hit = PURE_FORBIDDEN.search(_read(ECONOMY))
    assert hit is None, hit.group(0) if hit else ''


def test_app_calls_the_tokens_endpoint():
    assert '/api/tokens' in _read('app.js')


def test_app_sends_a_bearer_authorization_header_to_the_tokens_endpoint():
    text = _read('app.js')
    start = text.find('/api/tokens')
    window = text[max(0, start - 400):start + 400] if start >= 0 else ''
    assert 'Authorization' in window and 'Bearer' in window


def test_app_polls_the_tokens_endpoint_every_15_seconds_or_more():
    delays = _token_delays(_read('app.js'))
    assert delays, 'app.js has no setInterval for the tokens poll'
    assert all(delay is not None and delay >= MIN_TOKEN_POLL_MS for delay in delays), delays
