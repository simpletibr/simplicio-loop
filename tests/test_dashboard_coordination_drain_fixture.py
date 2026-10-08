'''Acceptance test for the coordination view on a synthetic 12-item drain (issue #1407).

The backlog is written to tmp_path as JSONL: one master line, then 12 item lines, 3 workers. Every expectation is
measured at a fixed ``now`` so the result never depends on the wall clock.

Shape of the drain:
  diamond  A -> B, A -> C, (B, C) -> D
  chain    E -> F -> G -> H
  done     A, E
  leases   B (w-live, fresh), C (w-stale, half TTL passed), I (w-expired, past expiry)
  blocked  D (by B and C), G (by F), H (by G)

The route check goes through GET /api/coordination over a real socket, with the coordination clock frozen at NOW.
'''
import http.client
import json
import time
from datetime import UTC, datetime

import pytest

from simplicio_loop.dashboard import coordination

NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC).timestamp()
REVISION = 7
TOKEN = 'drain-fixture-token-0123'
AUTH = {'Authorization': 'Bearer ' + TOKEN}
TIMEOUT = 5
ROUTE = '/api/coordination'
BACKLOG_PARTS = ('.simplicio-loop', 'orchestrator', 'backlog', 'backlog.jsonl')
COLUMN_KEYS = ['ready', 'claimed', 'running', 'verifying', 'done', 'blocked']
STATUS_TO_COLUMN = {
    'ready': 'ready', 'claimed': 'claimed', 'running': 'running',
    'verification': 'verifying', 'delivery': 'verifying', 'done': 'done',
}


def _lease(worker, heartbeat_at, expires_at):
    return {'worker': worker, 'heartbeat_at': heartbeat_at, 'expires_at': expires_at, 'ttl_seconds': 900}


def _drain_records():
    return [
        {'kind': 'master', 'revision': REVISION, 'goal': 'Drain the 12-item coordination fixture'},
        {'kind': 'item', 'id': 'A', 'goal': 'diamond root', 'status': 'done', 'priority': 1, 'depends_on': [],
         'frozen_at': '2026-10-08T08:00:00Z', 'done_at': '2026-10-08T08:30:00Z'},
        {'kind': 'item', 'id': 'B', 'goal': 'diamond left', 'status': 'claimed', 'priority': 2,
         'depends_on': ['A'], 'worker': 'w-live',
         'lease': _lease('w-live', '2026-10-08T11:59:00Z', '2026-10-08T12:14:00Z')},
        {'kind': 'item', 'id': 'C', 'goal': 'diamond right', 'status': 'running', 'priority': 3,
         'depends_on': ['A'], 'worker': 'w-stale',
         'lease': _lease('w-stale', '2026-10-08T11:50:00Z', '2026-10-08T12:05:00Z')},
        {'kind': 'item', 'id': 'D', 'goal': 'diamond join', 'status': 'ready', 'priority': 4,
         'depends_on': ['B', 'C']},
        {'kind': 'item', 'id': 'E', 'goal': 'chain root', 'status': 'done', 'priority': 5, 'depends_on': [],
         'frozen_at': '2026-10-08T08:10:00Z', 'done_at': '2026-10-08T09:00:00Z'},
        {'kind': 'item', 'id': 'F', 'goal': 'chain one', 'status': 'ready', 'priority': 6, 'depends_on': ['E']},
        {'kind': 'item', 'id': 'G', 'goal': 'chain two', 'status': 'ready', 'priority': 7, 'depends_on': ['F']},
        {'kind': 'item', 'id': 'H', 'goal': 'chain three', 'status': 'ready', 'priority': 8, 'depends_on': ['G']},
        {'kind': 'item', 'id': 'I', 'goal': 'expired lease', 'status': 'claimed', 'priority': 9, 'depends_on': [],
         'worker': 'w-expired',
         'lease': _lease('w-expired', '2026-10-08T11:43:20Z', '2026-10-08T11:58:20Z')},
        {'kind': 'item', 'id': 'J', 'goal': 'in verification', 'status': 'verification', 'priority': 10,
         'depends_on': []},
        {'kind': 'item', 'id': 'K', 'goal': 'in delivery', 'status': 'delivery', 'priority': 11, 'depends_on': []},
        {'kind': 'item', 'id': 'L', 'goal': 'failed, no dependency', 'status': 'failed', 'priority': 12,
         'depends_on': []},
    ]


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(record) + '\n' for record in records), encoding='utf-8')
    return path


def _fixture_items(records):
    return [record for record in records if record.get('kind') == 'item']


def _expected_columns_from_fixture(records):
    '''Column counts derived from the raw fixture records, not from the builder output.'''
    items = _fixture_items(records)
    statuses = {item['id']: item['status'] for item in items}
    counts = {column: 0 for column in COLUMN_KEYS}
    for item in items:
        column = STATUS_TO_COLUMN.get(item['status'], 'blocked')
        unmet = [dep for dep in item['depends_on'] if statuses[dep] != 'done']
        if column == 'ready' and unmet:
            column = 'blocked'
        counts[column] += 1
    return counts


def _expected_edges_from_fixture(records):
    statuses = {item['id']: item['status'] for item in _fixture_items(records)}
    return {(dep, item['id']): statuses[dep] == 'done'
            for item in _fixture_items(records) for dep in item['depends_on']}


def _assert_drain_payload(payload):
    assert payload['status'] == 'MEASURED'
    assert payload['revision'] == REVISION

    records = _drain_records()

    # Columns: literal anchors, and the same counts recomputed from the fixture.
    counts = {column['key']: column['count'] for column in payload['columns']}
    assert [column['key'] for column in payload['columns']] == COLUMN_KEYS
    assert counts == {'ready': 1, 'claimed': 2, 'running': 1, 'verifying': 2, 'done': 2, 'blocked': 4}
    assert counts == _expected_columns_from_fixture(records)

    # Items: one per fixture item, with the column the fixture implies.
    items = {item['id']: item for item in payload['items']}
    assert sorted(items) == sorted(item['id'] for item in _fixture_items(records))
    for fixture in _fixture_items(records):
        assert items[fixture['id']]['depends_on'] == fixture['depends_on']
    assert {iid: item['column'] for iid, item in items.items()} == {
        'A': 'done', 'B': 'claimed', 'C': 'running', 'D': 'blocked', 'E': 'done', 'F': 'ready',
        'G': 'blocked', 'H': 'blocked', 'I': 'claimed', 'J': 'verifying', 'K': 'verifying', 'L': 'blocked',
    }

    # Blocked items: the exact unfinished dependencies that hold them back.
    assert items['G']['blocked_by'] == ['F']
    assert items['H']['blocked_by'] == ['G']
    assert items['D']['blocked_by'] == ['B', 'C']
    assert items['L']['blocked_by'] == []
    assert items['F']['blocked_by'] == []

    # Edges: exactly the (dependency, dependent) pairs of the fixture, with satisfied == dependency is done.
    edges = {(edge['from'], edge['to']): edge['satisfied'] for edge in payload['edges']}
    assert len(payload['edges']) == len(edges) == 7
    assert edges == _expected_edges_from_fixture(records)
    assert edges == {('A', 'B'): True, ('A', 'C'): True, ('B', 'D'): False, ('C', 'D'): False,
                     ('E', 'F'): True, ('F', 'G'): False, ('G', 'H'): False}

    # Drain: 12 items, 2 done, 10 remaining, 4 blocked, 16 percent (2 * 100 / 12 truncated).
    drain = payload['drain']
    assert (drain['total'], drain['done'], drain['remaining'], drain['blocked'], drain['percent']) == (
        12, 2, 10, 4, 16)
    # Rate: done spans 08:00:00 to 09:00:00 (3600 s) over 2 done items, so 10 * 3600 / 2 = 18000 s.
    assert (drain['eta_s'], drain['eta_label'], drain['reason']) == (18000, 'ESTIMATE', None)

    # Leases: live, stale and expired at NOW.
    assert items['B']['lease']['state'] == 'live' and items['B']['lease']['remaining_s'] == 840
    assert items['C']['lease']['state'] == 'stale' and items['C']['lease']['age_s'] == 600
    assert items['I']['lease']['state'] == 'expired' and items['I']['lease']['remaining_s'] == 0
    assert items['A']['lease'] is None and items['F']['lease'] is None

    # Slots: one per leasing worker, sorted by worker name, reclaimable only when every lease has expired.
    assert payload['slots'] == [
        {'worker': 'w-expired', 'items': ['I'], 'state': 'expired', 'reclaimable': True},
        {'worker': 'w-live', 'items': ['B'], 'state': 'live', 'reclaimable': False},
        {'worker': 'w-stale', 'items': ['C'], 'state': 'stale', 'reclaimable': False},
    ]


@pytest.fixture
def backlog_path(tmp_path):
    return _write_jsonl(tmp_path / 'drain' / 'backlog.jsonl', _drain_records())


def test_fixture_has_the_required_shape():
    records = _drain_records()
    items = _fixture_items(records)
    assert len(items) == 12
    assert sum(1 for r in records if r.get('kind') == 'master') == 1
    assert sum(1 for item in items if item['status'] == 'done') >= 2
    workers = {item['lease']['worker'] for item in items if 'lease' in item}
    assert workers == {'w-live', 'w-stale', 'w-expired'}


def test_builder_on_drain_fixture_matches_fixture(backlog_path):
    payload = coordination.build_coordination(backlog_path, now=NOW)
    _assert_drain_payload(payload)


def test_builder_on_drain_fixture_is_deterministic(backlog_path):
    first = coordination.build_coordination(backlog_path, now=NOW)
    second = coordination.build_coordination(backlog_path, now=NOW)
    assert first == second


@pytest.fixture
def server_handle(tmp_path, monkeypatch):
    from simplicio_loop.dashboard import server
    monkeypatch.delenv('SIMPLICIO_BACKLOG_FILE', raising=False)
    repo = tmp_path / 'repo'
    repo.mkdir()
    _write_jsonl(repo.joinpath(*BACKLOG_PARTS), _drain_records())
    handle = server.start(repo_root=repo, host='127.0.0.1', port=0, token=TOKEN)
    try:
        yield handle
    finally:
        handle.stop()


def test_route_on_drain_fixture_matches_builder(server_handle, monkeypatch):
    # The route measures at the wall clock; freeze only the coordination module's clock so leases match NOW.
    class _FrozenClock:
        strptime = staticmethod(time.strptime)

        @staticmethod
        def time():
            return NOW

    monkeypatch.setattr(coordination, 'time', _FrozenClock)
    conn = http.client.HTTPConnection('127.0.0.1', server_handle.port, timeout=TIMEOUT)
    try:
        conn.request('GET', ROUTE, headers=AUTH)
        resp = conn.getresponse()
        assert resp.status == 200
        payload = json.loads(resp.read())
    finally:
        conn.close()
    _assert_drain_payload(payload)
