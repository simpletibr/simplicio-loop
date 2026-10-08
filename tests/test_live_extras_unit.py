'''Unit tests for the Simplicio Live extras panel (issue #1402, extras slice).

extras.js exports a pure extrasOf(reply), which maps the GET /api/runs/<run>/extras reply to four labelled rows, each
with a visible state (PASS or UNVERIFIED) and a text, and startExtras(readApi, runId), which polls the endpoint every
3000 ms and renders the rows as a <dl> into #live-extras. The module runs in node with a stub document; the wiring in
index.html, app.js and the CSS are checked on the sources. extras.js never sets styles inline and the CSS has no motion.
'''
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / 'simplicio_loop' / 'dashboard' / 'static'
LIVE = STATIC / 'live'
EXTRAS_DIR = STATIC / 'extras'
MODULE = EXTRAS_DIR / 'extras.js'
STYLE = EXTRAS_DIR / 'extras.css'
LABELS = ['Último comando medido', 'Contrato por tarefa', 'Modelo por lane', 'Batimento do lease']
FORBIDDEN = [r'\binnerHTML\b', r'\beval\s*\(', r'https?://', r'setAttribute\(\s*.style', r'\.style\s*[.=]',
             r'\bcssText\b', r'\b(?:claude|haiku|sonnet|opus)\b']
MOTION = re.compile(r'(?<![\w-])(?:animation|transition)(?:-[a-z-]+)?\s*:', re.IGNORECASE)
VALID = {
    'schema': 'simplicio.dashboard-extras/v1',
    'last_command': {'command': 'pytest tests/x.py -q', 'kind': 'test', 'at': '2026-10-08T10:00:00Z'},
    'tasks': [{'task_id': 'T1', 'title': 'Primeira tarefa'}, {'task_id': 'T2', 'title': 'Segunda'}],
    'models': [{'lane': 'coder', 'model': 'm-1', 'input_tokens': 1200, 'output_tokens': 300}],
    'heartbeat': {'state': 'UNVERIFIED', 'reason': 'lease sem batimento medido'},
}
NO_DATA = {'schema': 'simplicio.dashboard-extras/v1', 'last_command': None, 'tasks': [], 'models': [], 'heartbeat': None}


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


def _run(script, payload):
    proc = subprocess.run([_node(), '--input-type=module', '-e', script], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


EXTRAS_SCRIPT = '''
import fs from 'node:fs';
import { extrasOf } from %s;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(extrasOf(input.reply)));
'''

START_SCRIPT = '''
import fs from 'node:fs';
import { startExtras } from %s;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const calls = { paths: [], intervals: [] };
let tick = null;
globalThis.setInterval = (fn, ms) => { calls.intervals.push(ms); tick = fn; return 1; };
function element(tag) {
  return { tag, children: [], dataset: {}, textContent: '',
    append(...items) { this.children.push(...items); },
    replaceChildren(...items) { this.children = items; } };
}
const section = element('section');
globalThis.document = { getElementById: (id) => (id === 'live-extras' ? section : null), createElement: element };
const replies = input.replies.slice();
const readApi = async (path) => {
  calls.paths.push(path);
  const next = replies.shift();
  return next === undefined ? null : next;
};
const flat = (node) => (node.children.length ? node.children.map(flat).join('') : node.textContent);
const renders = [];
startExtras(readApi, input.runId);
renders.push(flat(section));
await new Promise((resolve) => setImmediate(resolve));
renders.push(flat(section));
const tags = section.children.map((child) => child.tag);
for (let i = 0; i < input.ticks; i += 1) {
  await tick();
  renders.push(flat(section));
}
process.stdout.write(JSON.stringify({ paths: calls.paths, intervals: calls.intervals, renders, tags }));
'''


def _extras_of(reply):
    return _run(EXTRAS_SCRIPT % json.dumps(MODULE.as_uri()), {'reply': reply})


def _start(run_id, replies, ticks=0):
    return _run(START_SCRIPT % json.dumps(MODULE.as_uri()), {'runId': run_id, 'replies': replies, 'ticks': ticks})


def _all_unverified(rows):
    return [row['state'] for row in rows] == ['UNVERIFIED'] * 4 and [row['label'] for row in rows] == LABELS


def test_the_extras_module_exports_the_contract():
    text = MODULE.read_text(encoding='utf-8')
    for name in ('extrasOf', 'startExtras'):
        assert re.search(r'export\s+(?:const|let|function)\s+%s\b' % name, text), name


def test_a_missing_reply_leaves_every_row_unverified_with_its_reason():
    assert _extras_of(None) == [
        {'label': LABELS[0], 'state': 'UNVERIFIED', 'text': 'nenhum teste ou lint medido'},
        {'label': LABELS[1], 'state': 'UNVERIFIED', 'text': 'task-contract.json sem tarefas'},
        {'label': LABELS[2], 'state': 'UNVERIFIED', 'text': 'sem token_usage medido'},
        {'label': LABELS[3], 'state': 'UNVERIFIED', 'text': 'sem batimento do lease medido'},
    ]


@pytest.mark.parametrize('reply', ['texto', 42, [], dict(VALID, schema='simplicio.other/v1')])
def test_a_foreign_or_malformed_reply_is_all_unverified(reply):
    assert _all_unverified(_extras_of(reply))


def test_a_valid_reply_shows_the_measured_rows():
    assert _extras_of(VALID) == [
        {'label': LABELS[0], 'state': 'PASS', 'text': 'pytest tests/x.py -q (test)'},
        {'label': LABELS[1], 'state': 'PASS', 'text': 'T1: Primeira tarefa; T2: Segunda'},
        {'label': LABELS[2], 'state': 'PASS', 'text': 'coder: m-1, entrada 1200, saída 300'},
        {'label': LABELS[3], 'state': 'UNVERIFIED', 'text': 'lease sem batimento medido'},
    ]


@pytest.mark.parametrize('changes, index, state, text', [
    ({'last_command': None}, 0, 'UNVERIFIED', 'nenhum teste ou lint medido'),
    ({'last_command': {'command': '', 'kind': 'lint'}}, 0, 'UNVERIFIED', 'nenhum teste ou lint medido'),
    ({'last_command': {'command': 'ruff check .'}}, 0, 'PASS', 'ruff check .'),
    ({'tasks': []}, 1, 'UNVERIFIED', 'task-contract.json sem tarefas'),
    ({'tasks': 'T1'}, 1, 'UNVERIFIED', 'task-contract.json sem tarefas'),
    ({'tasks': [{'title': 'sem id'}, 'x']}, 1, 'UNVERIFIED', 'task-contract.json sem tarefas'),
    ({'tasks': [{'task_id': 'T1', 'title': 'A'}, {'title': 'sem id'}]}, 1, 'PASS', 'T1: A'),
    ({'models': []}, 2, 'UNVERIFIED', 'sem token_usage medido'),
    ({'models': [{'lane': 'coder', 'model': 'm-1', 'input_tokens': 1}]}, 2, 'UNVERIFIED', 'sem token_usage medido'),
    ({'models': [{'lane': 'coder', 'model': 'm-1', 'input_tokens': '1', 'output_tokens': 2}]}, 2, 'UNVERIFIED',
     'sem token_usage medido'),
    ({'heartbeat': None}, 3, 'UNVERIFIED', 'sem batimento do lease medido'),
    ({'heartbeat': {'state': 'PASS', 'reason': 'batimento há 3 s'}}, 3, 'PASS', 'batimento há 3 s'),
    ({'heartbeat': {'state': 'STALLED', 'reason': 'sem batimento'}}, 3, 'UNVERIFIED', 'sem batimento'),
])
def test_each_row_turns_pass_only_on_a_measured_value(changes, index, state, text):
    row = _extras_of(dict(VALID, **changes))[index]
    assert (row['state'], row['text']) == (state, text)


def test_start_polls_the_run_extras_every_3000_ms():
    out = _start('run-1', [VALID])
    assert out['paths'] == ['/api/runs/run-1/extras']
    assert out['intervals'] == [3000]


def test_the_run_id_is_encoded_in_the_path():
    assert _start('a b/c', [None])['paths'][0] == '/api/runs/a%20b%2Fc/extras'


def test_without_a_run_id_nothing_is_requested_or_polled():
    out = _start('', [VALID])
    assert out['paths'] == [] and out['intervals'] == []


def test_the_panel_shows_every_row_unverified_before_the_first_reply():
    out = _start('run-1', [None])
    assert 'UNVERIFIED' in out['renders'][0] and 'nenhum teste ou lint medido' in out['renders'][0]


def test_the_render_is_a_definition_list_under_the_section_heading():
    assert _start('run-1', [VALID])['tags'] == ['h2', 'dl']


def test_a_reply_renders_its_state_words_and_texts():
    out = _start('run-1', [VALID])
    assert 'PASS' in out['renders'][1] and 'pytest tests/x.py -q (test)' in out['renders'][1]


def test_a_failed_read_keeps_the_last_render():
    out = _start('run-1', [VALID, None], ticks=1)
    assert out['renders'][2] == out['renders'][1]


def test_a_later_reply_replaces_the_render():
    out = _start('run-1', [VALID, NO_DATA], ticks=1)
    assert 'pytest tests/x.py' not in out['renders'][2] and 'nenhum teste ou lint medido' in out['renders'][2]


@pytest.mark.parametrize('path', [MODULE, STYLE])
@pytest.mark.parametrize('pattern', FORBIDDEN)
def test_extras_sources_avoid_innerhtml_eval_inline_styles_absolute_urls_and_model_names(path, pattern):
    assert re.search(pattern, path.read_text(encoding='utf-8'), flags=re.IGNORECASE) is None, (path.name, pattern)


def test_extras_css_has_no_motion_at_all():
    assert MOTION.search(STYLE.read_text(encoding='utf-8')) is None


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.order = []
        self.by_id = {}
        self.stylesheets = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        data = {name: value for name, value in attrs}
        if tag == 'link' and 'stylesheet' in (data.get('rel') or '').split():
            self.stylesheets.append(data.get('href'))
        if tag == 'script':
            self.scripts.append(data.get('src'))
        if data.get('id'):
            self.order.append(data['id'])
            self.by_id.setdefault(data['id'], (tag, data))


def _index():
    page = _Page()
    page.feed((LIVE / 'index.html').read_text(encoding='utf-8'))
    return page


def test_the_extras_section_sits_between_the_agora_and_the_gates_panels():
    page = _index()
    assert 'live-extras' in page.by_id, 'missing #live-extras'
    tag, data = page.by_id['live-extras']
    assert tag == 'section' and data.get('aria-label') == 'Sinais do worker', data
    assert page.order.index('agora') < page.order.index('live-extras') < page.order.index('gates')


def test_the_page_links_the_extras_stylesheet_and_no_new_script():
    page = _index()
    assert page.stylesheets.count('/static/extras/extras.css') == 1, page.stylesheets
    assert page.scripts == ['/static/i18n/i18n.js', '/static/live/app.js'], page.scripts


def test_the_app_imports_startextras_and_starts_it_inside_the_token_block():
    text = (LIVE / 'app.js').read_text(encoding='utf-8')
    assert text.count("import { startExtras } from '/static/extras/extras.js';") == 1
    start = text.index('function start() {')
    call = text.index('startExtras(readApi, runId);')
    assert start < call < text.index('if (!token || !runId)', start)
    assert text.index('if (token) {', start) < call
