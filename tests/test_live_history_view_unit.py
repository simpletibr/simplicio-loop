'''Unit tests for the Simplicio Live history view (history-view.js) and its stylesheet (history.css).

history-view.js builds five sections (runs, comparison, trends, activity, lessons) into one root element. Node has no DOM
here, so the view runs against a small fake DOM that records every node, attribute, property and listener. The view
imports five names from './history-model.js', which another worker writes in parallel: each test copies the view next to
a stub of that module, so the tests never need the real module.
'''
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LIVE = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'history'
VIEW = LIVE / 'history-view.js'
CSS = LIVE / 'history.css'
SVG_NS = 'http://www.w3.org/2000/svg'
MODEL_NAMES = ['rowsOf', 'heatLevels', 'trendSeries', 'deltaText', 'phaseBars']
TONES = ['running', 'pass', 'fail', 'unverified', 'stalled', 'blocked', 'pending']
SHAPES = {'running': 'play', 'pass': 'check', 'fail': 'cross', 'unverified': 'diamond', 'stalled': 'pause',
          'blocked': 'barred', 'pending': 'ring'}
RUNS, COMPARE, TRENDS, ACTIVITY, LESSONS = ('Histórico de runs', 'Comparação', 'Tendências', 'Atividade',
                                             'Lições do learn')
SECTION_TITLES = [RUNS, COMPARE, TRENDS, ACTIVITY, LESSONS]
RUN_HEADERS = ['Comparar', 'Run', 'Veredito', 'Duração', 'Iterações', 'Custo', 'Início']
DAYS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
EMPTY_RUNS = 'Nenhum run no histórico.'
NO_LESSONS = 'Nenhuma lição registrada.'
PHASE_NOTE = 'Os runs pararam em fases diferentes.'
COMPARE_PROMPT = 'Escolha dois runs na tabela para comparar.'
NO_ACTIVITY = 'Sem dados de atividade.'
SNAP = {'op': 'snapshot'}


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


STUB = '''
export function rowsOf(records) { return records; }
export function heatLevels(grid) { return grid.map((row) => row.map((v) => (v > 0 ? Math.min(4, v) : 0))); }
export function trendSeries(trends, key) {
  return { labels: trends.map((t) => t.label), values: trends.map((t) => t[key] ?? null) };
}
export function deltaText(metric, kind) { return 'Δ ' + metric.delta + ' (' + kind + ')'; }
export function phaseBars(compare) { return compare.phases; }
'''

DRIVER = '''
import fs from 'node:fs';
import { createHistory } from __VIEW__;

let uids = 0;
function detach(node) {
  const parent = node.parentNode;
  if (parent !== null) parent.childNodes.splice(parent.childNodes.indexOf(node), 1);
  node.parentNode = null;
}
class FakeNode {
  constructor() { this.childNodes = []; this.parentNode = null; this.listeners = new Map(); }
  get children() { return this.childNodes.filter((node) => node.localName !== undefined); }
  get textContent() { return this.childNodes.map((node) => node.textContent).join(''); }
  set textContent(value) { this.replaceChildren(...(value === '' ? [] : [new TextNode(String(value))])); }
  append(...nodes) { for (const node of nodes) this.insertBefore(node, null); }
  insertBefore(node, ref) {
    detach(node);
    const index = ref === null ? this.childNodes.length : this.childNodes.indexOf(ref);
    if (index < 0) throw new Error('reference node is not a child');
    this.childNodes.splice(index, 0, node);
    node.parentNode = this;
    return node;
  }
  replaceChildren(...nodes) {
    for (const child of this.childNodes) child.parentNode = null;
    this.childNodes = [];
    this.append(...nodes);
  }
  remove() { detach(this); }
  addEventListener(type, fn) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(fn);
  }
  fire(type) { for (const fn of this.listeners.get(type) ?? []) fn({ type, target: this }); }
}
class TextNode extends FakeNode {
  constructor(data) { super(); this.data = data; }
  get textContent() { return this.data; }
}
class Element extends FakeNode {
  constructor(tag, ns) {
    super();
    this.localName = tag;
    this.ns = ns;
    this.uid = ++uids;
    this.attributes = new Map();
    this.styleProps = null;
  }
  get style() {
    if (this.styleProps === null) this.styleProps = new Map();
    const props = this.styleProps;
    return { setProperty(name, value) { props.set(name, String(value)); } };
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  hasAttribute(name) { return this.attributes.has(name); }
  removeAttribute(name) { this.attributes.delete(name); }
}
globalThis.document = {
  createElement: (tag) => new Element(tag, undefined),
  createElementNS: (ns, tag) => new Element(tag, ns),
};

function snap(node) {
  if (node.localName === undefined) return { text: node.data };
  const out = { tag: node.localName, uid: node.uid, attrs: Object.fromEntries(node.attributes),
    children: node.childNodes.map(snap) };
  if (node.ns !== undefined) out.ns = node.ns;
  if (node.checked !== undefined) out.checked = node.checked;
  if (node.styleProps !== null) out.style = Object.fromEntries(node.styleProps);
  return out;
}
function find(node, pred) {
  if (node.localName !== undefined && pred(node)) return node;
  for (const child of node.childNodes) {
    const found = find(child, pred);
    if (found !== null) return found;
  }
  return null;
}

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const root = new Element('div');
const statusEl = new Element('p');
const calls = [];
const handlers = { onCompare: (a, b) => { calls.push([a, b]); } };
const history = createHistory(root, statusEl);
const results = input.ops.map((op) => {
  switch (op.op) {
    case 'render':
      history.render(op.data, handlers);
      return null;
    case 'check': {
      const box = find(root, (n) => n.localName === 'input' && n.getAttribute('aria-label') === 'Comparar ' + op.runId);
      box.checked = op.value;
      box.fire('change');
      return null;
    }
    case 'press': {
      const button = find(root, (n) => n.localName === 'button' && n.textContent === op.name);
      const disabled = button.hasAttribute('disabled');
      button.fire('click');
      return { disabled, calls: calls.length };
    }
    case 'snapshot': {
      const button = find(root, (n) => n.localName === 'button');
      return {
        tree: snap(root),
        status: statusEl.textContent,
        calls: calls.map((pair) => pair.slice()),
        compare: { text: button.textContent, disabled: button.hasAttribute('disabled') },
      };
    }
    default:
      throw new Error('unknown op ' + op.op);
  }
});
process.stdout.write(JSON.stringify(results));
'''


def _drive(tmp_path, ops):
    shutil.copy(VIEW, tmp_path / 'history-view.js')
    (tmp_path / 'history-model.js').write_text(STUB, encoding='utf-8')
    script = DRIVER.replace('__VIEW__', json.dumps((tmp_path / 'history-view.js').as_uri()))
    proc = subprocess.run([_node(), '--input-type=module', '-e', script], input=json.dumps({'ops': ops}),
                          capture_output=True, text=True, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _snapshot(tmp_path, *ops):
    return _drive(tmp_path, [*ops, SNAP])[-1]


def _snaps(tmp_path, ops):
    results = _drive(tmp_path, ops)
    return [result for op, result in zip(ops, results) if op['op'] == 'snapshot']


def _render(data):
    return {'op': 'render', 'data': data}


def _check(run_id, value=True):
    return {'op': 'check', 'runId': run_id, 'value': value}


def _press(name):
    return {'op': 'press', 'name': name}


def _row(run_id, tone='pass', verdict='Aprovado', **extra):
    row = {'runId': run_id, 'repo': 'simplicio-loop', 'verdict': verdict, 'durationText': '4 min', 'iterations': 3,
           'costText': 'US$ 0,42', 'startedAt': '2026-10-07 09:00', 'tone': tone}
    row.update(extra)
    return row


def _heat():
    grid = [[0] * 24 for _ in range(7)]
    grid[0][9] = 3
    grid[6][23] = 1
    return grid


def _compare(comparable=True):
    return {
        'comparable': comparable,
        'metrics': {'duration_s': {'a': 240, 'b': 360, 'delta': 120}},
        'phases': [
            {'phase': 'executing', 'aPct': 80, 'bPct': 40, 'aS': 'PASS', 'bS': 'FAIL'},
            {'phase': 'validating', 'aPct': 100, 'bPct': None, 'aS': 'PASS', 'bS': None},
        ],
    }


def _data(records=None, trends=None, heatmap=None, compare=None, lessons=None):
    return {'records': [] if records is None else records, 'trends': trends, 'heatmap': heatmap,
            'compare': compare, 'lessons': [] if lessons is None else lessons}


def _walk(node):
    yield node
    for child in node.get('children', []):
        yield from _walk(child)


def _all(node, pred):
    return [n for n in _walk(node) if 'tag' in n and pred(n)]


def _tag(name):
    return lambda n: n['tag'] == name


def _cls(name):
    return lambda n: name in _attrs(n).get('class', '').split()


def _one(node, pred):
    found = _all(node, pred)
    assert len(found) == 1, f'expected one match, found {len(found)}'
    return found[0]


def _section(tree, title):
    for section in _all(tree, _tag('section')):
        if _text(_one(section, _tag('h3'))) == title:
            return section
    raise AssertionError(f'no section named {title}')


def _elements(node):
    return [child for child in node.get('children', []) if 'tag' in child]


def _attrs(node):
    return node.get('attrs', {})


def _style(node):
    return node.get('style', {})


def _text(node):
    if 'text' in node:
        return node['text']
    return ''.join(_text(child) for child in node.get('children', []))


def _visible(node):
    return 'hidden' not in _attrs(node)


def _rows(section):
    return _elements(_one(section, _tag('tbody')))


def _uid(node):
    return node['uid']


def _run_row(section, run_id):
    for row in _rows(section):
        if _text(_elements(row)[1]) == run_id:
            return row
    raise AssertionError(f'no row for {run_id}')


def _box(section, run_id):
    return _one(section, lambda n: n['tag'] == 'input' and _attrs(n).get('aria-label') == 'Comparar ' + run_id)


def _lamp(row):
    return _one(row, _cls('lamp'))


def test_builds_five_sections_in_the_order_of_the_brief(tmp_path):
    snap = _snapshot(tmp_path, _render(_data()))
    titles = [_text(_one(s, _tag('h3'))) for s in _all(snap['tree'], _tag('section'))]
    assert titles == SECTION_TITLES


def test_runs_table_has_a_comparar_column_then_the_five_fields(tmp_path):
    snap = _snapshot(tmp_path, _render(_data([_row('run-1')])))
    headers = [_text(th) for th in _all(_section(snap['tree'], RUNS), _tag('th'))]
    assert headers == RUN_HEADERS


def test_each_row_has_a_comparar_checkbox_named_after_its_run(tmp_path):
    snap = _snapshot(tmp_path, _render(_data([_row('run-1'), _row('run-2')])))
    boxes = _all(_section(snap['tree'], RUNS), _tag('input'))
    assert [_attrs(b)['aria-label'] for b in boxes] == ['Comparar run-1', 'Comparar run-2']
    assert all(_attrs(b)['type'] == 'checkbox' for b in boxes)


def test_verdict_is_a_lamp_with_its_tone_class_and_a_distinct_shape_per_tone(tmp_path):
    rows = [_row(f'run-{i}', tone=tone, verdict=tone.upper()) for i, tone in enumerate(TONES)]
    snap = _snapshot(tmp_path, _render(_data(rows)))
    lamps = [_lamp(r) for r in _rows(_section(snap['tree'], RUNS))]
    assert [_attrs(lamp)['class'] for lamp in lamps] == [f'lamp lamp-{tone}' for tone in TONES]
    shapes = [_attrs(lamp)['data-shape'] for lamp in lamps]
    assert shapes == [SHAPES[tone] for tone in TONES]
    assert len(set(shapes)) == len(TONES)
    assert [_text(lamp) for lamp in lamps] == [tone.upper() for tone in TONES]


def test_a_lamp_glyph_is_hidden_from_assistive_technology(tmp_path):
    snap = _snapshot(tmp_path, _render(_data([_row('run-1')])))
    lamp = _lamp(_rows(_section(snap['tree'], RUNS))[0])
    glyph = _one(lamp, _cls('lamp-glyph'))
    assert _attrs(glyph)['aria-hidden'] == 'true'
    assert _text(glyph) == ''


def test_an_unknown_tone_shows_as_pending(tmp_path):
    snap = _snapshot(tmp_path, _render(_data([_row('run-1', tone='weird')])))
    lamp = _lamp(_rows(_section(snap['tree'], RUNS))[0])
    assert _attrs(lamp)['class'] == 'lamp lamp-pending'
    assert _attrs(lamp)['data-shape'] == 'ring'


def test_empty_history_says_so_in_the_status_line_and_fills_no_rows(tmp_path):
    empty, filled = _snaps(tmp_path, [_render(_data()), SNAP, _render(_data([_row('run-1')])), SNAP])
    assert empty['status'] == EMPTY_RUNS
    assert _rows(_section(empty['tree'], RUNS)) == []
    assert filled['status'] == ''


def test_row_fields_show_duration_iterations_cost_and_start(tmp_path):
    snap = _snapshot(tmp_path, _render(_data([_row('run-1')])))
    row = _rows(_section(snap['tree'], RUNS))[0]
    assert [_text(cell) for cell in _elements(row)[1:]] == ['run-1', 'Aprovado', '4 min', '3', 'US$ 0,42', '2026-10-07 09:00']


def test_compare_button_is_enabled_only_with_exactly_two_checked(tmp_path):
    rows = [_row('run-1'), _row('run-2'), _row('run-3')]
    results = _drive(tmp_path, [_render(_data(rows)), SNAP, _check('run-1'), SNAP, _check('run-2'), SNAP,
                                _check('run-3'), SNAP, _check('run-1', False), SNAP])
    snaps = [r for r in results if r is not None and 'tree' in r]
    assert [s['compare']['disabled'] for s in snaps] == [True, True, False, True, False]
    assert snaps[0]['compare']['text'] == 'Comparar 2 runs'


def test_compare_reports_the_two_chosen_runs_in_table_order(tmp_path):
    rows = [_row('run-1'), _row('run-2'), _row('run-3')]
    results = _drive(tmp_path, [_render(_data(rows)), _check('run-3'), _check('run-1'), _press('Comparar 2 runs'), SNAP])
    assert results[-1]['calls'] == [['run-1', 'run-3']]


def test_pressing_the_button_with_fewer_than_two_checked_compares_nothing(tmp_path):
    results = _drive(tmp_path, [_render(_data([_row('run-1'), _row('run-2')])), _check('run-1'),
                                _press('Comparar 2 runs'), SNAP])
    assert results[2]['disabled'] is True
    assert results[-1]['calls'] == []


def test_a_selected_run_that_leaves_the_history_is_no_longer_selected(tmp_path):
    results = _drive(tmp_path, [_render(_data([_row('run-1'), _row('run-2')])), _check('run-1'), _check('run-2'),
                                _render(_data([_row('run-2')])), SNAP])
    snap = results[-1]
    assert snap['compare']['disabled'] is True
    assert _box(_section(snap['tree'], RUNS), 'run-2')['checked'] is True
    assert [_text(_elements(r)[1]) for r in _rows(_section(snap['tree'], RUNS))] == ['run-2']


def test_a_rerender_keeps_every_section_row_checkbox_and_button_node(tmp_path):
    first = _data([_row('run-1'), _row('run-2')])
    later = _data([_row('run-1', tone='fail', verdict='Falhou', durationText='9 min'), _row('run-2')])
    before, after = _snaps(tmp_path, [_render(first), SNAP, _render(later), SNAP])
    for title in SECTION_TITLES:
        assert _uid(_section(after['tree'], title)) == _uid(_section(before['tree'], title)), title
    run_before = _run_row(_section(before['tree'], RUNS), 'run-1')
    run_after = _run_row(_section(after['tree'], RUNS), 'run-1')
    assert _uid(run_after) == _uid(run_before)
    assert _uid(_box(_section(after['tree'], RUNS), 'run-1')) == _uid(_box(_section(before['tree'], RUNS), 'run-1'))
    assert _uid(_one(after['tree'], _tag('button'))) == _uid(_one(before['tree'], _tag('button')))
    assert _text(_elements(run_after)[3]) == '9 min'
    assert _attrs(_lamp(run_after))['class'] == 'lamp lamp-fail'


def test_a_rerender_keeps_the_checked_state_of_a_selected_run(tmp_path):
    results = _drive(tmp_path, [_render(_data([_row('run-1')])), _check('run-1'),
                                _render(_data([_row('run-1', durationText='5 min')])), SNAP])
    assert _box(_section(results[-1]['tree'], RUNS), 'run-1')['checked'] is True


def test_comparison_lists_each_metric_with_a_b_and_delta_text(tmp_path):
    snap = _snapshot(tmp_path, _render(_data(compare=_compare())))
    rows = _rows(_section(snap['tree'], COMPARE))
    assert [[_text(c) for c in _elements(r)] for r in rows] == [['Duração', '240', '360', 'Δ 120 (seconds)']]


def test_comparison_without_a_pair_says_how_to_get_one(tmp_path):
    snap = _snapshot(tmp_path, _render(_data(compare=None)))
    section = _section(snap['tree'], COMPARE)
    prompt = _one(section, _cls('hist-empty'))
    assert _visible(prompt) and _text(prompt) == COMPARE_PROMPT
    assert not _visible(_one(section, _tag('table')))
    assert _rows(section) == []


def test_the_phase_note_shows_only_when_the_runs_stopped_in_different_phases(tmp_path):
    apart, together = _snaps(tmp_path, [_render(_data(compare=_compare(False))), SNAP,
                                        _render(_data(compare=_compare(True))), SNAP])
    note_apart = _one(_section(apart['tree'], COMPARE), _cls('hist-note'))
    note_together = _one(_section(together['tree'], COMPARE), _cls('hist-note'))
    assert _text(note_apart) == PHASE_NOTE and _visible(note_apart)
    assert not _visible(note_together)


def test_phase_bars_give_two_bars_per_phase_and_name_a_run_that_never_reached_it(tmp_path):
    snap = _snapshot(tmp_path, _render(_data(compare=_compare())))
    phases = _all(_section(snap['tree'], COMPARE), _cls('hist-phase'))
    assert len(phases) == 2
    first_bars = _all(phases[0], _cls('hist-bar'))
    second_bars = _all(phases[1], _cls('hist-bar'))
    assert [_text(b) for b in first_bars] == ['A: 80%', 'B: 40%']
    assert [_text(b) for b in second_bars] == ['A: 100%', 'B: não alcançada']
    fills = _all(phases[0], _cls('hist-fill'))
    assert [_style(f)['--fill'] for f in fills] == ['80%', '40%']


def test_a_null_point_breaks_the_trend_line_into_separate_polylines(tmp_path):
    trends = [
        {'label': 's1', 'complete_rate': 0.5, 'iterations_per_task': 2, 'cost_per_task_usd': 0.1},
        {'label': 's2', 'complete_rate': 0.6, 'iterations_per_task': 2, 'cost_per_task_usd': 0.2},
        {'label': 's3', 'complete_rate': None, 'iterations_per_task': 3, 'cost_per_task_usd': None},
        {'label': 's4', 'complete_rate': 0.8, 'iterations_per_task': 3, 'cost_per_task_usd': 0.3},
        {'label': 's5', 'complete_rate': 0.9, 'iterations_per_task': 4, 'cost_per_task_usd': 0.4},
    ]
    snap = _snapshot(tmp_path, _render(_data(trends=trends)))
    figures = _all(_section(snap['tree'], TRENDS), _tag('figure'))
    lines = _all(figures[0], _tag('polyline'))
    assert [len(line['attrs']['points'].split()) for line in lines] == [2, 2]


def test_each_trend_has_a_text_list_of_its_values_with_no_data_marked(tmp_path):
    trends = [{'label': 's1', 'complete_rate': 0.5, 'iterations_per_task': 2, 'cost_per_task_usd': 0.1},
              {'label': 's2', 'complete_rate': None, 'iterations_per_task': 2, 'cost_per_task_usd': 0.25}]
    snap = _snapshot(tmp_path, _render(_data(trends=trends)))
    figures = _all(_section(snap['tree'], TRENDS), _tag('figure'))
    captions = [_text(_one(f, _tag('figcaption'))) for f in figures]
    assert captions == ['Taxa de conclusão', 'Iterações por tarefa', 'Custo por tarefa (USD)']
    assert [_text(li) for li in _elements(_one(figures[0], _tag('ol')))] == ['s1: 0.5', 's2: sem dado']
    assert [_text(li) for li in _elements(_one(figures[2], _tag('ol')))] == ['s1: 0.1', 's2: 0.25']


def test_trend_lines_are_svg_elements_in_the_svg_namespace(tmp_path):
    trends = [{'label': 's1', 'complete_rate': 0.5, 'iterations_per_task': 2, 'cost_per_task_usd': 0.1},
              {'label': 's2', 'complete_rate': 0.7, 'iterations_per_task': 2, 'cost_per_task_usd': 0.2}]
    snap = _snapshot(tmp_path, _render(_data(trends=trends)))
    svg = _all(_section(snap['tree'], TRENDS), _tag('svg'))[0]
    assert svg['ns'] == SVG_NS
    assert all(line['ns'] == SVG_NS for line in _all(svg, _tag('polyline')))


def test_heatmap_is_seven_days_by_twenty_four_hours_with_a_level_and_label_per_cell(tmp_path):
    snap = _snapshot(tmp_path, _render(_data(heatmap=_heat())))
    grid = _one(_section(snap['tree'], ACTIVITY), _tag('tbody'))
    rows = _elements(grid)
    cells = _all(grid, _tag('td'))
    assert len(rows) == 7
    assert len(cells) == 168
    assert _text(_one(rows[0], _tag('th'))) == 'Seg'
    assert _attrs(cells[9])['aria-label'] == 'Seg 09h: 3 runs'
    assert _attrs(cells[9])['data-level'] == '3'
    assert _attrs(cells[167])['aria-label'] == 'Dom 23h: 1 runs'
    assert _attrs(cells[167])['data-level'] == '1'
    assert all(_attrs(c)['data-level'] in {'0', '1', '2', '3', '4'} for c in cells)


def test_heatmap_day_labels_are_portuguese_and_in_week_order(tmp_path):
    snap = _snapshot(tmp_path, _render(_data(heatmap=_heat())))
    grid = _one(_section(snap['tree'], ACTIVITY), _tag('tbody'))
    assert [_text(_one(r, _tag('th'))) for r in _elements(grid)] == DAYS


def test_heatmap_without_data_says_so_and_marks_every_cell_no_data(tmp_path):
    snap = _snapshot(tmp_path, _render(_data(heatmap=None)))
    section = _section(snap['tree'], ACTIVITY)
    note = _one(section, _cls('hist-empty'))
    assert _visible(note) and _text(note) == NO_ACTIVITY
    cells = _all(section, _tag('td'))
    assert len(cells) == 168
    assert all(_attrs(c)['data-level'] == '0' for c in cells)
    assert all(_attrs(c)['aria-label'].endswith('sem dado') for c in cells)


def test_lessons_show_text_and_hit_count_and_an_empty_message(tmp_path):
    lessons = [{'lesson': 'Rodar o teste antes do merge', 'hit_count': 4, 'last_seen': '2026-10-07'}]
    snap = _snapshot(tmp_path, _render(_data(lessons=lessons)))
    items = _elements(_one(_section(snap['tree'], LESSONS), _tag('ul')))
    assert [[_text(s) for s in _all(item, _tag('span'))] for item in items] == [['Rodar o teste antes do merge', 'x4']]
    empty = _snapshot(tmp_path, _render(_data(lessons=[])))
    section = _section(empty['tree'], LESSONS)
    assert _text(_one(section, _cls('hist-empty'))) == NO_LESSONS
    assert not _visible(_one(section, _tag('ul')))


def test_run_ids_and_lessons_are_written_as_text_never_as_markup(tmp_path):
    snap = _snapshot(tmp_path, _render(_data([_row('<img src=x>')], lessons=[{'lesson': '<b>x</b>', 'hit_count': 1}])))
    cell = _elements(_rows(_section(snap['tree'], RUNS))[0])[1]
    assert _text(cell) == '<img src=x>'
    assert _elements(cell) == []
    lesson = _one(_section(snap['tree'], LESSONS), _cls('lesson-text'))
    assert _text(lesson) == '<b>x</b>' and _elements(lesson) == []


def test_the_view_writes_text_through_textcontent_and_attributes_only():
    source = VIEW.read_text(encoding='utf-8')
    for banned in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', "setAttribute('style'"):
        assert banned not in source, banned
    assert not re.search(r'\sstyle\s*=', source)


def test_the_view_imports_only_the_five_model_names_it_was_given():
    source = VIEW.read_text(encoding='utf-8')
    assert len(re.findall(r'^import\b', source, re.M)) == 1
    [names] = re.findall(r"^import \{([^}]*)\} from '\./history-model\.js';", source, re.M)
    assert sorted(n.strip() for n in names.split(',')) == sorted(MODEL_NAMES)


def test_stylesheet_defines_tokens_on_root_with_a_dark_variant():
    css = CSS.read_text(encoding='utf-8')
    assert re.search(r':root\s*\{', css)
    assert '@media (prefers-color-scheme: dark)' in css
    assert 'var(--' in css


def test_stylesheet_has_no_imports_and_no_external_urls():
    css = CSS.read_text(encoding='utf-8')
    assert not re.search(r'@import|url\(|https?:', css)


def test_wide_tables_scroll_inside_their_own_region():
    css = CSS.read_text(encoding='utf-8')
    assert re.search(r'\.hist-scroll\s*\{[^}]*overflow-x:\s*auto', css)


@pytest.mark.parametrize('selector', ['button', 'input', '.hist-scroll'])
def test_interactive_controls_have_a_visible_focus_ring(selector):
    css = CSS.read_text(encoding='utf-8')
    assert re.search(re.escape(selector) + r':focus-visible\s*[^{]*\{[^}]*outline', css), selector


@pytest.mark.parametrize('shape', sorted(set(SHAPES.values())))
def test_every_lamp_shape_has_a_glyph_rule(shape):
    css = CSS.read_text(encoding='utf-8')
    assert re.search(r'\[data-shape="' + shape + r'"\]', css), shape


@pytest.mark.parametrize('level', range(5))
def test_heat_levels_have_a_fill_rule(level):
    css = CSS.read_text(encoding='utf-8')
    assert re.search(r'\[data-level="' + str(level) + r'"\]', css), level
