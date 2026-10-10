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
LABELS = ['Último comando medido', 'Comando em execução', 'Contrato por tarefa', 'Modelo por lane', 'Batimento do lease', 'Agentes por etapa',
          'Custo do run']
# A bar width goes through the CSSOM (style.setProperty('width', ...)), which the CSP style-src 'self' allows. Nothing else
# may touch a style (attribute, assignment, index, cssText, Object.assign, another property), and no markup is parsed.
FORBIDDEN = [r'\binnerHTML\b', r'\bouterHTML\b', r'\binsertAdjacentHTML\b', r'\bdocument\s*\.\s*write', r'\beval\s*\(',
             r'https?://', r'setAttribute\(\s*.style', r'\.style\s*=', r'\.style\s*\.(?!setProperty\()', r'\.style\s*\[',
             r'\.style\s*\?\.', r'\bstyle\s*\[', r'Object\s*\.\s*assign\s*\([^)]*style', r"setProperty\(\s*(?!'width',)",
             r'\bcssText\b', r'\b(?:claude|haiku|sonnet|opus)\b', r"\[\s*['\"]style['\"]\s*\]",
             r'\{[^}]*\bstyle\b[^}]*\}\s*=', r'\bsetAttributeNS\b', r'\binsertAdjacentElement\b',
             r'\bcreateContextualFragment\b', r'\bDOMParser\b', r'\bsrcdoc\b', r'\b(?:setHTML|setHTMLUnsafe|parseHTMLUnsafe)\b']
MOTION = re.compile(r'(?<![\w-])(?:animation|transition)(?:-[a-z-]+)?\s*:', re.IGNORECASE)
VALID = {
    'schema': 'simplicio.dashboard-extras/v1',
    'last_command': {'command': 'pytest tests/x.py -q', 'kind': 'test', 'at': '2026-10-08T10:00:00Z'},
    'running_command': {'state': 'PASS', 'reason': 'lane-a: em execução há 12 s: pytest -q', 'lanes': []},
    'tasks': [{'task_id': 'T1', 'title': 'Primeira tarefa'}, {'task_id': 'T2', 'title': 'Segunda'}],
    'models': [{'lane': 'coder', 'model': 'm-1', 'input_tokens': 1200, 'output_tokens': 300}],
    'heartbeat': {'state': 'UNVERIFIED', 'reason': 'lease sem batimento medido'},
}
STAGES = {
    'schema': 'simplicio.dashboard-stage-agents/v1',
    'rows': [
        {'phase': 'planning', 'role': 'planning', 'effort': 'high', 'model': 'm-a', 'tokens_in': 1000, 'tokens_out': 200,
         'cost_usd': 0.0123, 'cost_state': 'ESTIMADO', 'proof_kind': 'estimado', 'reason': None},
        {'phase': 'executing', 'role': None, 'effort': None, 'model': 'm-b', 'tokens_in': 50, 'tokens_out': 5,
         'cost_usd': None, 'cost_state': 'UNVERIFIED', 'proof_kind': 'estimado', 'reason': 'modelo sem preço'},
    ],
    'cost': {'usd': 0.0123, 'state': 'ESTIMADO', 'proof_kind': 'estimado', 'reason': None},
}
NO_STAGES = {'schema': 'simplicio.dashboard-stage-agents/v1', 'rows': [],
             'cost': {'usd': None, 'state': 'UNVERIFIED', 'proof_kind': 'estimado', 'reason': 'tokens não medidos'}}
NO_DATA = {'schema': 'simplicio.dashboard-extras/v1', 'last_command': None, 'running_command': None, 'tasks': [], 'models': [], 'heartbeat': None}


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
process.stdout.write(JSON.stringify(extrasOf(input.reply, input.stages)));
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


def _extras_of(reply, stages=None):
    return _run(EXTRAS_SCRIPT % json.dumps(MODULE.as_uri()), {'reply': reply, 'stages': stages})


def _start(run_id, replies, ticks=0):
    return _run(START_SCRIPT % json.dumps(MODULE.as_uri()), {'runId': run_id, 'replies': replies, 'ticks': ticks})


def _all_unverified(rows):
    return [row['state'] for row in rows] == ['UNVERIFIED'] * 7 and [row['label'] for row in rows] == LABELS


def test_the_extras_module_exports_the_contract():
    text = MODULE.read_text(encoding='utf-8')
    for name in ('extrasOf', 'startExtras'):
        assert re.search(r'export\s+(?:const|let|function)\s+%s\b' % name, text), name


def test_a_missing_reply_leaves_every_row_unverified_with_its_reason():
    assert _extras_of(None) == [
        {'label': LABELS[0], 'state': 'UNVERIFIED', 'text': 'nenhum teste ou lint medido'},
        {'label': LABELS[1], 'state': 'UNVERIFIED', 'text': 'nenhum command_started medido'},
        {'label': LABELS[2], 'state': 'UNVERIFIED', 'text': 'task-contract.json sem tarefas'},
        {'label': LABELS[3], 'state': 'UNVERIFIED', 'text': 'sem token_usage medido'},
        {'label': LABELS[4], 'state': 'UNVERIFIED', 'text': 'sem batimento do lease medido'},
        {'label': LABELS[5], 'state': 'UNVERIFIED', 'text': 'sem token_usage por etapa medido'},
        {'label': LABELS[6], 'state': 'UNVERIFIED', 'text': 'custo do run não estimado'},
    ]


@pytest.mark.parametrize('reply', ['texto', 42, [], dict(VALID, schema='simplicio.other/v1')])
def test_a_foreign_or_malformed_reply_is_all_unverified(reply):
    assert _all_unverified(_extras_of(reply))


def test_a_valid_reply_shows_the_measured_rows():
    assert _extras_of(VALID)[:5] == [
        {'label': LABELS[0], 'state': 'PASS', 'text': 'pytest tests/x.py -q (test)'},
        {'label': LABELS[1], 'state': 'PASS', 'text': 'lane-a: em execução há 12 s: pytest -q'},
        {'label': LABELS[2], 'state': 'PASS', 'text': 'T1: Primeira tarefa; T2: Segunda'},
        {'label': LABELS[3], 'state': 'PASS', 'text': 'coder: m-1, entrada 1200, saída 300'},
        {'label': LABELS[4], 'state': 'UNVERIFIED', 'text': 'lease sem batimento medido'},
    ]


def test_the_stage_rows_list_role_model_tokens_and_cost_as_estimates_and_the_run_cost_is_visible():
    rows = _extras_of(VALID, STAGES)
    assert rows[5] == {'label': LABELS[5], 'state': 'ESTIMADO', 'text': (
        'planning: planning/high (padrão da tabela) m-a, entrada 1000, saída 200, US$ 0.0123 estimado; '
        'executing: sem papel m-b, entrada 50, saída 5, custo UNVERIFIED (modelo sem preço)')}
    assert rows[6] == {'label': LABELS[6], 'state': 'ESTIMADO', 'text': 'US$ 0.0123 estimado'}


def test_a_stage_reply_without_rows_stays_unverified_with_the_cost_reason():
    rows = _extras_of(VALID, NO_STAGES)
    assert (rows[5]['state'], rows[5]['text']) == ('UNVERIFIED', 'sem token_usage por etapa medido')
    assert (rows[6]['state'], rows[6]['text']) == ('UNVERIFIED', 'tokens não medidos')


@pytest.mark.parametrize('stages', ['x', 7, [], dict(STAGES, schema='simplicio.other/v1')])
def test_a_foreign_stage_reply_is_unverified(stages):
    assert [row['state'] for row in _extras_of(VALID, stages)[5:]] == ['UNVERIFIED', 'UNVERIFIED']


@pytest.mark.parametrize('changes, index, state, text', [
    ({'last_command': None}, 0, 'UNVERIFIED', 'nenhum teste ou lint medido'),
    ({'last_command': {'command': '', 'kind': 'lint'}}, 0, 'UNVERIFIED', 'nenhum teste ou lint medido'),
    ({'last_command': {'command': 'ruff check .'}}, 0, 'PASS', 'ruff check .'),
    ({'running_command': None}, 1, 'UNVERIFIED', 'nenhum command_started medido'),
    ({'running_command': {'state': 'PASS', 'reason': ''}}, 1, 'UNVERIFIED', 'nenhum command_started medido'),
    ({'running_command': {'state': 'UNVERIFIED', 'reason': 'nenhum command_started no run'}}, 1, 'UNVERIFIED', 'nenhum command_started no run'),
    ({'running_command': {'state': 'STALLED', 'reason': 'x'}}, 1, 'UNVERIFIED', 'x'),
    ({'running_command': {'state': 'PASS', 'reason': 'nenhum comando em execução segundo os eventos'}}, 1, 'PASS', 'nenhum comando em execução segundo os eventos'),
    ({'tasks': []}, 2, 'UNVERIFIED', 'task-contract.json sem tarefas'),
    ({'tasks': 'T1'}, 2, 'UNVERIFIED', 'task-contract.json sem tarefas'),
    ({'tasks': [{'title': 'sem id'}, 'x']}, 2, 'UNVERIFIED', 'task-contract.json sem tarefas'),
    ({'tasks': [{'task_id': 'T1', 'title': 'A'}, {'title': 'sem id'}]}, 2, 'PASS', 'T1: A'),
    ({'models': []}, 3, 'UNVERIFIED', 'sem token_usage medido'),
    ({'models': [{'lane': 'coder', 'model': 'm-1', 'input_tokens': 1}]}, 3, 'UNVERIFIED', 'sem token_usage medido'),
    ({'models': [{'lane': 'coder', 'model': 'm-1', 'input_tokens': '1', 'output_tokens': 2}]}, 3, 'UNVERIFIED',
     'sem token_usage medido'),
    ({'heartbeat': None}, 4, 'UNVERIFIED', 'sem batimento do lease medido'),
    ({'heartbeat': {'state': 'PASS', 'reason': 'batimento há 3 s'}}, 4, 'PASS', 'batimento há 3 s'),
    ({'heartbeat': {'state': 'STALLED', 'reason': 'sem batimento'}}, 4, 'UNVERIFIED', 'sem batimento'),
])
def test_each_row_turns_pass_only_on_a_measured_value(changes, index, state, text):
    row = _extras_of(dict(VALID, **changes))[index]
    assert (row['state'], row['text']) == (state, text)


def test_start_polls_the_run_extras_and_stage_agents_every_3000_ms():
    out = _start('run-1', [VALID, STAGES])
    assert out['paths'] == ['/api/runs/run-1/extras', '/api/runs/run-1/stage-agents']
    assert 'planning: planning/high (padrão da tabela) m-a' in out['renders'][1] and 'US$ 0.0123 estimado' in out['renders'][1]
    assert out['intervals'] == [3000]


def test_the_run_id_is_encoded_in_the_path():
    assert _start('a b/c', [None, None])['paths'] == ['/api/runs/a%20b%2Fc/extras', '/api/runs/a%20b%2Fc/stage-agents']


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
    out = _start('run-1', [VALID, STAGES, None, None], ticks=1)
    assert out['renders'][2] == out['renders'][1]


def test_a_later_reply_replaces_the_render():
    out = _start('run-1', [VALID, STAGES, NO_DATA, NO_STAGES], ticks=1)
    assert 'pytest tests/x.py' not in out['renders'][2] and 'nenhum teste ou lint medido' in out['renders'][2]
    assert 'US$ 0.0123' not in out['renders'][2] and 'tokens não medidos' in out['renders'][2]


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
    assert text.count("import { startBudget, startExtras } from '/static/extras/extras.js';") == 1
    start = text.index('function start() {')
    call = text.index('startExtras(readApi, runId);')
    assert start < call < text.index('if (!token || !runId)', start)
    assert text.index('if (token) {', start) < call


# --- issue #1550: stacked bars, per task/iteration cost, agent map and the token sparkline --------------------------------
HOSTILE = '<img src=x onerror=alert(1)>'


def _bd_row(key, tokens=None, cost=None, state='ESTIMADO', reason=None, source=None, tokens_in=0, tokens_out=0, others=None):
    row = {'key': key, 'tokens_in': tokens_in, 'tokens_out': tokens_out, 'tokens': tokens, 'tokens_proof_kind': 'medido',
            'cost_usd': cost, 'cost_state': state if cost is not None else 'UNVERIFIED', 'proof_kind': 'estimado',
            'reason': reason, 'source': source}
    if others is not None:
        row['others'] = others
    return row


def _stages(total=300, **breakdown):
    empty = {name: [] for name in ('by_phase', 'by_lane', 'by_model', 'by_task', 'by_iteration')}
    tokens = {'total': total, 'state': 'PASS' if total else 'UNVERIFIED', 'proof_kind': 'medido',
              'reason': None if total else 'tokens do provedor não medidos: nenhum token_usage no run'}
    return dict(STAGES, breakdown=dict(empty, tokens=tokens, **breakdown),
                agent_map={'state': 'UNVERIFIED', 'reason': 'nenhum worker_claimed no run', 'lanes': [],
                           'slots': {'state': 'UNVERIFIED', 'reason': 'slots não medidos'}})


BD = _stages(
    by_phase=[_bd_row('planning', 100), _bd_row('executing', 200)],
    by_lane=[_bd_row('coder', 250), _bd_row(None, 50)],
    by_model=[_bd_row('m-a', 300)],
    by_task=[_bd_row('T1', 100, 0.25), _bd_row('T2', 200, 0.75), _bd_row('T3', 5, None, reason='sem preço na tabela')],
    by_iteration=[_bd_row(1, 100, 0.4, source='evento'), _bd_row(2, 200, 0.6, source='ordem dos eventos'), _bd_row(None, 1)],
)

WIDGETS_SCRIPT = '''
import fs from 'node:fs';
import { widgetsOf } from %s;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(widgetsOf(input.stages)));
'''

HELPERS_SCRIPT = '''
import fs from 'node:fs';
import { percentOf, pushPoint } from %s;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify({ pct: input.pairs.map(([a, b]) => percentOf(a, b)),
  history: input.series.reduce((h, v) => pushPoint(h, v), []) }));
'''

DOM_SCRIPT = '''
import fs from 'node:fs';
import { startExtras } from %s;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
let tick = null;
globalThis.setInterval = (fn) => { tick = fn; return 1; };
const made = [];
function element(tag) {
  const node = { tag, children: [], dataset: {}, textContent: '', className: '', attrs: {}, props: {},
    style: { setProperty(name, value) { node.props[name] = value; } },
    setAttribute(name, value) { node.attrs[name] = String(value); },
    append(...items) { this.children.push(...items); },
    replaceChildren(...items) { this.children = items; } };
  made.push(node);
  return node;
}
const section = element('section');
globalThis.document = { getElementById: (id) => (id === 'live-extras' ? section : null), createElement: element };
const replies = input.replies.slice();
const readApi = async () => { const next = replies.shift(); return next === undefined ? null : next; };
startExtras(readApi, 'run-1');
await new Promise((resolve) => setImmediate(resolve));
for (let i = 0; i < input.ticks; i += 1) await tick();
const plain = (node) => ({ tag: node.tag, className: node.className, text: node.textContent, attrs: node.attrs,
  props: node.props, state: node.dataset.state, children: node.children.map(plain) });
process.stdout.write(JSON.stringify(plain(section)));
'''


def _widgets(stages):
    return _run(WIDGETS_SCRIPT % json.dumps(MODULE.as_uri()), {'stages': stages})


def _dom(replies, ticks=0):
    return _run(DOM_SCRIPT % json.dumps(MODULE.as_uri()), {'replies': replies, 'ticks': ticks})


def _walk(node):
    yield node
    for child in node['children']:
        yield from _walk(child)


def _widget(stages, label):
    [found] = [w for w in _widgets(stages) if w['label'] == label]
    return found


def test_an_older_reply_without_a_breakdown_adds_no_widget():
    assert _widgets(STAGES) == [] and _widgets(None) == []


def test_tokens_by_phase_become_a_stacked_bar_with_clamped_percent_widths():
    widget = _widget(BD, 'Tokens por fase')
    assert widget['state'] == 'PASS'
    assert [(seg['text'], round(seg['pct'], 2)) for seg in widget['segments']] == [
        ('planning: 100', 33.33), ('executing: 200', 66.67)]
    assert all(0 <= seg['pct'] <= 100 for seg in widget['segments'])


def test_lane_and_model_widgets_name_the_missing_key_instead_of_hiding_it():
    lanes = _widget(BD, 'Tokens por lane')
    assert [seg['text'] for seg in lanes['segments']] == ['coder: 250', 'sem lane: 50']
    assert [seg['text'] for seg in _widget(BD, 'Tokens por modelo')['segments']] == ['m-a: 300']


def test_a_breakdown_with_no_measured_tokens_is_unverified_with_the_server_reason_and_has_no_bar():
    widget = _widget(_stages(total=None), 'Tokens por fase')
    assert widget['state'] == 'UNVERIFIED' and widget['segments'] == []
    assert widget['text'] == 'tokens do provedor não medidos: nenhum token_usage no run'


def test_the_agent_map_lists_lanes_claims_tasks_and_leases_and_flags_slots_unverified():
    stages = _stages()
    stages['agent_map'] = {'state': 'PASS', 'reason': None, 'slots': {'state': 'UNVERIFIED', 'reason': 'slots não medidos'},
                           'lanes': [{'key': 'coder', 'claims': 2, 'tasks': ['T1', 'T2'], 'lease_ids': ['L1'], 'branches': [],
                                      'state': 'PASS', 'proof_kind': 'medido', 'lease_reason': None},
                                     {'key': None, 'claims': 1, 'tasks': ['T3'], 'lease_ids': [], 'branches': [],
                                      'state': 'PASS', 'proof_kind': 'medido', 'lease_reason': 'worker_claimed sem lease_id'}]}
    widget = _widget(stages, 'Mapa de agentes')
    assert widget['state'] == 'PASS'
    assert [item['text'] for item in widget['legend']] == [
        'coder: 2 claims, tarefas T1, T2, leases L1',
        'sem lane: 1 claims, tarefas T3, lease UNVERIFIED (worker_claimed sem lease_id)',
        'slots UNVERIFIED (slots não medidos)']


def test_an_agent_map_without_claims_is_unverified_with_the_reason():
    widget = _widget(_stages(), 'Mapa de agentes')
    assert widget['state'] == 'UNVERIFIED' and widget['text'] == 'nenhum worker_claimed no run'


def test_percent_is_clamped_between_0_and_100():
    out = _run(HELPERS_SCRIPT % json.dumps(MODULE.as_uri()), {
        'pairs': [[5, 2], [-3, 10], [1, 0], [None, 4], [1, 4], [4, 4], ['a', 4]], 'series': []})
    assert out['pct'] == [100, 0, 0, 0, 25, 100, 0]


def test_the_sparkline_history_is_bounded_to_60_points():
    out = _run(HELPERS_SCRIPT % json.dumps(MODULE.as_uri()), {'pairs': [], 'series': list(range(100))})
    assert out['history'] == list(range(40, 100)) and len(out['history']) == 60


def test_bars_set_only_a_percent_width_and_the_legend_text_is_text_content():
    tree = _dom([VALID, BD])
    segments = [n for n in _walk(tree) if 'extras-seg' in n['className'].split()]
    assert segments, 'no stacked bar segment was rendered'
    for node in segments:
        assert set(node['props']) == {'width'} and 0 <= float(node['props']['width'].rstrip('%')) <= 100
        assert node['props']['width'].endswith('%') and node['text'] == ''
    assert any(n['tag'] == 'ul' for n in _walk(tree))
    assert 'planning: 100' in [n['text'] for n in _walk(tree)]


def test_the_sparkline_is_fed_the_polled_token_totals_and_never_grows_past_60_points():
    totals = [_stages(total=value, by_phase=[_bd_row('planning', value)]) for value in range(1, 80)]
    replies = []
    for stages in totals:
        replies += [VALID, stages]
    tree = _dom(replies, ticks=78)
    [spark] = [n for n in _walk(tree) if n['tag'] == 'sl-sparkline']
    values = spark['attrs']['values'].split(',')
    assert len(values) == 60 and values[-1] == '79' and values[0] == '20'
    assert set(spark['attrs']) == {'values', 'label'}


def test_hostile_model_phase_lane_and_task_names_stay_inert_text():
    stages = _stages(
        by_phase=[_bd_row(HOSTILE, 100, 0.5)], by_lane=[_bd_row(HOSTILE, 100)], by_model=[_bd_row(HOSTILE, 100, 0.5)],
        by_task=[_bd_row(HOSTILE, 100, 0.5)], by_iteration=[_bd_row(1, 100, 0.5, source=HOSTILE)])
    stages['agent_map'] = {'state': 'PASS', 'reason': None, 'slots': {'state': 'UNVERIFIED', 'reason': HOSTILE},
                           'lanes': [{'key': HOSTILE, 'claims': 1, 'tasks': [HOSTILE], 'lease_ids': [HOSTILE],
                                      'branches': [], 'state': 'PASS', 'proof_kind': 'medido', 'lease_reason': None}]}
    stages['breakdown']['tokens']['reason'] = HOSTILE
    tree = _dom([VALID, stages])
    nodes = list(_walk(tree))
    assert {n['tag'] for n in nodes} <= {'section', 'h2', 'dl', 'div', 'dt', 'dd', 'span', 'ul', 'li', 'sl-sparkline'}
    assert any(HOSTILE in n['text'] for n in nodes), 'the hostile name must be visible as text'
    for node in nodes:
        assert node['children'] == [] or node['text'] == '', node['tag']
        assert 'onerror' not in json.dumps(node['attrs']) and 'onerror' not in json.dumps(node['props'])


def test_hostile_running_command_text_stays_inert():
    reply = dict(VALID, running_command={'state': 'PASS', 'reason': 'lane-a: em execucao ha 3 s: ' + HOSTILE + ' <script>alert(2)</script> javascript:alert(3) " onmouseover="x'})
    tree = _dom([reply, None])
    nodes = list(_walk(tree))
    assert {n['tag'] for n in nodes} <= {'section', 'h2', 'dl', 'div', 'dt', 'dd', 'span', 'ul', 'li', 'sl-sparkline'}
    assert any(HOSTILE in n['text'] for n in nodes), 'the hostile running_command reason must be visible as text'
    for node in nodes:
        assert node['children'] == [] or node['text'] == '', node['tag']
        assert 'onerror' not in json.dumps(node['attrs']) and 'onerror' not in json.dumps(node['props'])
        assert 'onmouseover' not in json.dumps(node['attrs']) and 'onmouseover' not in json.dumps(node['props'])


# --- D4: aggregate rows (top 20 + outros) and partial cost ---------------------------------------------------------------
def test_aggregate_rows_with_others_field_render_as_outros():
    """Server caps at 20 rows + 1 aggregate; client must recognize and format them."""
    stages = _stages(
        by_lane=[_bd_row('coder', 250), _bd_row('runner', 100), _bd_row(None, 50, others=7)]
    )
    widget = _widget(stages, 'Tokens por lane')
    # others=7 means 7 groups were folded; the aggregate row should render as "outros (7): 50"
    assert any('outros (7)' in seg['text'] for seg in widget['segments']), widget['segments']


def test_aggregate_row_in_agent_map_lanes():
    """Agent map with aggregate row."""
    stages = _stages()
    stages['agent_map'] = {
        'state': 'PASS', 'reason': None,
        'slots': {'state': 'PASS', 'reason': None},
        'lanes': [
            {'key': 'coder', 'claims': 2, 'tasks': ['T1', 'T2'], 'lease_ids': ['L1'], 'branches': [],
             'state': 'PASS', 'proof_kind': 'medido', 'lease_reason': None},
            {'key': None, 'claims': 9, 'others': 4, 'tasks': [], 'lease_ids': [], 'branches': [],
             'state': 'PASS', 'proof_kind': 'medido', 'lease_reason': None}
        ]
    }
    widget = _widget(stages, 'Mapa de agentes')
    # Should show "outros (4): 9 claims"
    assert any('outros (4)' in item['text'] and '9 claims' in item['text'] for item in widget['legend']), widget['legend']


def test_tasks_total_and_lease_ids_total_suffix():
    """When tasks_total > len(tasks), show (+K) suffix; same for lease_ids."""
    stages = _stages()
    stages['agent_map'] = {
        'state': 'PASS', 'reason': None,
        'slots': {'state': 'PASS', 'reason': None},
        'lanes': [
            {'key': 'coder', 'claims': 5, 'tasks': ['T1', 'T2'], 'tasks_total': 5,
             'lease_ids': ['L1'], 'lease_ids_total': 4, 'branches': [],
             'state': 'PASS', 'proof_kind': 'medido', 'lease_reason': None},
        ]
    }
    widget = _widget(stages, 'Mapa de agentes')
    assert widget['legend'][0]['text'] == 'coder: 5 claims, tarefas T1, T2 (+3), leases L1 (+3)'


def test_1000_rows_limited_to_max_rows_plus_aggregate():
    """1,000 rows must be folded to at most 21 (20 + 1 aggregate)."""
    many_rows = [_bd_row(f'phase_{i}', i) for i in range(1000)]
    stages = _stages(by_phase=many_rows)
    widget = _widget(stages, 'Tokens por fase')
    # Should have <= 21 segments (20 normal + 1 aggregate) + legend items
    assert len(widget['segments']) <= 21, f"expected <= 21 segments, got {len(widget['segments'])}"
    assert len(widget['legend']) <= 21, f"expected <= 21 legend items, got {len(widget['legend'])}"
    # Percentages should sum to ~100
    pct_sum = sum(seg['pct'] for seg in widget['segments'])
    assert 99 < pct_sum < 101, f"segments pct sum {pct_sum} not ~100"
    # Should have an "outros" entry
    assert any('outros' in seg['text'] for seg in widget['segments']), widget['segments']


HUGE_SCRIPT = '''
import fs from 'node:fs';
import { startExtras } from %s;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
let made = 0;
globalThis.setInterval = () => 1;
function element(tag) {
  made += 1;
  return { tag, children: [], dataset: {}, textContent: '', className: '', style: { setProperty() {} }, setAttribute() {},
    append(...items) { for (const item of items) this.children.push(item); },
    replaceChildren(...items) { this.children = items; } };
}
const section = element('section');
globalThis.document = { getElementById: () => section, createElement: element };
const n = input.count;
const row = (key) => ({ key, tokens_in: 1, tokens_out: 1, tokens: 2, tokens_proof_kind: 'medido', cost_usd: 0.001,
  cost_state: 'ESTIMADO', proof_kind: 'estimado', reason: null, source: null });
const many = (prefix) => Array.from({ length: n }, (_, i) => row(prefix + i));
const stages = {
  schema: 'simplicio.dashboard-stage-agents/v1',
  rows: Array.from({ length: n }, (_, i) => ({ phase: 'p' + i, role: 'execution', effort: 'high', model: 'm', tokens_in: 1,
    tokens_out: 1, cost_usd: 0.001, cost_state: 'ESTIMADO', proof_kind: 'estimado', reason: null })),
  cost: { usd: 1, state: 'ESTIMADO', proof_kind: 'estimado', reason: null },
  breakdown: { by_phase: many('p'), by_lane: many('l'), by_model: many('m'), by_task: many('t'),
    by_iteration: Array.from({ length: n }, (_, i) => row(i)),
    tokens: { total: 2 * n, state: 'PASS', proof_kind: 'medido', reason: null } },
  agent_map: { state: 'PASS', reason: null, slots: { state: 'UNVERIFIED', reason: 'slots não medidos' },
    lanes: Array.from({ length: n }, (_, i) => ({ key: 'l' + i, claims: 2, tasks: ['t' + i], lease_ids: [], branches: [],
      lease_reason: 'sem lease' })) },
};
const replies = [{ schema: 'simplicio.dashboard-extras/v1' }, stages];
const started = performance.now();
startExtras(async () => (replies.shift() ?? null), 'run-1');
await new Promise((resolve) => setImmediate(resolve));
const elapsed = performance.now() - started;
const flat = (node) => (node.children.length ? node.children.map(flat).join('\\n') : node.textContent);
process.stdout.write(JSON.stringify({ made, elapsed, text: flat(section) }));
'''


def test_a_reply_with_150000_rows_per_dimension_renders_20_rows_plus_one_others_row_without_throwing():
    out = _run(HUGE_SCRIPT % json.dumps(MODULE.as_uri()), {'count': 150_000})
    assert out['made'] < 600, out['made']
    assert out['elapsed'] < 3000, out['elapsed']
    text = out['text']
    assert '300000 tokens medidos' in text and 'outros (149980): 299960\n' in text
    assert 'US$ 1.0000 estimado' in text
    assert '150000 lanes, 300000 claims (worker_claimed)' in text and 'outros (149980): 299960 claims' in text
    assert 'outros (149980): entrada 149980, saída 149980' in text


def test_the_rows_beyond_the_cap_are_folded_with_their_tokens_cost_and_claims_summed():
    rows = [_bd_row('r%d' % i, 10, 0.5, tokens_in=6, tokens_out=4) for i in range(30)]
    stages = _stages(by_task=rows, by_lane=rows)
    tokens = _widget(stages, 'Tokens por lane')
    assert tokens['text'] == '300 tokens medidos' and tokens['segments'][-1]['text'] == 'outros (10): 100'
    assert round(tokens['segments'][-1]['pct'], 2) == 33.33
    lanes = [{'key': 'l%d' % i, 'claims': 3, 'tasks': [], 'lease_ids': ['L'], 'branches': [], 'state': 'PASS',
              'proof_kind': 'medido', 'lease_reason': None} for i in range(30)]
    stages['agent_map'] = {'state': 'PASS', 'reason': None, 'lanes': lanes, 'slots': {'state': 'UNVERIFIED', 'reason': 'r'}}
    agents = _widget(stages, 'Mapa de agentes')
    assert agents['text'] == '30 lanes, 90 claims (worker_claimed)' and agents['legend'][20]['text'] == 'outros (10): 30 claims'


def test_stage_rows_with_aggregate():
    """Stage rows with aggregate (others field) should format as 'outros (N): entrada X, saída Y, ...'"""
    stages = _stages()
    stages['rows'] = [
        {'phase': 'planning', 'role': 'role', 'effort': 'high', 'model': 'm-a', 'tokens_in': 1000, 'tokens_out': 200,
         'cost_usd': 0.01, 'cost_state': 'ESTIMADO', 'proof_kind': 'estimado', 'reason': None},
        {'phase': None, 'role': 'role', 'effort': None, 'model': 'm-b', 'tokens_in': 50, 'tokens_out': 5,
         'cost_usd': 0.001, 'cost_state': 'ESTIMADO', 'proof_kind': 'estimado', 'reason': None, 'others': 3},
    ]
    row = _extras_of(VALID, stages)[5]  # row[5] is the stages row (row[1] is the #1560 running command)
    # Should contain "outros (3): entrada 50, saída 5"
    assert 'outros (3)' in row['text'] and 'entrada 50' in row['text'], row['text']


# --- D5: the source guard catches every way to write a style or parse markup --------------------------------------------
GUARD_PROBES = [
    "el.style .width = '5%'", "el.style\n.width = '5%'", "el.style.width = '5%'", "el.style['width'] = '5%'",
    "style['width']='5%'", "el.style.cssText = 'x'", "Object.assign(el.style, {width: '5%'})",
    "el.style.setProperty('background', 'url(//x)')", 'el.style.setProperty(name, value)',
    "el.style.setProperty( 'height', '5%')", "el.insertAdjacentHTML('beforeend', x)", 'el.outerHTML = x',
    'document.write(x)', 'document . write(x)', 'el.innerHTML = x', "el.setAttribute('style', 'x')", "el.style = 'x'",
    "el.style.removeProperty('x')", 'el.style?.width', 'eval(x)', "fetch('https://x')", "fetch('http://x')",
    "el['style'].width = '5%'", 'el["style"].width = x', "const {style} = el", "const { style } = el",
    "let {style: s} = el", "el.setAttributeNS(null, 'style', 'x')", "el.insertAdjacentElement('beforeend', x)",
    "range.createContextualFragment(x)", "new DOMParser()", "iframe.srcdoc = x", "el.srcdoc",
    "el.setHTMLUnsafe(x)", "el.setHTML(x)", "Document.parseHTMLUnsafe(x)",
]
GUARD_ALLOWED = ["part.style.setProperty('width', Math.round(pct * 100) / 100 + '%');"]


@pytest.mark.parametrize('snippet', GUARD_PROBES)
def test_the_guard_catches_each_hostile_construction(snippet):
    assert any(re.search(pattern, snippet, flags=re.IGNORECASE) for pattern in FORBIDDEN), snippet


@pytest.mark.parametrize('snippet', GUARD_ALLOWED)
def test_the_guard_lets_the_clamped_width_through(snippet):
    assert [p for p in FORBIDDEN if re.search(p, snippet, flags=re.IGNORECASE)] == []


@pytest.mark.parametrize('snippet', GUARD_PROBES)
def test_each_probe_appended_to_a_copy_of_extras_js_trips_the_guard_and_the_real_file_does_not(snippet):
    real = MODULE.read_text(encoding='utf-8')
    assert [p for p in FORBIDDEN if re.search(p, real, flags=re.IGNORECASE)] == []
    probed = real + '\n' + snippet + '\n'
    assert any(re.search(pattern, probed, flags=re.IGNORECASE) for pattern in FORBIDDEN), snippet


def test_the_only_style_write_in_extras_js_is_the_literal_width():
    text = MODULE.read_text(encoding='utf-8')
    assert len(re.findall(r'\.style\b', text)) == 1 and len(re.findall(r"\.style\.setProperty\('width', ", text)) == 1


def test_the_app_starts_the_budget_poll_in_extras_with_the_reducer_dispatch_and_the_tokens_cadence():
    text = (LIVE / 'app.js').read_text(encoding='utf-8')
    assert text.count('startBudget(readApi, runId, dispatch, TOKENS_POLL_MS);') == 1
    assert 'loadBudget' not in text


def _floor_stages(**cost):
    stages = json.loads(json.dumps(STAGES))
    stages['rows'][0].update(cost_floor=True, floor_reason='piso: 1 evento acima de 100000')
    stages['cost'].update(dict(usd=0.0160, floor=True, floor_reason='piso: 1 evento(s) acima de 100000 tokens sem requests'), **cost)
    return stages


def test_a_floor_run_cost_reads_a_partir_de_with_the_reason_never_estimado():
    text = _extras_of(VALID, _floor_stages())[6]['text']
    assert text == 'a partir de US$ 0.0160 (piso: 1 evento(s) acima de 100000 tokens sem requests)'
    assert 'estimado' not in text


def test_a_floor_stage_row_reads_a_partir_de_and_an_exact_row_keeps_estimado():
    text = _extras_of(VALID, _floor_stages())[5]['text']
    assert 'planning: planning/high (padrão da tabela) m-a, entrada 1000, saída 200, a partir de US$ 0.0123;' in text
    exact = _extras_of(VALID, STAGES)
    assert 'a partir de' not in exact[5]['text'] and 'a partir de' not in exact[6]['text']


def test_cached_tokens_outside_the_usd_are_said_in_the_run_cost():
    stages = _floor_stages(unpriced_tokens={'cached_tokens': 5000, 'cache_write_tokens': 0, 'reasoning_tokens': 0})
    assert _extras_of(VALID, stages)[6]['text'].endswith('; leitura de cache não entra no USD')
    plain = json.loads(json.dumps(STAGES))
    plain['cost']['unpriced_tokens'] = {'cached_tokens': 0, 'cache_write_tokens': 0, 'reasoning_tokens': 0}
    assert _extras_of(VALID, plain)[6]['text'] == 'US$ 0.0123 estimado'
