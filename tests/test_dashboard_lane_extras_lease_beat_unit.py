'''The watcher's `lease_heartbeat` events are the measured line of the lease-heartbeat row of the extras (#1551).

The row is read from the run's own events: the age is the `ts` of the latest beat of each lease key against the clock
passed in, a beat is stale once it is older than the `ttl_s` it carries, and a `lost` beat is stale at any age. Beats and
the Mapper/backlog lanes of `worker_claimed` share the row; an event that names no lease key is ignored.
'''
import time

from simplicio_loop.dashboard import lane_extras

EVENT_SCHEMA = 'simplicio.dashboard-event/v1'
NOW = 1_790_000_000.0
KEY = 'repo-a#7'


def _utc(offset=0.0):
    return time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(NOW + offset))


def _beat(seq, ago, key=KEY, status='renewed', ttl=180, beats=1, **extra):
    payload = {'lease_key': key, 'status': status, 'beats': beats, 'ttl_s': ttl}
    payload.update(extra)
    return {'schema': EVENT_SCHEMA, 'seq': seq, 'kind': 'lease_heartbeat', 'lane': None, 'ts': _utc(-ago),
            'payload': payload}


def _claim(seq, lane, lease_id):
    return {'schema': EVENT_SCHEMA, 'seq': seq, 'kind': 'worker_claimed', 'lane': lane, 'task_id': 'T1',
            'ts': _utc(-1), 'payload': {'lease_id': lease_id}}


def _heartbeat(tmp_path, events):
    return lane_extras.extras(tmp_path, events, backlog_path=tmp_path / 'none.jsonl', now=NOW)['heartbeat']


def test_a_beat_is_a_measured_row_with_its_age_from_the_event_clock(tmp_path):
    got = _heartbeat(tmp_path, [_beat(1, 25)])
    assert got['state'] == 'PASS'
    assert got['lanes'] == [{'lane': KEY, 'lease_id': KEY, 'state': 'MEASURED', 'heartbeat_at': _utc(-25), 'age_s': 25,
                             'stale': False, 'reason': None, 'source': 'lease_heartbeat',
                             'status': 'renewed'}]
    assert got['reason'] == f'{KEY}: último batimento há 25 s'


def test_the_age_follows_the_clock_passed_in(tmp_path):
    events = [_beat(1, 0)]
    first = lane_extras.extras(tmp_path, events, now=NOW + 10)['heartbeat']['lanes'][0]
    later = lane_extras.extras(tmp_path, events, now=NOW + 70)['heartbeat']['lanes'][0]
    assert (first['age_s'], later['age_s']) == (10, 70)


def test_a_beat_older_than_its_ttl_is_flagged_stale_and_one_inside_it_is_not(tmp_path):
    inside, outside = (_heartbeat(tmp_path, [_beat(1, age, ttl=180)])['lanes'][0] for age in (180, 181))
    assert (inside['stale'], outside['stale']) == (False, True)
    assert _heartbeat(tmp_path, [_beat(1, 181, ttl=180)])['reason'] == f'{KEY}: último batimento há 181 s (obsoleto)'


def test_a_lost_lease_is_stale_at_any_age_and_says_so(tmp_path):
    got = _heartbeat(tmp_path, [_beat(1, 2, status='lost')])
    assert got['lanes'][0]['stale'] is True and got['lanes'][0]['age_s'] == 2
    assert got['reason'] == f'{KEY}: lease perdido há 2 s'


def test_the_latest_beat_of_a_key_wins_by_seq_and_each_key_has_its_own_row(tmp_path):
    events = [_beat(3, 5, beats=3), _beat(1, 125, beats=1), _beat(2, 65, beats=2), _beat(4, 1, key='repo-b#2')]
    lanes = _heartbeat(tmp_path, events)['lanes']
    assert [(row['lane'], row['age_s']) for row in lanes] == [(KEY, 5), ('repo-b#2', 1)]


def test_a_renewal_after_a_loss_makes_the_lease_live_again(tmp_path):
    row = _heartbeat(tmp_path, [_beat(1, 30, status='lost'), _beat(2, 10)])['lanes'][0]
    assert (row['age_s'], row['stale']) == (10, False)


def test_a_future_or_unreadable_ts_is_unverified_with_the_reason(tmp_path):
    future = _heartbeat(tmp_path, [_beat(1, -100)])
    assert future['state'] == 'UNVERIFIED'
    assert future['lanes'][0]['reason'] == 'lease_heartbeat no futuro do relógio'
    broken = dict(_beat(1, 5), ts='ontem')
    row = _heartbeat(tmp_path, [broken])['lanes'][0]
    assert (row['state'], row['age_s'], row['reason']) == ('UNVERIFIED', None, 'lease_heartbeat sem ts medido')


def test_a_beat_without_a_usable_ttl_is_unverified_never_assumed_live(tmp_path):
    for ttl in (None, 0, -5, 'x', True):
        row = _heartbeat(tmp_path, [_beat(1, 5, ttl=ttl)])['lanes'][0]
        assert (row['state'], row['stale'], row['reason']) == ('UNVERIFIED', None, 'lease_heartbeat sem ttl_s medido')


def test_an_event_without_a_lease_key_is_ignored(tmp_path):
    no_key = dict(_beat(1, 5), payload={'status': 'renewed', 'ttl_s': 180})
    blank = _beat(2, 5, key='')
    assert _heartbeat(tmp_path, [no_key, blank]) == {'state': 'UNVERIFIED', 'reason': lane_extras.NO_LANE_REASON, 'lanes': []}


def test_beats_and_claimed_lanes_share_the_row_in_the_same_reply(tmp_path):
    got = _heartbeat(tmp_path, [_claim(1, 'lane-a', 'lease-x'), _beat(2, 30)])
    assert [row['lane'] for row in got['lanes']] == ['lane-a', KEY]
    assert got['lanes'][0]['state'] == 'UNVERIFIED' and got['lanes'][1]['state'] == 'MEASURED'
    assert got['state'] == 'PASS'
    assert got['reason'].endswith(f'{KEY}: último batimento há 30 s') and 'lane-a:' in got['reason']


def test_the_row_stays_capped_at_the_item_limit(tmp_path):
    events = [_beat(i + 1, 5, key=f'repo#{i:03d}') for i in range(lane_extras.MAX_ITEMS + 10)]
    assert len(_heartbeat(tmp_path, events)['lanes']) == lane_extras.MAX_ITEMS


def test_other_event_kinds_never_make_a_beat(tmp_path):
    other = dict(_beat(1, 5), kind='lane_progress')
    assert _heartbeat(tmp_path, [other])['lanes'] == []
