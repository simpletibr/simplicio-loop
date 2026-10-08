'''Pure unit tests for the Simplicio Live coordination model (coordination.js).

coordination.js turns the GET /api/coordination payload (the backlog DAG with leases and worker slots) into the six
coordination columns, the layered DAG, the drain summary and the worker slots. It runs in node (no DOM, no clock: the
caller passes nowMs). These tests fail until coordination.js exists.
'''
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'coordination' / 'model.js'

COLUMN_KEYS = ['ready', 'claimed', 'running', 'verifying', 'done', 'blocked']
LABELS = {'ready': 'Pronto', 'claimed': 'Reservado', 'running': 'Em execução', 'verifying': 'Verificando',
          'done': 'Concluído', 'blocked': 'Bloqueado'}
NOW = int(datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


SCRIPT = '''
import fs from 'node:fs';
import * as coord from %s;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
let out;
if (input.op === 'coordinationOf') out = coord.coordinationOf(input.payload, input.nowMs);
else if (input.op === 'blockedText') out = coord.blockedText(input.card);
else out = { COORD_COLUMNS: coord.COORD_COLUMNS, COORD_LABELS: coord.COORD_LABELS };
process.stdout.write(JSON.stringify(out));
'''


def _call(payload):
    script = SCRIPT % json.dumps(MODULE.as_uri())
    proc = subprocess.run([_node(), '--input-type=module', '-e', script], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _lease(state='live', remaining_s=600, worker='w1', expires_ms=None):
    expires = NOW + remaining_s * 1000 if expires_ms is None else expires_ms
    return {'worker': worker, 'heartbeat_at': _iso(NOW - 60000), 'expires_at': _iso(expires), 'age_s': 60,
            'remaining_s': remaining_s, 'state': state}


def _item(item_id, column, depends_on=(), blocked_by=(), worker=None, lease=None, goal=None):
    return {'id': item_id, 'goal': goal if goal is not None else 'goal ' + item_id, 'status': column,
            'column': column, 'priority': 0, 'depends_on': list(depends_on), 'blocked_by': list(blocked_by),
            'worker': worker, 'lease': lease}


def _payload(items, **changes):
    payload = {'status': 'MEASURED', 'revision': 1, 'columns': [], 'items': items, 'edges': [], 'drain': None,
               'slots': []}
    payload.update(changes)
    return payload


def _coord(payload, now=NOW):
    return _call({'op': 'coordinationOf', 'payload': payload, 'nowMs': now})


def _column(out, key):
    return next(column for column in out['columns'] if column['key'] == key)


def _card(out, item_id):
    return next(card for column in out['columns'] for card in column['cards'] if card['id'] == item_id)


def _layers_of(items):
    return _coord(_payload(items))['dag']['layers']


def test_the_column_keys_and_labels_are_the_contract():
    out = _call({'op': 'constants'})
    assert out['COORD_COLUMNS'] == COLUMN_KEYS
    assert out['COORD_LABELS'] == LABELS


@pytest.mark.parametrize('payload', [None, 'abc', 42, [1, 2], {}, {'items': 'nope'}, {'status': 'weird'}])
def test_a_null_or_garbage_payload_is_unverified_with_six_empty_columns(payload):
    out = _coord(payload)
    assert out['status'] == 'UNVERIFIED'
    assert out['total'] == 0
    assert [column['key'] for column in out['columns']] == COLUMN_KEYS
    assert all(column['count'] == 0 and column['cards'] == [] for column in out['columns'])
    assert out['dag'] == {'layers': [], 'edges': []}
    assert out['drain'] is None
    assert out['slots'] == []


def test_an_unverified_payload_keeps_its_status_and_reason():
    out = _coord(_payload([], status='UNVERIFIED', reason='backlog file missing'))
    assert out['status'] == 'UNVERIFIED'
    assert out['reason'] == 'backlog file missing'


def test_a_measured_payload_has_no_reason_and_six_columns_with_labels_in_order():
    out = _coord(_payload([]))
    assert out['status'] == 'MEASURED'
    assert out['reason'] is None
    assert [(column['key'], column['label'], column['count']) for column in out['columns']] == [
        (key, LABELS[key], 0) for key in COLUMN_KEYS]


def test_each_item_lands_in_its_column_and_the_counts_match_the_cards():
    items = [_item('a', 'ready'), _item('b', 'claimed'), _item('c', 'running'), _item('d', 'verifying'),
             _item('e', 'done'), _item('f', 'blocked'), _item('g', 'blocked')]
    out = _coord(_payload(items))
    assert out['total'] == 7
    assert {column['key']: column['count'] for column in out['columns']} == {
        'ready': 1, 'claimed': 1, 'running': 1, 'verifying': 1, 'done': 1, 'blocked': 2}
    assert [card['id'] for card in _column(out, 'blocked')['cards']] == ['f', 'g']
    assert all(column['count'] == len(column['cards']) for column in out['columns'])


def test_an_item_with_an_unknown_column_goes_to_blocked():
    out = _coord(_payload([_item('x', 'mystery')]))
    assert _card(out, 'x')['column'] == 'blocked'
    assert _column(out, 'blocked')['count'] == 1


def test_cards_keep_the_payload_order_within_a_column():
    out = _coord(_payload([_item('c', 'running'), _item('a', 'ready'), _item('b', 'running')]))
    assert [card['id'] for card in _column(out, 'running')['cards']] == ['c', 'b']


def test_a_card_has_exactly_the_coordination_fields():
    item = _item('t1', 'running', blocked_by=[], worker='w2', lease=_lease('live', 600, 'w2'), goal='Fazer X')
    card = _card(_coord(_payload([item])), 't1')
    assert card == {'id': 't1', 'goal': 'Fazer X', 'column': 'running', 'blockedBy': [], 'worker': 'w2',
                    'leaseState': 'live', 'remainingS': 600, 'issue': None, 'pr': None}


def test_blocked_by_comes_from_the_payload_and_defaults_to_empty():
    out = _coord(_payload([_item('a', 'blocked', blocked_by=['x', 'y'])]))
    assert _card(out, 'a')['blockedBy'] == ['x', 'y']
    item = _item('b', 'ready')
    del item['blocked_by']
    assert _card(_coord(_payload([item])), 'b')['blockedBy'] == []


def test_a_card_without_a_lease_has_null_lease_state_and_remaining():
    card = _card(_coord(_payload([_item('a', 'ready', worker=None, lease=None)])), 'a')
    assert card['worker'] is None
    assert card['leaseState'] is None
    assert card['remainingS'] is None


@pytest.mark.parametrize('state', ['live', 'stale', 'expired'])
def test_the_lease_state_comes_from_the_payload_when_no_now_is_given(state):
    card = _card(_coord(_payload([_item('a', 'running', lease=_lease(state, 120))]), now=None), 'a')
    assert card['leaseState'] == state
    assert card['remainingS'] == 120


def test_an_unknown_lease_state_is_null():
    card = _card(_coord(_payload([_item('a', 'running', lease=_lease('weird', 120))]), now=None), 'a')
    assert card['leaseState'] is None


def test_remaining_s_counts_down_from_now_using_expires_at():
    item = _item('a', 'running', lease=_lease('live', 600, expires_ms=NOW + 600000))
    card = _card(_coord(_payload([item]), now=NOW + 10000), 'a')
    assert card['remainingS'] == 590
    assert card['leaseState'] == 'live'


def test_a_lease_whose_expires_at_has_passed_is_expired_with_zero_remaining():
    item = _item('a', 'running', lease=_lease('live', 30, expires_ms=NOW + 30000))
    card = _card(_coord(_payload([item]), now=NOW + 31000), 'a')
    assert card['leaseState'] == 'expired'
    assert card['remainingS'] == 0


def test_an_unparsable_expires_at_keeps_the_payload_lease_values():
    lease = _lease('stale', 300)
    lease['expires_at'] = 'not a date'
    card = _card(_coord(_payload([_item('a', 'verifying', lease=lease)]), now=NOW + 10000), 'a')
    assert card['leaseState'] == 'stale'
    assert card['remainingS'] == 300


def test_layers_put_roots_in_layer_zero_and_use_the_longest_path_depth():
    items = [_item('a', 'done'), _item('b', 'done', depends_on=['a']), _item('c', 'done', depends_on=['b', 'a'])]
    assert _layers_of(items) == [['a'], ['b'], ['c']]


def test_a_diamond_puts_the_join_below_its_longest_branch():
    items = [_item('top', 'done'), _item('left', 'done', depends_on=['top']),
             _item('right1', 'done', depends_on=['top']), _item('right2', 'done', depends_on=['right1']),
             _item('join', 'ready', depends_on=['left', 'right2'])]
    assert _layers_of(items) == [['top'], ['left', 'right1'], ['right2'], ['join']]


def test_ids_inside_a_layer_are_in_stable_id_order():
    items = [_item('c', 'ready'), _item('a', 'ready'), _item('b', 'ready'), _item('z', 'ready', depends_on=['c'])]
    assert _layers_of(items) == [['a', 'b', 'c'], ['z']]


def test_a_dependency_on_a_missing_item_does_not_move_the_item():
    assert _layers_of([_item('x', 'ready', depends_on=['ghost'])]) == [['x']]


def test_items_in_a_cycle_go_to_the_last_layer_and_the_rest_is_layered():
    items = [_item('c', 'ready'), _item('a', 'ready', depends_on=['b']), _item('b', 'ready', depends_on=['a'])]
    assert _layers_of(items) == [['c'], ['a', 'b']]


def test_a_self_dependency_is_a_cycle_and_goes_to_the_last_layer():
    items = [_item('y', 'ready'), _item('x', 'ready', depends_on=['x'])]
    assert _layers_of(items) == [['y'], ['x']]


def test_every_item_appears_in_exactly_one_layer_even_downstream_of_a_cycle():
    items = [_item('a', 'ready', depends_on=['b']), _item('b', 'ready', depends_on=['a']),
             _item('d', 'ready', depends_on=['a']), _item('r', 'done')]
    layers = _layers_of(items)
    placed = [item_id for layer in layers for item_id in layer]
    assert sorted(placed) == ['a', 'b', 'd', 'r']
    assert layers[0] == ['r']


def test_an_empty_dag_has_no_layers():
    assert _layers_of([]) == []


def test_edges_run_from_the_dependency_to_the_item_and_are_satisfied_only_when_it_is_done():
    items = [_item('a', 'done'), _item('b', 'running', depends_on=['a']), _item('c', 'blocked', depends_on=['b'])]
    edges = _coord(_payload(items))['dag']['edges']
    assert sorted(edges, key=lambda edge: (edge['from'], edge['to'])) == [
        {'from': 'a', 'to': 'b', 'satisfied': True}, {'from': 'b', 'to': 'c', 'satisfied': False}]


def test_an_edge_with_a_missing_end_is_dropped_and_a_repeated_dependency_is_one_edge():
    items = [_item('a', 'done'), _item('b', 'ready', depends_on=['a', 'a', 'ghost'])]
    assert _coord(_payload(items))['dag']['edges'] == [{'from': 'a', 'to': 'b', 'satisfied': True}]


def test_a_duplicate_item_id_counts_once_and_the_first_one_wins():
    items = [_item('a', 'ready', goal='first'), _item('a', 'done', goal='second')]
    out = _coord(_payload(items))
    assert out['total'] == 1
    assert _card(out, 'a')['goal'] == 'first'


def test_items_that_are_not_objects_or_have_no_id_are_skipped():
    items = [None, 'x', {'column': 'ready'}, _item('ok', 'ready')]
    out = _coord(_payload(items))
    assert out['total'] == 1
    assert [card['id'] for card in _column(out, 'ready')['cards']] == ['ok']


def test_the_drain_summary_is_passed_through_with_its_eta_label_and_reason():
    drain = {'total': 12, 'done': 3, 'remaining': 9, 'blocked': 3, 'percent': 25, 'eta_s': None,
             'eta_label': 'UNVERIFIED', 'reason': 'fewer than two timestamped done items'}
    assert _coord(_payload([], drain=drain))['drain'] == {
        'total': 12, 'done': 3, 'remaining': 9, 'blocked': 3, 'percent': 25, 'etaS': None,
        'etaLabel': 'UNVERIFIED', 'reason': 'fewer than two timestamped done items'}


def test_a_drain_with_an_estimate_keeps_the_eta_seconds():
    drain = {'total': 4, 'done': 2, 'remaining': 2, 'blocked': 0, 'percent': 50, 'eta_s': 1800,
             'eta_label': 'ESTIMATE', 'reason': None}
    drain_out = _coord(_payload([], drain=drain))['drain']
    assert (drain_out['etaS'], drain_out['etaLabel'], drain_out['reason']) == (1800, 'ESTIMATE', None)


def test_a_missing_drain_is_null():
    assert _coord(_payload([]))['drain'] is None


def test_slots_keep_the_worker_items_state_and_reclaimable_flag():
    slots = [{'worker': 'w1', 'items': ['a', 'b'], 'state': 'live', 'reclaimable': False},
             {'worker': 'w2', 'items': ['c'], 'state': 'expired', 'reclaimable': True}]
    assert _coord(_payload([], slots=slots))['slots'] == [
        {'worker': 'w1', 'items': ['a', 'b'], 'state': 'live', 'reclaimable': False},
        {'worker': 'w2', 'items': ['c'], 'state': 'expired', 'reclaimable': True}]


@pytest.mark.parametrize('card, text', [
    ({'blockedBy': ['a', 'b']}, 'Bloqueado por: a, b'),
    ({'blockedBy': ['x']}, 'Bloqueado por: x'),
    ({'blockedBy': []}, ''),
    ({}, ''),
    ({'blockedBy': None}, ''),
    (None, ''),
])
def test_blocked_text_lists_the_blockers_or_is_empty(card, text):
    assert _call({'op': 'blockedText', 'card': card}) == text


def test_the_twelve_item_drain_with_three_workers_matches_the_backlog():
    items = [
        _item('t01', 'done', worker='w1'),
        _item('t02', 'done', depends_on=['t01'], worker='w2'),
        _item('t03', 'running', depends_on=['t01'], worker='w3', lease=_lease('live', 600, 'w3', NOW + 600000)),
        _item('t04', 'verifying', depends_on=['t02'], worker='w1',
              lease=_lease('stale', 300, 'w1', NOW + 300000)),
        _item('t05', 'claimed', depends_on=['t02'], worker='w2'),
        _item('t06', 'ready'),
        _item('t07', 'blocked', depends_on=['t04', 't06'], blocked_by=['t04', 't06']),
        _item('t08', 'blocked'),
        _item('t09', 'done', depends_on=['t01']),
        _item('t10', 'ready', depends_on=['t02']),
        _item('t11', 'running', depends_on=['t02'], worker='w3', lease=_lease('expired', 0, 'w3', NOW - 10000)),
        _item('t12', 'blocked', depends_on=['t11'], blocked_by=['t11']),
    ]
    drain = {'total': 12, 'done': 3, 'remaining': 9, 'blocked': 3, 'percent': 25, 'eta_s': None,
             'eta_label': 'UNVERIFIED', 'reason': 'fewer than two timestamped done items'}
    slots = [{'worker': 'w1', 'items': ['t01', 't04'], 'state': 'live', 'reclaimable': False},
             {'worker': 'w2', 'items': ['t02', 't05'], 'state': 'live', 'reclaimable': False},
             {'worker': 'w3', 'items': ['t03', 't11'], 'state': 'expired', 'reclaimable': True}]
    out = _coord(_payload(items, drain=drain, slots=slots))

    assert out['total'] == 12
    assert {column['key']: column['count'] for column in out['columns']} == {
        'ready': 2, 'claimed': 1, 'running': 2, 'verifying': 1, 'done': 3, 'blocked': 3}
    assert [card['id'] for card in _column(out, 'ready')['cards']] == ['t06', 't10']
    assert [card['id'] for card in _column(out, 'blocked')['cards']] == ['t07', 't08', 't12']
    assert _card(out, 't07')['blockedBy'] == ['t04', 't06']
    assert _card(out, 't04')['leaseState'] == 'stale'
    assert _card(out, 't11')['leaseState'] == 'expired'
    assert _card(out, 't11')['remainingS'] == 0

    assert out['dag']['layers'] == [['t01', 't06', 't08'], ['t02', 't03', 't09'],
                                    ['t04', 't05', 't10', 't11'], ['t07', 't12']]
    edges = sorted((edge['from'], edge['to'], edge['satisfied']) for edge in out['dag']['edges'])
    assert edges == sorted([
        ('t01', 't02', True), ('t01', 't03', True), ('t01', 't09', True), ('t02', 't04', True),
        ('t02', 't05', True), ('t02', 't10', True), ('t02', 't11', True), ('t04', 't07', False),
        ('t06', 't07', False), ('t11', 't12', False)])
    assert out['drain'] == {'total': 12, 'done': 3, 'remaining': 9, 'blocked': 3, 'percent': 25, 'etaS': None,
                            'etaLabel': 'UNVERIFIED', 'reason': 'fewer than two timestamped done items'}
    assert out['slots'] == [
        {'worker': 'w1', 'items': ['t01', 't04'], 'state': 'live', 'reclaimable': False},
        {'worker': 'w2', 'items': ['t02', 't05'], 'state': 'live', 'reclaimable': False},
        {'worker': 'w3', 'items': ['t03', 't11'], 'state': 'expired', 'reclaimable': True}]


GH_ISSUE = 'https://github.com/wesleysimplicio/simplicio-loop/issues/12'
GH_PR = 'https://github.com/wesleysimplicio/simplicio-loop/pull/34'


# GitHub references -----------------------------------------------------------------------------------------------------

def test_an_issue_and_a_pr_keep_their_number_and_github_url():
    item = _item('a', 'running')
    item['issue'] = {'number': 12, 'url': GH_ISSUE}
    item['pr'] = {'number': 34, 'url': GH_PR}
    card = _card(_coord(_payload([item])), 'a')
    assert card['issue'] == {'number': 12, 'url': GH_ISSUE}
    assert card['pr'] == {'number': 34, 'url': GH_PR}


@pytest.mark.parametrize('url', [
    'http://github.com/o/r/issues/12', 'https://github.com.evil.example/o/r', 'https://example.com/o/r/issues/12',
    'javascript:alert(1)', 'github.com/o/r/issues/12', '', None, 12,
])
def test_a_url_outside_github_is_dropped_and_the_number_is_kept(url):
    item = _item('a', 'running')
    item['issue'] = {'number': 12, 'url': url}
    assert _card(_coord(_payload([item])), 'a')['issue'] == {'number': 12, 'url': None}


@pytest.mark.parametrize('ref', [
    None, 'PR 12', 12, [], {}, {'url': GH_ISSUE}, {'number': '12', 'url': GH_ISSUE}, {'number': 1.5, 'url': GH_ISSUE},
    {'number': True, 'url': GH_ISSUE}, {'number': 0, 'url': GH_ISSUE}, {'number': -3, 'url': GH_ISSUE},
])
def test_a_missing_or_malformed_issue_or_pr_is_null(ref):
    item = _item('a', 'running')
    item['issue'] = ref
    item['pr'] = ref
    card = _card(_coord(_payload([item])), 'a')
    assert card['issue'] is None
    assert card['pr'] is None


def test_an_item_without_issue_or_pr_fields_has_null_references():
    card = _card(_coord(_payload([_item('a', 'ready')])), 'a')
    assert card['issue'] is None
    assert card['pr'] is None


# Worktrees -------------------------------------------------------------------------------------------------------------

MISSING_WORKTREES = 'worktree payload missing or invalid'
WORKTREE_STATES = ['clean', 'dirty', 'conflict', 'prunable', 'locked', 'unknown']


def _worktree_row(path, **changes):
    row = {'path': path, 'branch': 'feat/' + path.rsplit('/', 1)[-1], 'head': 'abcdef1234567890',
           'item_id': 'T-1', 'state': 'clean', 'cleanup': 'none', 'main': False}
    row.update(changes)
    return row


def _worktrees_of(rows=None, status='MEASURED', reason=None):
    return _coord(_payload([], worktrees={'status': status, 'reason': reason, 'rows': rows or []}))['worktrees']


def test_a_payload_without_worktrees_is_unverified_with_no_rows():
    assert _coord(_payload([]))['worktrees'] == {'status': 'UNVERIFIED', 'reason': MISSING_WORKTREES, 'rows': []}


@pytest.mark.parametrize('worktrees', [
    None, 'abc', [1], {}, {'status': 'weird', 'rows': []}, {'status': 'MEASURED'},
    {'status': 'MEASURED', 'rows': 'nope'}, {'status': 'MEASURED', 'rows': None},
])
def test_an_invalid_worktrees_payload_is_unverified_with_no_rows(worktrees):
    out = _coord(_payload([], worktrees=worktrees))
    assert out['worktrees'] == {'status': 'UNVERIFIED', 'reason': MISSING_WORKTREES, 'rows': []}


def test_an_unverified_worktrees_payload_keeps_its_reason():
    assert _worktrees_of(status='UNVERIFIED', reason='git worktree list failed') == {
        'status': 'UNVERIFIED', 'reason': 'git worktree list failed', 'rows': []}


def test_an_unverified_worktrees_payload_without_a_reason_gets_the_default():
    assert _worktrees_of(status='UNVERIFIED')['reason'] == MISSING_WORKTREES


def test_a_measured_worktrees_payload_has_no_reason_when_none_is_given():
    assert _worktrees_of()['reason'] is None


def test_worktree_rows_map_to_camel_case_and_keep_their_order():
    rows = [_worktree_row('/w/a', state='dirty', cleanup='pending', item_id='T-7', head='0123456789'),
            _worktree_row('/repo', branch='main', item_id=None, state='clean', cleanup='none', main=True)]
    assert _worktrees_of(rows) == {'status': 'MEASURED', 'reason': None, 'rows': [
        {'path': '/w/a', 'branch': 'feat/a', 'head': '0123456789', 'itemId': 'T-7', 'state': 'dirty',
         'cleanup': 'pending', 'main': False},
        {'path': '/repo', 'branch': 'main', 'head': 'abcdef1234567890', 'itemId': None, 'state': 'clean',
         'cleanup': 'none', 'main': True}]}


@pytest.mark.parametrize('state', WORKTREE_STATES)
def test_every_contract_worktree_state_is_kept(state):
    assert _worktrees_of([_worktree_row('/w/a', state=state)])['rows'][0]['state'] == state


@pytest.mark.parametrize('cleanup', ['none', 'pending', 'locked'])
def test_every_contract_cleanup_is_kept(cleanup):
    assert _worktrees_of([_worktree_row('/w/a', cleanup=cleanup)])['rows'][0]['cleanup'] == cleanup


def test_an_unknown_worktree_state_is_unknown_and_an_unknown_cleanup_is_pending():
    row = _worktrees_of([_worktree_row('/w/a', state='weird', cleanup='weird', main='yes')])['rows'][0]
    assert (row['state'], row['cleanup'], row['main']) == ('unknown', 'pending', False)


def test_missing_branch_and_head_are_null():
    row = _worktrees_of([_worktree_row('/w/a', branch=None, head=None, item_id=None)])['rows'][0]
    assert (row['branch'], row['head'], row['itemId']) == (None, None, None)


def test_worktree_rows_without_a_path_are_skipped_and_a_repeated_path_counts_once():
    rows = [None, 'x', {'branch': 'b', 'state': 'clean'}, _worktree_row('/w/a', state='clean'),
            _worktree_row('/w/a', state='dirty')]
    out = _worktrees_of(rows)
    assert [(row['path'], row['state']) for row in out['rows']] == [('/w/a', 'clean')]


def test_the_model_does_not_add_worktrees_to_the_columns_or_the_counts():
    out = _coord(_payload([_item('a', 'ready')], worktrees={'status': 'MEASURED', 'rows': [_worktree_row('/w/a')]}))
    assert out['total'] == 1
    assert _column(out, 'ready')['count'] == 1


def test_the_coordination_module_reads_no_dom_and_no_clock():
    text = MODULE.read_text(encoding='utf-8')
    for pattern in (r'\bdocument\b', r'\bwindow\b', r'\bDate\.now\b', r'new Date\(', r'\bperformance\.now\b',
                    r'\binnerHTML\b', r'\beval\s*\(', r'https?://'):
        assert re.search(pattern, text) is None, pattern
