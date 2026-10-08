'''Unit tests for the coordination view of the Simplicio Live dashboard (GET /api/coordination, TDD red).

``build_coordination`` reads a task backlog JSONL (one master line, then one item line per work item) and derives
the kanban columns, dependency edges, lease health, drain progress and worker slots. The 12-item drain fixture has
3 workers, a dependency chain, one expired lease, one stale lease and a ready item held back by its dependency.
Every lease expectation is measured at an injected ``now`` so the results never depend on the wall clock.
'''
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from simplicio_loop.dashboard import coordination

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'coordination' / 'drain12.jsonl'
NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC).timestamp()
COLUMN_KEYS = ['ready', 'claimed', 'running', 'verifying', 'done', 'blocked']
TOP_KEYS = {'status', 'revision', 'columns', 'items', 'edges', 'drain', 'slots'}
ITEM_KEYS = {'id', 'goal', 'status', 'column', 'priority', 'depends_on', 'blocked_by', 'worker', 'lease'}


def _stamp(epoch):
    return datetime.fromtimestamp(epoch, UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def _lease(worker, heartbeat, expires, ttl=900):
    lease = {'worker': worker, 'claimed_at': heartbeat, 'heartbeat_at': heartbeat, 'expires_at': expires}
    if ttl is not None:
        lease['ttl_seconds'] = ttl
    return lease


def _item(iid, status='ready', depends_on=(), lease=None, **extra):
    obj = {'kind': 'item', 'id': iid, 'goal': f'Goal {iid}', 'status': status, 'depends_on': list(depends_on),
           'priority': 100, 'lease': lease or {}, 'frozen_at': '2026-10-08T09:00:00Z'}
    obj.update(extra)
    return obj


def _write(tmp_path, *objs, raw=None):
    path = tmp_path / 'backlog.jsonl'
    lines = raw if raw is not None else [json.dumps(obj) for obj in objs]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def _columns(payload):
    return {column['key']: column['count'] for column in payload['columns']}


def _by_id(payload):
    return {item['id']: item for item in payload['items']}


@pytest.fixture
def drain():
    return coordination.build_coordination(FIXTURE, now=NOW)


def test_fixture_loads_as_a_measured_twelve_item_drain(drain):
    assert drain['status'] == 'MEASURED'
    assert drain['revision'] == 7
    assert [item['id'] for item in drain['items']] == list('ABCDEFGHIJKL')
    assert {item['worker'] for item in drain['items'] if item['worker']} == {'w1', 'w2', 'w3'}


def test_payload_has_the_contract_keys(drain):
    assert set(drain) == TOP_KEYS
    assert all(set(item) == ITEM_KEYS for item in drain['items'])


def test_columns_are_the_six_kanban_columns_in_order_with_counts(drain):
    assert [column['key'] for column in drain['columns']] == COLUMN_KEYS
    assert _columns(drain) == {'ready': 2, 'claimed': 1, 'running': 2, 'verifying': 1, 'done': 3, 'blocked': 3}


def test_each_fixture_item_lands_in_its_column(drain):
    columns = {item['id']: item['column'] for item in drain['items']}
    assert columns == {
        'A': 'done', 'B': 'done', 'C': 'done',
        'D': 'running', 'E': 'running',
        'F': 'claimed',
        'G': 'verifying',
        'H': 'blocked', 'I': 'blocked',
        'J': 'ready', 'K': 'ready',
        'L': 'blocked',
    }


def test_a_ready_item_held_by_an_unmet_dependency_shows_its_raw_status_in_blocked(drain):
    held = _by_id(drain)['H']
    assert held['status'] == 'ready'
    assert held['column'] == 'blocked'


@pytest.mark.parametrize('status, column', [
    ('running', 'running'),
    ('claimed', 'claimed'),
    ('verification', 'verifying'),
    ('delivery', 'verifying'),
    ('done', 'done'),
    ('blocked', 'blocked'),
    ('failed', 'blocked'),
    ('quarantined', 'blocked'),
    ('dead-letter', 'blocked'),
    ('cancelled', 'blocked'),
    ('skipped', 'blocked'),
    ('invented-status', 'blocked'),
])
def test_status_names_map_onto_columns(tmp_path, status, column):
    path = _write(tmp_path, _item('X', status=status))
    payload = coordination.build_coordination(path, now=NOW)
    assert payload['items'][0]['column'] == column
    assert payload['items'][0]['status'] == status


def test_edges_are_the_dependency_graph_with_satisfied_flags(drain):
    edges = sorted((edge['from'], edge['to'], edge['satisfied']) for edge in drain['edges'])
    assert edges == [
        ('A', 'B', True),
        ('A', 'K', True),
        ('B', 'D', True),
        ('B', 'K', True),
        ('C', 'G', True),
        ('D', 'H', False),
        ('H', 'I', False),
        ('J', 'L', False),
    ]


def test_edges_skip_dependencies_that_are_not_in_the_backlog(tmp_path):
    path = _write(tmp_path, _item('Y'), _item('X', depends_on=['GHOST', 'Y']))
    payload = coordination.build_coordination(path, now=NOW)
    assert [(edge['from'], edge['to']) for edge in payload['edges']] == [('Y', 'X')]


def test_blocked_by_lists_unmet_dependencies_of_non_done_items_only(drain):
    blocked_by = {item['id']: item['blocked_by'] for item in drain['items']}
    assert blocked_by == {
        'A': [], 'B': [], 'C': [],
        'D': [], 'E': [], 'F': [], 'G': [],
        'H': ['D'], 'I': ['H'],
        'J': [], 'K': [],
        'L': ['J'],
    }


def test_a_missing_dependency_counts_as_unmet_in_blocked_by(tmp_path):
    path = _write(tmp_path, _item('X', depends_on=['GHOST']))
    payload = coordination.build_coordination(path, now=NOW)
    assert payload['items'][0]['blocked_by'] == ['GHOST']
    assert payload['items'][0]['column'] == 'blocked'


def test_a_live_lease_reports_its_age_and_remaining_seconds(drain):
    lease = _by_id(drain)['D']['lease']
    assert lease == {'worker': 'w1', 'heartbeat_at': '2026-10-08T11:55:00Z', 'expires_at': '2026-10-08T12:10:00Z',
                     'age_s': 300, 'remaining_s': 600, 'state': 'live'}
    assert _by_id(drain)['D']['worker'] == 'w1'


def test_a_lease_whose_heartbeat_is_recent_is_live_even_near_expiry(drain):
    lease = _by_id(drain)['G']['lease']
    assert (lease['state'], lease['age_s'], lease['remaining_s']) == ('live', 120, 780)


def test_an_expired_lease_has_zero_remaining_seconds(drain):
    lease = _by_id(drain)['E']['lease']
    assert (lease['state'], lease['age_s'], lease['remaining_s']) == ('expired', 1800, 0)


def test_a_stale_lease_is_past_half_its_ttl_but_not_yet_expired(drain):
    lease = _by_id(drain)['F']['lease']
    assert (lease['state'], lease['age_s'], lease['remaining_s']) == ('stale', 1200, 600)


def test_unleased_items_have_null_lease_and_worker(drain):
    item = _by_id(drain)['A']
    assert item['lease'] is None
    assert item['worker'] is None


def test_a_heartbeat_exactly_half_the_ttl_old_is_still_live(tmp_path):
    heartbeat = _stamp(NOW - 450)
    path = _write(tmp_path, _item('X', status='running', lease=_lease('w1', heartbeat, _stamp(NOW + 450))))
    assert coordination.build_coordination(path, now=NOW)['items'][0]['lease']['state'] == 'live'


def test_a_heartbeat_one_second_past_half_the_ttl_is_stale(tmp_path):
    heartbeat = _stamp(NOW - 451)
    path = _write(tmp_path, _item('X', status='running', lease=_lease('w1', heartbeat, _stamp(NOW + 449))))
    assert coordination.build_coordination(path, now=NOW)['items'][0]['lease']['state'] == 'stale'


def test_a_lease_expiring_exactly_now_is_expired(tmp_path):
    path = _write(tmp_path, _item('X', status='running', lease=_lease('w1', _stamp(NOW - 10), _stamp(NOW))))
    assert coordination.build_coordination(path, now=NOW)['items'][0]['lease']['state'] == 'expired'


def test_missing_ttl_defaults_to_900_seconds(tmp_path):
    path = _write(tmp_path,
                  _item('LATE', status='running', lease=_lease('w1', _stamp(NOW - 500), _stamp(NOW + 400), ttl=None)),
                  _item('FRESH', status='running', lease=_lease('w2', _stamp(NOW - 400), _stamp(NOW + 500), ttl=None)))
    states = {item['id']: item['lease']['state'] for item in coordination.build_coordination(path, now=NOW)['items']}
    assert states == {'LATE': 'stale', 'FRESH': 'live'}


def test_an_unparsable_expiry_is_expired_and_an_unparsable_heartbeat_is_stale(tmp_path):
    path = _write(tmp_path,
                  _item('BADEXP', status='running', lease=_lease('w1', _stamp(NOW - 10), 'not-a-time')),
                  _item('BADHB', status='running', lease=_lease('w2', 'yesterday', _stamp(NOW + 800))))
    leases = {item['id']: item['lease'] for item in coordination.build_coordination(path, now=NOW)['items']}
    assert leases['BADEXP']['state'] == 'expired'
    assert leases['BADEXP']['remaining_s'] == 0
    assert leases['BADHB']['state'] == 'stale'
    assert leases['BADHB']['age_s'] is None


def test_drain_reports_total_done_remaining_blocked_and_percent(drain):
    assert drain['drain'] == {
        'total': 12, 'done': 3, 'remaining': 9, 'blocked': 3, 'percent': 25,
        'eta_s': 10800, 'eta_label': 'ESTIMATE', 'reason': None,
    }


def test_eta_is_an_estimate_from_the_done_items_timestamps(drain):
    # Three done items frozen at 09:00Z, the last one done at 10:00Z: 3 items in 3600s, so 9 left take 10800s.
    assert drain['drain']['eta_s'] == 10800
    assert drain['drain']['eta_label'] == 'ESTIMATE'


def test_eta_is_unverified_with_fewer_than_two_done_items(tmp_path):
    one_done = _write(tmp_path, _item('A', status='done', done_at='2026-10-08T09:20:00Z'), _item('B'))
    drain_one = coordination.build_coordination(one_done, now=NOW)['drain']
    assert drain_one['eta_s'] is None
    assert drain_one['eta_label'] == 'UNVERIFIED'
    assert drain_one['reason']

    no_done = _write(tmp_path, _item('C'))
    drain_none = coordination.build_coordination(no_done, now=NOW)['drain']
    assert (drain_none['eta_s'], drain_none['eta_label']) == (None, 'UNVERIFIED')


def test_eta_is_unverified_when_a_done_item_lacks_its_done_timestamp(tmp_path):
    path = _write(tmp_path,
                  _item('A', status='done', done_at='2026-10-08T09:20:00Z'),
                  _item('B', status='done'),
                  _item('C'))
    drain = coordination.build_coordination(path, now=NOW)['drain']
    assert (drain['eta_s'], drain['eta_label']) == (None, 'UNVERIFIED')
    assert drain['reason']


def test_drain_percent_is_zero_for_an_empty_backlog(tmp_path):
    path = _write(tmp_path, {'kind': 'master', 'revision': 1})
    drain = coordination.build_coordination(path, now=NOW)['drain']
    assert (drain['total'], drain['percent']) == (0, 0)


def test_slots_list_each_worker_with_its_items_and_worst_lease_state(drain):
    assert drain['slots'] == [
        {'worker': 'w1', 'items': ['D', 'G'], 'state': 'live', 'reclaimable': False},
        {'worker': 'w2', 'items': ['E'], 'state': 'expired', 'reclaimable': True},
        {'worker': 'w3', 'items': ['F'], 'state': 'stale', 'reclaimable': False},
    ]


def test_only_a_worker_whose_leases_have_all_expired_is_reclaimable(tmp_path):
    expired = _lease('w1', _stamp(NOW - 900), _stamp(NOW - 1))
    live = _lease('w1', _stamp(NOW - 10), _stamp(NOW + 890))
    path = _write(tmp_path,
                  _item('OLD', status='running', lease=expired),
                  _item('NEW', status='running', lease=live))
    slot = coordination.build_coordination(path, now=NOW)['slots'][0]
    assert (slot['worker'], slot['items'], slot['state'], slot['reclaimable']) == ('w1', ['OLD', 'NEW'], 'expired', False)


def test_no_slots_when_no_item_holds_a_lease(tmp_path):
    path = _write(tmp_path, _item('A', status='done', done_at='2026-10-08T09:20:00Z'), _item('B'))
    assert coordination.build_coordination(path, now=NOW)['slots'] == []


def test_edges_and_blocked_by_are_empty_for_a_chainless_backlog(tmp_path):
    path = _write(tmp_path, _item('A'), _item('B'))
    payload = coordination.build_coordination(path, now=NOW)
    assert payload['edges'] == []
    assert [item['blocked_by'] for item in payload['items']] == [[], []]


def test_priority_defaults_to_100_when_missing_or_invalid(tmp_path):
    path = _write(tmp_path, _item('A', priority='urgent'), _item('B', priority=5), {'kind': 'item', 'id': 'C', 'goal': 'g', 'status': 'ready'})
    priorities = {item['id']: item['priority'] for item in coordination.build_coordination(path, now=NOW)['items']}
    assert priorities == {'A': 100, 'B': 5, 'C': 100}


def test_revision_is_zero_when_the_backlog_has_no_master_line(tmp_path):
    path = _write(tmp_path, _item('A'))
    payload = coordination.build_coordination(path, now=NOW)
    assert payload['status'] == 'MEASURED'
    assert payload['revision'] == 0


def test_build_uses_the_wall_clock_when_now_is_omitted():
    payload = coordination.build_coordination(FIXTURE)
    assert payload['status'] == 'MEASURED'
    assert len(payload['items']) == 12


def test_a_missing_file_fails_open_to_an_unverified_empty_view(tmp_path):
    payload = coordination.build_coordination(tmp_path / 'absent.jsonl', now=NOW)
    assert set(payload) == {'status', 'reason', 'columns', 'items', 'edges', 'drain', 'slots'}
    assert payload['status'] == 'UNVERIFIED'
    assert payload['reason']
    assert _columns(payload) == {key: 0 for key in COLUMN_KEYS}
    assert (payload['items'], payload['edges'], payload['drain'], payload['slots']) == ([], [], None, [])


def test_a_directory_in_place_of_the_file_fails_open(tmp_path):
    payload = coordination.build_coordination(tmp_path, now=NOW)
    assert payload['status'] == 'UNVERIFIED'
    assert payload['items'] == []


@pytest.mark.parametrize('bad_line', ['{"kind": "item", "id": "A"', '[1, 2, 3]'])
def test_a_malformed_or_non_object_line_fails_open(tmp_path, bad_line):
    path = _write(tmp_path, raw=[json.dumps(_item('A')), bad_line])
    payload = coordination.build_coordination(path, now=NOW)
    assert payload['status'] == 'UNVERIFIED'
    assert payload['reason']
    assert payload['items'] == []


def test_lines_of_an_unknown_kind_are_ignored(tmp_path):
    path = _write(tmp_path, _item('A'), {'kind': 'note', 'text': 'ignored'})
    payload = coordination.build_coordination(path, now=NOW)
    assert payload['status'] == 'MEASURED'
    assert [item['id'] for item in payload['items']] == ['A']
