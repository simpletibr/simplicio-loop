'''Unit tests for the Simplicio Live coordination view (coordination-view.js) and its markup in index.html and live.css.

coordination-view.js renders the model of coordinationOf() into four containers: a kanban, a dependency DAG, the drain
metric and the worker slots. Node has no DOM here, so the view runs against a small fake DOM that counts every write.
The model is built here from the contract fields, so the view never depends on coordination.js being present.
'''
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LIVE = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'live'
VIEW = LIVE.parent / 'coordination' / 'view.js'
EMPTY = 'Nenhum item na fila deste repositório.'
NO_DRAIN = 'Sem métrica de drenagem para mostrar.'
COLUMNS = [('backlog', 'Backlog'), ('ready', 'Prontos'), ('claimed', 'Em execução'),
           ('review', 'Revisão'), ('blocked', 'Bloqueados'), ('done', 'Concluídos')]
LEASE_TEXT = {'live': 'Lease vivo', 'stale': 'Lease desatualizado', 'expired': 'Lease expirado'}
LEASE_LAMP = {'live': 'RUNNING', 'stale': 'UNVERIFIED', 'expired': 'STALLED'}


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


SCRIPT = '''
import fs from 'node:fs';
import { createCoordination } from __VIEW__;

let uids = 0;
let writes = 0;
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
  remove() { writes += 1; detach(this); }
  addEventListener(type, fn) {
    const list = this.listeners.get(type) ?? [];
    list.push(fn);
    this.listeners.set(type, list);
  }
  click() { for (const fn of this.listeners.get('click') ?? []) fn({ type: 'click', target: this }); }
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
function find(node, pred) {
  if (pred(node)) return node;
  for (const child of node.children) {
    const hit = find(child, pred);
    if (hit !== null) return hit;
  }
  return null;
}

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const kanban = new Element('div');
const dag = new Element('div');
const drain = new Element('div');
const slots = new Element('div');
const status = new Element('p');
const coord = createCoordination({ kanban, dag, drain, slots, status });
const out = input.steps.map((step) => {
  coord.render(step.model);
  if (step.click !== null && step.click !== undefined) {
    const button = find(dag, (node) => node.localName === 'button' && node.textContent === step.click);
    if (button === null) throw new Error('no DAG button for ' + step.click);
    button.click();
  }
  return {
    kanban: snap(kanban), dag: snap(dag), drain: snap(drain), slots: snap(slots),
    status: status.textContent, writes,
  };
});
process.stdout.write(JSON.stringify(out));
'''


def _render(steps):
    script = SCRIPT.replace('__VIEW__', json.dumps(VIEW.as_uri()))
    proc = subprocess.run([_node(), '--input-type=module', '-e', script], input=json.dumps({'steps': steps}),
                          capture_output=True, text=True, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _attrs(node):
    return node.get('attrs', {})


def _text(node):
    if 'text' in node:
        return node['text']
    return ''.join(_text(child) for child in node.get('children', []))


def _elements(node):
    return [child for child in node.get('children', []) if 'tag' in child]


def _all(node, pred, found=None):
    found = [] if found is None else found
    if 'tag' in node and pred(node):
        found.append(node)
    for child in node.get('children', []):
        _all(child, pred, found)
    return found


def _find(node, pred):
    hits = _all(node, pred)
    return hits[0] if hits else None


def _by_class(node, name):
    return _find(node, lambda n: name in _attrs(n).get('class', '').split())


def _hidden(node, name):
    part = _by_class(node, name)
    assert part is not None, name
    return 'hidden' in _attrs(part)


def _card(card_id, column='claimed', **extra):
    row = {'id': card_id, 'goal': 'Objetivo ' + card_id, 'column': column, 'blockedBy': [], 'worker': 'w-1',
           'leaseState': 'live', 'remainingS': 540}
    row.update(extra)
    return row


def _columns(cards_by_key=None):
    cards_by_key = cards_by_key or {}
    return [{'key': key, 'label': label, 'count': len(cards_by_key.get(key, [])), 'cards': cards_by_key.get(key, [])}
            for key, label in COLUMNS]


def _drain(**extra):
    row = {'total': 10, 'done': 3, 'remaining': 7, 'blocked': 0, 'percent': 30, 'etaS': 720, 'etaLabel': 'ESTIMATE',
           'reason': None}
    row.update(extra)
    return row


def _model(cards_by_key=None, layers=None, edges=None, drain=None, slots=None, status='RUNNING', reason=None,
           total=None):
    cards_by_key = cards_by_key or {}
    columns = _columns(cards_by_key)
    total = sum(len(cards) for cards in cards_by_key.values()) if total is None else total
    return {'status': status, 'reason': reason, 'total': total, 'columns': columns,
            'dag': {'layers': layers or [], 'edges': edges or []},
            'drain': drain, 'slots': slots or []}


def _step(model, click=None):
    return {'model': model, 'click': click}


BASE_DAG = dict(
    layers=[['T-1'], ['T-2', 'T-3']],
    edges=[{'from': 'T-1', 'to': 'T-2', 'satisfied': True}, {'from': 'T-1', 'to': 'T-3', 'satisfied': False}],
)


def _dag_model(**extra):
    return _model(layers=BASE_DAG['layers'], edges=BASE_DAG['edges'], total=3, **extra)


def _button(tree, node_id):
    button = _find(tree['dag'], lambda n: n.get('tag') == 'button' and _text(n) == node_id)
    assert button is not None, node_id
    return button


def _edges(tree):
    return {(_attrs(n)['data-from'], _attrs(n)['data-to']): _attrs(n)
            for n in _all(tree['dag'], lambda n: n.get('tag') == 'li' and 'data-from' in _attrs(n))}


def _edge_item(tree, source, target):
    item = _find(tree['dag'], lambda n: _attrs(n).get('data-from') == source and _attrs(n).get('data-to') == target)
    assert item is not None, (source, target)
    return item


def _cards_by_id(tree):
    found = {}
    for card in _all(tree['kanban'], lambda n: n.get('tag') == 'li' and 'data-lease' in _attrs(n)):
        found[_text(_by_class(card, 'card-id'))] = card
    return found


# Kanban ---------------------------------------------------------------------------------------------------------------

def test_renders_six_columns_in_model_order_with_label_and_count():
    cards = {'claimed': [_card('T-1'), _card('T-2')], 'done': [_card('T-9', column='done', leaseState='expired')]}
    [step] = _render([_step(_model(cards))])
    columns = _elements(step['kanban'])
    assert [_attrs(column)['data-column'] for column in columns] == [key for key, _ in COLUMNS]
    assert [_text(_elements(column)[0]) for column in columns] == [
        'Backlog (0)', 'Prontos (0)', 'Em execução (2)', 'Revisão (0)', 'Bloqueados (0)', 'Concluídos (1)']


def test_card_shows_id_goal_worker_and_remaining_time():
    [step] = _render([_step(_model({'claimed': [_card('T-1')]}))])
    card = _cards_by_id(step)['T-1']
    assert _text(_by_class(card, 'card-id')) == 'T-1'
    assert _text(_by_class(card, 'card-goal')) == 'Objetivo T-1'
    assert _text(_by_class(card, 'card-worker')) == 'Worker: w-1'
    assert _text(_by_class(card, 'card-remaining')) == 'restam 9 min'
    assert not _hidden(card, 'card-remaining')


@pytest.mark.parametrize('lease', ['live', 'stale', 'expired'])
def test_lease_badge_names_the_lease_state_and_its_lamp(lease):
    [step] = _render([_step(_model({'claimed': [_card('T-1', leaseState=lease)]}))])
    card = _cards_by_id(step)['T-1']
    badge = _by_class(card, 'lease')
    assert _attrs(badge)['data-lease'] == lease
    assert _text(_by_class(badge, 'lease-label')) == LEASE_TEXT[lease]
    assert _attrs(_by_class(badge, 'lamp'))['data-state'] == LEASE_LAMP[lease]


def test_unknown_lease_is_a_pending_lamp_not_a_success():
    [step] = _render([_step(_model({'claimed': [_card('T-1', leaseState=None)]}))])
    badge = _by_class(_cards_by_id(step)['T-1'], 'lease')
    assert _attrs(badge)['data-lease'] == 'unknown'
    assert _text(_by_class(badge, 'lease-label')) == 'Lease sem registro'
    assert _attrs(_by_class(badge, 'lamp'))['data-state'] == 'PENDING'


def test_blocked_card_shows_the_blocked_by_line_and_its_siding_marker():
    cards = {'blocked': [_card('T-2', column='blocked', blockedBy=['T-1', 'T-4'])]}
    [step] = _render([_step(_model(cards))])
    card = _cards_by_id(step)['T-2']
    assert _attrs(card)['data-blocked'] == 'true'
    assert _text(_by_class(card, 'card-blocked-text')) == 'Bloqueado por: T-1, T-4'
    assert not _hidden(card, 'card-blocked')


def test_unblocked_card_hides_the_blocked_line():
    [step] = _render([_step(_model({'claimed': [_card('T-1')]}))])
    card = _cards_by_id(step)['T-1']
    assert 'data-blocked' not in _attrs(card)
    assert _text(_by_class(card, 'card-blocked-text')) == ''
    assert _hidden(card, 'card-blocked')


def test_card_without_remaining_time_hides_it():
    [step] = _render([_step(_model({'claimed': [_card('T-1', remainingS=None)]}))])
    card = _cards_by_id(step)['T-1']
    assert _text(_by_class(card, 'card-remaining')) == ''
    assert _hidden(card, 'card-remaining')


def test_a_poll_moves_a_card_to_its_new_column_and_keeps_its_node():
    before = _render([_step(_model({'claimed': [_card('T-1')]}))])[0]
    after = _render([_step(_model({'claimed': [_card('T-1')]})), _step(_model({'review': [_card('T-1', column='review')]}))])[1]
    assert _cards_by_id(after)['T-1']['uid'] == _cards_by_id(before)['T-1']['uid']
    assert _attrs(_elements(after['kanban'])[3])['data-column'] == 'review'
    cards = _all(after['kanban'], lambda n: n.get('tag') == 'li' and 'data-lease' in _attrs(n))
    assert [_text(_by_class(c, 'card-id')) for c in cards] == ['T-1']


def test_goal_is_written_as_text_never_as_markup():
    [step] = _render([_step(_model({'claimed': [_card('T-1', goal='<img src=x onerror=1>')]}))])
    goal = _by_class(_cards_by_id(step)['T-1'], 'card-goal')
    assert _text(goal) == '<img src=x onerror=1>'
    assert _elements(goal) == []


# DAG ------------------------------------------------------------------------------------------------------------------

def test_layers_render_in_order_with_one_focusable_button_per_node():
    [step] = _render([_step(_dag_model())])
    layers = _all(step['dag'], lambda n: n.get('tag') == 'li' and 'data-layer' in _attrs(n))
    assert [_text(_elements(layer)[0]) for layer in layers] == ['Camada 1', 'Camada 2']
    buttons = _all(step['dag'], lambda n: n.get('tag') == 'button')
    assert [_text(button) for button in buttons] == ['T-1', 'T-2', 'T-3']
    assert all(_attrs(button)['aria-pressed'] == 'false' for button in buttons)


def test_each_node_lists_its_dependencies_with_satisfied_and_unsatisfied_marks():
    [step] = _render([_step(_dag_model())])
    edges = _edges(step)
    assert set(edges) == {('T-1', 'T-2'), ('T-1', 'T-3')}
    assert edges[('T-1', 'T-2')]['data-satisfied'] == 'true'
    assert edges[('T-1', 'T-3')]['data-satisfied'] == 'false'
    satisfied = _edge_item(step, 'T-1', 'T-2')
    unsatisfied = _edge_item(step, 'T-1', 'T-3')
    assert _attrs(_by_class(satisfied, 'lamp'))['data-state'] == 'PASS'
    assert _attrs(_by_class(unsatisfied, 'lamp'))['data-state'] == 'BLOCKED'
    assert _text(_by_class(satisfied, 'dag-edge-text')) == 'T-1: satisfeita'
    assert _text(_by_class(unsatisfied, 'dag-edge-text')) == 'T-1: não satisfeita'


def test_selecting_a_node_highlights_every_edge_that_touches_it():
    [step] = _render([_step(_dag_model(), click='T-1')])
    edges = _edges(step)
    assert _attrs(_button(step, 'T-1'))['aria-pressed'] == 'true'
    assert _attrs(_button(step, 'T-2'))['aria-pressed'] == 'false'
    assert edges[('T-1', 'T-2')].get('data-highlight') == 'true'
    assert edges[('T-1', 'T-3')].get('data-highlight') == 'true'


def test_selecting_a_dependent_node_highlights_only_its_own_edges():
    [step] = _render([_step(_dag_model(), click='T-2')])
    edges = _edges(step)
    assert edges[('T-1', 'T-2')].get('data-highlight') == 'true'
    assert 'data-highlight' not in edges[('T-1', 'T-3')]


def test_selecting_the_same_node_again_clears_the_highlight():
    _first, step = _render([_step(_dag_model(), click='T-1'), _step(_dag_model(), click='T-1')])
    assert _attrs(_button(step, 'T-1'))['aria-pressed'] == 'false'
    assert all('data-highlight' not in attrs for attrs in _edges(step).values())


def test_selection_and_button_identity_survive_a_poll():
    first, second = _render([_step(_dag_model(), click='T-2'), _step(_dag_model())])
    assert _button(second, 'T-2')['uid'] == _button(first, 'T-2')['uid']
    assert _attrs(_button(second, 'T-2'))['aria-pressed'] == 'true'
    assert _edges(second)[('T-1', 'T-2')].get('data-highlight') == 'true'


def test_selected_node_that_leaves_the_model_clears_the_selection():
    reduced = _model(layers=[['T-1'], ['T-3']], edges=[{'from': 'T-1', 'to': 'T-3', 'satisfied': False}], total=2)
    _first, step = _render([_step(_dag_model(), click='T-2'), _step(reduced)])
    assert _find(step['dag'], lambda n: n.get('tag') == 'button' and _text(n) == 'T-2') is None
    assert _attrs(_button(step, 'T-1'))['aria-pressed'] == 'false'
    assert 'data-highlight' not in _edges(step)[('T-1', 'T-3')]


def test_empty_dag_says_there_are_no_dependencies():
    [empty, filled] = _render([_step(_model()), _step(_dag_model())])
    assert _text(_by_class(empty['dag'], 'coord-none')) == 'Nenhuma dependência entre os itens.'
    assert not _hidden(empty['dag'], 'coord-none')
    assert _hidden(filled['dag'], 'coord-none')


# Drain ----------------------------------------------------------------------------------------------------------------

def test_drain_shows_counts_percent_and_a_progress_meter():
    drain = _drain(done=3, remaining=7, blocked=2, percent=30)
    [step] = _render([_step(_model(drain=drain, total=10))])
    assert _text(_by_class(step['drain'], 'drain-counts')) == 'Concluídos 3 de 10. Restam 7 (2 bloqueados).'
    assert _text(_by_class(step['drain'], 'drain-percent')) == '30% da fila concluída'
    meter = _find(step['drain'], lambda n: n.get('tag') == 'progress')
    assert _attrs(meter)['value'] == '30' and _attrs(meter)['max'] == '100'


@pytest.mark.parametrize('eta_s, label, expected', [
    (720, 'ESTIMATE', 'ETA: 12 min (ESTIMATE)'),
    (45, 'UNVERIFIED', 'ETA: 45 s (UNVERIFIED)'),
    (None, 'UNVERIFIED', 'ETA: sem estimativa (UNVERIFIED)'),
    (720, None, 'ETA: 12 min (UNVERIFIED)'),
])
def test_drain_eta_never_shows_a_bare_number(eta_s, label, expected):
    [step] = _render([_step(_model(drain=_drain(etaS=eta_s, etaLabel=label)))])
    assert _text(_by_class(step['drain'], 'drain-eta')) == expected


def test_drain_reason_is_shown_only_when_present():
    [shown, hidden] = _render([_step(_model(drain=_drain(reason='fila sem receipt'))), _step(_model(drain=_drain()))])
    assert _text(_by_class(shown['drain'], 'drain-reason')) == 'fila sem receipt'
    assert not _hidden(shown['drain'], 'drain-reason')
    assert _hidden(hidden['drain'], 'drain-reason')


def test_missing_drain_says_so_and_hides_the_metric_parts():
    [step] = _render([_step(_model(drain=None))])
    assert _text(_by_class(step['drain'], 'drain-counts')) == NO_DRAIN
    for name in ('drain-percent', 'drain-eta', 'drain-reason'):
        assert _hidden(step['drain'], name), name
    meter = _find(step['drain'], lambda n: n.get('tag') == 'progress')
    assert meter is not None and 'hidden' in _attrs(meter)


# Slots ----------------------------------------------------------------------------------------------------------------

def test_slot_shows_worker_items_lease_and_the_reclaimable_flag():
    slots = [{'worker': 'w-1', 'items': ['T-1', 'T-2'], 'state': 'expired', 'reclaimable': True},
             {'worker': 'w-2', 'items': ['T-3'], 'state': 'live', 'reclaimable': False}]
    [step] = _render([_step(_model(slots=slots))])
    first, second = _all(step['slots'], lambda n: n.get('tag') == 'li' and 'data-worker' in _attrs(n))
    assert _attrs(first)['data-worker'] == 'w-1'
    assert _text(_by_class(first, 'slot-worker')) == 'w-1'
    assert _text(_by_class(first, 'slot-items')) == 'Itens: T-1, T-2'
    assert _text(_by_class(_by_class(first, 'lease'), 'lease-label')) == 'Lease expirado'
    assert _text(_by_class(first, 'slot-reclaim')) == 'reclamável'
    assert not _hidden(first, 'slot-reclaim')
    assert _hidden(second, 'slot-reclaim')


def test_empty_slots_say_so():
    [empty] = _render([_step(_model(slots=[]))])
    assert _text(_by_class(empty['slots'], 'coord-none')) == 'Nenhum worker com lease.'
    assert not _hidden(empty['slots'], 'coord-none')


# Status and idempotence -----------------------------------------------------------------------------------------------

def test_status_names_the_model_state_and_its_reason():
    [step] = _render([_step(_model({'claimed': [_card('T-1')]}, status='UNVERIFIED', reason='sem receipt de fila'))])
    assert step['status'] == 'Não verificado: sem receipt de fila'


def test_status_says_when_the_queue_is_empty():
    [step] = _render([_step(_model(status='RUNNING', reason=None, total=0))])
    assert step['status'] == 'Em execução. ' + EMPTY


def test_identical_model_does_no_dom_work():
    model = _dag_model(drain=_drain(), slots=[{'worker': 'w-1', 'items': ['T-1'], 'state': 'live', 'reclaimable': False}])
    first, second = _render([_step(model), _step(model)])
    assert second['writes'] == first['writes']
    assert second['kanban'] == first['kanban']
    assert second['dag'] == first['dag']


# Static checks on the sources -----------------------------------------------------------------------------------------

def test_view_source_avoids_innerhtml_inline_style_and_css_text():
    text = VIEW.read_text(encoding='utf-8')
    assert 'innerHTML' not in text
    assert not re.search(r'setAttribute\(\s*.style.', text)
    assert 'cssText' not in text
    assert not re.search(r'https?://', text)
    assert not re.search(r'\beval\s*\(', text)


def test_view_exports_create_coordination_and_imports_nothing():
    text = VIEW.read_text(encoding='utf-8')
    assert re.search(r'export\s+function\s+createCoordination\s*\(', text)
    assert not re.search(r'^\s*import\s', text, flags=re.MULTILINE), 'the view takes its model through render()'


def test_index_html_adds_one_coordination_panel_right_after_the_board():
    html = (LIVE / 'index.html').read_text(encoding='utf-8')
    board = ('<section class="panel board-panel" aria-labelledby="board-title"><h2 id="board-title">Quadro por etapa</h2>'
             '<p id="board-status" role="status"></p><div id="board" class="board"></div></section>')
    coord = ('<section class="panel coord-panel" aria-labelledby="coord-title"><h2 id="coord-title">Fila e coordenação</h2>'
             '<p id="coord-status" role="status"></p><div id="coord-kanban" class="coord-kanban"></div>'
             '<div id="coord-dag" class="coord-dag"></div><div id="coord-drain" class="coord-drain"></div>'
             '<div id="coord-slots" class="coord-slots"></div></section>')
    assert re.search(re.escape(board) + r'\s*' + re.escape(coord) + r'\s*<section class="panel rail-panel"', html)
    assert html.count('class="panel coord-panel"') == 1
    for dom_id in ('coord-status', 'coord-kanban', 'coord-dag', 'coord-drain', 'coord-slots'):
        assert html.count('id="%s"' % dom_id) == 1, dom_id


def _coordination_css():
    css = (VIEW.parent / 'coordination.css').read_text(encoding='utf-8')
    marker = css.find('/* Coordination view')
    assert marker != -1, 'coordination.css has no marked coordination section'
    return css[marker:]


def test_coordination_css_is_appended_and_uses_tokens_only():
    section = _coordination_css()
    assert not re.search(r'#[0-9a-fA-F]{3,8}(?![\w-])', section), 'hard-coded colour'
    assert 'prefers-color-scheme' not in section
    assert 'animation' not in section and 'transition' not in section


@pytest.mark.parametrize('lease', ['live', 'stale', 'expired'])
def test_lease_lamp_edges_use_the_state_tokens(lease):
    section = _coordination_css()
    token = 'var(--sl-state-%s)' % LEASE_LAMP[lease].lower()
    pattern = r'\.coord-card\[data-lease="%s"\][^{]*\{[^}]*%s' % (lease, re.escape(token))
    assert re.search(pattern, section), lease


def test_blocked_cards_sit_on_a_dashed_siding():
    assert re.search(r'\.coord-card\[data-blocked="true"\][^{]*\{[^}]*border-style:\s*dashed', _coordination_css())


def test_dag_buttons_have_the_focus_ring_and_selected_edges_are_marked():
    section = _coordination_css()
    assert re.search(r'\.dag-node-button:focus-visible\s*\{[^}]*var\(--sl-focus-width\)[^}]*var\(--sl-focus\)', section)
    assert re.search(r'\.dag-edge\[data-highlight="true"\]\s*\{', section)
    assert re.search(r'\.dag-node-button\[aria-pressed="true"\]\s*\{', section)


def test_coordination_panel_spans_the_full_row_on_desktop():
    assert re.search(r'@media \(min-width: 900px\)\s*\{\s*\.coord-panel\s*\{\s*grid-column:\s*1\s*/\s*-1', _coordination_css())
