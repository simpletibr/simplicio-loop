'''Unit tests for the Simplicio Live board view (board-view.js) and its markup in index.html and live.css.

board-view.js renders the nine columns of boardOf() into the #board element. Node has no DOM here (no jsdom, no
browser), so the view runs against a small fake DOM that counts every write. The tests read the resulting tree
and check which nodes survive a poll, so a focused card keeps its focus. board.js runs in the same node process.
'''
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LIVE = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'live'
VIEW = LIVE / 'board-view.js'
BOARD = LIVE / 'board.js'
BOARD_BLOCK = ('<section class="panel board-panel" aria-labelledby="board-title"><h2 id="board-title">Quadro por etapa</h2>'
               '<p id="board-status" role="status"></p><div id="board" class="board"></div></section>')
NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
NOW_MS = int(NOW.timestamp() * 1000)
STATES = ['RUNNING', 'PASS', 'FAIL', 'UNVERIFIED', 'STALLED', 'BLOCKED', 'PENDING']
COLUMN_KEYS = ['intake', 'mapping', 'planning', 'executing', 'validating', 'watching', 'delivering', 'done', 'off']
HEADINGS = ['Contrato (0)', 'Mapeamento (0)', 'Plano (0)', 'Execução (2)', 'Validação (0)', 'Watcher (0)',
            'Entrega (0)', 'Concluído (0)', 'Fora do trilho (1)']
EMPTY = 'Nenhum run encontrado neste repositório.'


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


SCRIPT = '''
import fs from 'node:fs';
import { createBoard } from __VIEW__;
import { boardOf } from __BOARD__;

let uids = 0;
let writes = 0;
function detach(node) {
  const parent = node.parentNode;
  if (parent !== null) parent.childNodes.splice(parent.childNodes.indexOf(node), 1);
  node.parentNode = null;
}
class FakeNode {
  constructor() { this.childNodes = []; this.parentNode = null; }
  get children() { return this.childNodes.filter((node) => node.localName !== undefined); }
  get textContent() { return this.childNodes.map((node) => node.textContent).join(''); }
  set textContent(value) { this.replaceChildren(...(value === '' ? [] : [new TextNode(String(value))])); }
  append(...nodes) { for (const node of nodes) this.insertBefore(node, null); }
  insertBefore(node, ref) {
    writes += 1;
    detach(node);
    const index = ref === null ? this.childNodes.length : this.childNodes.indexOf(ref);
    if (index < 0) throw new Error('reference node is not a child');
    this.childNodes.splice(index, 0, node);
    node.parentNode = this;
    return node;
  }
  replaceChildren(...nodes) {
    writes += 1;
    for (const child of this.childNodes) child.parentNode = null;
    this.childNodes = [];
    this.append(...nodes);
  }
  replaceWith(node) {
    writes += 1;
    const parent = this.parentNode;
    detach(node);
    const index = parent.childNodes.indexOf(this);
    parent.childNodes.splice(index, 1, node);
    node.parentNode = parent;
    this.parentNode = null;
  }
  remove() { writes += 1; detach(this); }
}
class TextNode extends FakeNode {
  constructor(data) { super(); this.data = data; }
  get textContent() { return this.data; }
}
class Element extends FakeNode {
  constructor(tag) { super(); this.localName = tag; this.uid = ++uids; this.attributes = new Map(); }
  setAttribute(name, value) { writes += 1; this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  hasAttribute(name) { return this.attributes.has(name); }
  removeAttribute(name) { writes += 1; this.attributes.delete(name); }
}
globalThis.document = { createElement: (tag) => new Element(tag) };

function snap(node) {
  if (node.localName === undefined) return { text: node.data };
  return { tag: node.localName, uid: node.uid, attrs: Object.fromEntries(node.attributes), children: node.childNodes.map(snap) };
}

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const root = new Element('div');
root.setAttribute('id', 'board');
const statusEl = new Element('p');
const board = createBoard(root, statusEl);
const out = input.steps.map((step) => {
  board.render(boardOf(step.runs, step.nowMs), step.opts);
  return { root: snap(root), status: statusEl.textContent, writes };
});
process.stdout.write(JSON.stringify(out));
'''


def _render(steps):
    script = (SCRIPT.replace('__VIEW__', json.dumps(VIEW.as_uri())).replace('__BOARD__', json.dumps(BOARD.as_uri())))
    proc = subprocess.run([_node(), '--input-type=module', '-e', script], input=json.dumps({'steps': steps}),
                          capture_output=True, text=True, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _iso(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace('+00:00', 'Z')


def _run(run_id, phase, **extra):
    row = {'run_id': run_id, 'phase': phase, 'progress_status': 'RUNNING', 'percent': 42,
           'current_action': 'rodando testes', 'updated_at': _iso(3)}
    row.update(extra)
    return row


def _step(runs, run_id=None, now_ms=NOW_MS):
    return {'runs': runs, 'nowMs': now_ms, 'opts': {'runId': run_id, 'token': 'tok', 'pathname': '/live'}}


def _attrs(node):
    return node.get('attrs', {})


def _text(node):
    if 'text' in node:
        return node['text']
    return ''.join(_text(child) for child in node.get('children', []))


def _elements(node):
    return [child for child in node.get('children', []) if 'tag' in child]


def _columns(root):
    return _elements(root)


def _heading(section):
    return _elements(section)[0]


def _cards(section):
    return _elements(_elements(section)[1])


def _by_class(node, name):
    if _attrs(node).get('class') == name:
        return node
    for child in node.get('children', []):
        found = _by_class(child, name)
        if found is not None:
            return found
    return None


def _cards_by_run(snapshot):
    found = {}
    for column in _columns(snapshot):
        for item in _cards(column):
            found[_text(_by_class(item, 'card-run'))] = item
    return found


def test_renders_nine_columns_named_by_label_and_count():
    runs = [_run('run-1', 'executing'), _run('run-2', 'executing'), _run('run-3', 'mystery')]
    [step] = _render([_step(runs)])
    columns = _columns(step['root'])
    assert [_attrs(column)['data-column'] for column in columns] == COLUMN_KEYS
    assert [_text(_heading(column)) for column in columns] == HEADINGS
    assert [len(_cards(column)) for column in columns] == [0, 0, 0, 2, 0, 0, 0, 0, 1]


def test_card_has_state_link_run_id_action_percent_and_age():
    [step] = _render([_step([_run('run-1', 'executing', progress_status='BLOCKED')])])
    item = _cards_by_run(step['root'])['run-1']
    assert _attrs(item)['data-state'] == 'BLOCKED'
    body = _elements(item)[0]
    assert body['tag'] == 'a'
    assert _attrs(body)['href'] == '/live?run=run-1&t=tok'
    assert _text(_by_class(item, 'card-state')) == 'Bloqueado'
    assert _text(_by_class(item, 'card-run')) == 'run-1'
    assert _text(_by_class(item, 'card-action')) == 'rodando testes'
    assert _text(_by_class(item, 'card-percent')) == '42%'
    assert _text(_by_class(item, 'card-age')) == 'há 3 min'
    assert 'aria-current' not in _attrs(item)


def test_run_without_a_safe_id_has_no_link_and_shows_its_id_as_text():
    [step] = _render([_step([_run('run/7', 'executing')])])
    item = _cards_by_run(step['root'])['run/7']
    body = _elements(item)[0]
    assert body['tag'] == 'span'
    assert 'href' not in _attrs(body)
    assert _text(_by_class(item, 'card-run')) == 'run/7'


def test_run_id_is_written_as_text_never_as_markup():
    [step] = _render([_step([_run('a<b', 'executing')])])
    run = _by_class(_cards_by_run(step['root'])['a<b'], 'card-run')
    assert _text(run) == 'a<b'
    assert _elements(run) == []


def test_absent_percent_action_and_age_are_hidden_and_empty():
    row = _run('run-1', 'executing', percent=None, current_action=None, updated_at=None)
    [step] = _render([_step([row])])
    item = _cards_by_run(step['root'])['run-1']
    for name in ('card-percent', 'card-action', 'card-age'):
        part = _by_class(item, name)
        assert _text(part) == '', name
        assert 'hidden' in _attrs(part), name


def test_marks_only_the_selected_run_as_current():
    runs = [_run('run-1', 'executing'), _run('run-2', 'executing')]
    [step] = _render([_step(runs, run_id='run-2')])
    cards = _cards_by_run(step['root'])
    assert _attrs(cards['run-2'])['aria-current'] == 'true'
    assert 'aria-current' not in _attrs(cards['run-1'])


def test_identical_model_and_options_do_no_dom_work():
    step = _step([_run('run-1', 'executing')])
    first, second = _render([step, step])
    assert second['writes'] == first['writes']
    assert second['root'] == first['root']


def test_a_poll_updates_cards_in_place_and_keeps_their_nodes():
    first_runs = [_run('run-1', 'executing'), _run('run-2', 'executing')]
    later_runs = [_run('run-1', 'executing'), _run('run-2', 'validating')]
    before, after = _render([_step(first_runs), _step(later_runs, now_ms=NOW_MS + 60_000)])
    assert [column['uid'] for column in _columns(after['root'])] == [column['uid'] for column in _columns(before['root'])]
    assert _cards_by_run(after['root'])['run-1']['uid'] == _cards_by_run(before['root'])['run-1']['uid']
    assert _text(_by_class(_cards_by_run(after['root'])['run-1'], 'card-age')) == 'há 4 min'


def test_a_run_that_changes_phase_moves_to_its_new_column():
    _before, after = _render([_step([_run('run-2', 'executing')]), _step([_run('run-2', 'validating')])])
    assert [len(_cards(column)) for column in _columns(after['root'])] == [0, 0, 0, 0, 1, 0, 0, 0, 0]
    assert _text(_heading(_columns(after['root'])[4])) == 'Validação (1)'


def test_a_run_that_leaves_the_model_leaves_the_board():
    _before, after = _render([_step([_run('run-1', 'executing'), _run('run-2', 'executing')]),
                              _step([_run('run-1', 'executing')])])
    assert set(_cards_by_run(after['root'])) == {'run-1'}
    assert _text(_heading(_columns(after['root'])[3])) == 'Execução (1)'


def test_status_line_says_when_the_repository_has_no_runs():
    empty, filled = _render([_step([]), _step([_run('run-1', 'executing')])])
    assert empty['status'] == EMPTY
    assert all(len(_cards(column)) == 0 for column in _columns(empty['root']))
    assert filled['status'] == ''


def test_index_html_opens_main_with_the_board_section():
    html = (LIVE / 'index.html').read_text(encoding='utf-8')
    assert re.search(r'<main class="live-main">\s*' + re.escape(BOARD_BLOCK), html), 'board section is not the first child of main'


def test_board_css_scrolls_inside_the_board_and_keeps_column_width():
    css = (LIVE / 'live.css').read_text(encoding='utf-8')
    assert re.search(r'\.board\s*\{[^}]*overflow-x:\s*auto', css), 'the board must scroll inside its own box'
    # Nine columns (eight phases plus off-rail) share the width and fit at 1920 px; 9.5rem is the floor below which they scroll (see the e2e fit test).
    assert re.search(r'\.board\s*>\s*section\s*\{[^}]*min-width:\s*9\.5rem', css), 'columns need a 9.5rem minimum width'


@pytest.mark.parametrize('state', STATES)
def test_card_lamp_edge_uses_the_state_token(state):
    css = (LIVE / 'live.css').read_text(encoding='utf-8')
    token = f'var(--sl-state-{state.lower()})'
    pattern = rf'\.board\s+ol\s*>\s*li\[data-state="{state}"\][^{{]*\{{[^}}]*{re.escape(token)}'
    assert re.search(pattern, css), state


def test_card_focus_ring_uses_the_focus_tokens():
    css = (LIVE / 'live.css').read_text(encoding='utf-8')
    assert re.search(r'\.card-body:focus-visible\s*\{[^}]*var\(--sl-focus-width\)[^}]*var\(--sl-focus\)', css)
