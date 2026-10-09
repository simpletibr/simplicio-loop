'''Unit tests for the per-run extras of the Simplicio Live dashboard (TDD red).

The extras are the last measured test or lint command, the declared task list, the model used per lane with its token
totals, and the heartbeat of each lane's lease. A lane's lease_id (from its worker_claimed event) is mapped to the
backlog lease written by scripts/task_backlog.py and read through the coordination reader; the age is measured against a
clock passed in. A lane with no lease_id, or whose lease is not in the backlog, stays UNVERIFIED with the reason. The
reader is a pure function of the run directory, the events, the backlog file and the clock, so no server is needed.
'''
import json
import time

from simplicio_loop.dashboard import budget, lane_extras

SCHEMA = 'simplicio.dashboard-extras/v1'
EVENT_SCHEMA = 'simplicio.dashboard-event/v1'
NOW = 1_790_000_000.0
NO_LANE = {'state': 'UNVERIFIED', 'reason': 'nenhuma lane com lease_id registrado', 'lanes': []}


def _utc(offset=0.0):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(NOW + offset))


def _backlog(tmp_path, leases):
    '''A backlog.jsonl like task_backlog.py writes: a master line, then one item line per task with its lease.'''
    lines = [json.dumps({'kind': 'master', 'revision': 1})]
    for task_id, lease in leases.items():
        lines.append(json.dumps({'kind': 'item', 'id': task_id, 'status': 'running', 'lease': lease}))
    path = tmp_path / 'backlog.jsonl'
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def _lease(heartbeat_ago, ttl=900, **ids):
    return {'worker': 'w1', 'claimed_at': _utc(-heartbeat_ago), 'heartbeat_at': _utc(-heartbeat_ago),
            'ttl_seconds': ttl, 'expires_at': _utc(ttl - heartbeat_ago), **ids}


def _claim(seq, lane, lease_id, task_id='T1'):
    event = _event(seq, 'worker_claimed', {'lease_id': lease_id}, lane=lane)
    return dict(event, task_id=task_id)


def _event(seq, kind, payload=None, lane=None, ts=None):
    return {'schema': EVENT_SCHEMA, 'seq': seq, 'kind': kind, 'lane': lane,
            'ts': ts or f'2026-10-08T10:00:{seq:02d}Z', 'payload': payload or {}}


def _contract(tmp_path, tasks):
    (tmp_path / 'task-contract.json').write_text(json.dumps({'tasks': tasks}), encoding='utf-8')


def test_an_empty_run_reports_no_extras_and_an_unverified_heartbeat(tmp_path):
    assert lane_extras.extras(tmp_path, []) == {'schema': SCHEMA, 'last_command': None, 'tasks': [],
                                                'models': [], 'heartbeat': NO_LANE}


def test_last_command_is_the_latest_test_or_lint_result_by_seq(tmp_path):
    events = [
        _event(3, 'lint_result', {'command': 'ruff check .'}, ts='2026-10-08T10:00:03Z'),
        _event(1, 'test_result', {'command': 'pytest -q'}),
        _event(2, 'test_result', {'command': ''}),
        _event(4, 'test_result', {'command': 7}),
        _event(9, 'phase_entered', {'command': 'rm -rf build'}),
    ]
    got = lane_extras.extras(tmp_path, events)['last_command']
    assert got == {'command': 'ruff check .', 'kind': 'lint_result', 'at': '2026-10-08T10:00:03Z'}


def test_events_of_another_schema_are_not_read(tmp_path):
    foreign = dict(_event(5, 'test_result', {'command': 'pytest -q'}), schema='other/v1')
    assert lane_extras.extras(tmp_path, [foreign, 'not an event'])['last_command'] is None


def test_last_command_is_redacted_and_cut_to_300_characters(tmp_path):
    command = 'pytest --token=hunter2hunter2 ' + 'x' * 400
    got = lane_extras.extras(tmp_path, [_event(1, 'test_result', {'command': command})])['last_command']
    assert 'hunter2hunter2' not in got['command']
    assert len(got['command']) == 300


def test_tasks_come_from_the_contract_with_id_and_title_fallbacks(tmp_path):
    _contract(tmp_path, [{'id': 't1', 'title': 'Add budget'}, {'task_id': 't2', 'name': 'Wire route'},
                         {'id': 't3'}, {'title': 'no identifier'}, 'not a dict'])
    assert lane_extras.extras(tmp_path, [])['tasks'] == [
        {'task_id': 't1', 'title': 'Add budget'}, {'task_id': 't2', 'title': 'Wire route'}]


def test_task_titles_are_redacted_and_cut_to_160_characters(tmp_path):
    _contract(tmp_path, [{'id': 't1', 'title': 'password=hunter2hunter2 ' + 'y' * 300}])
    title = lane_extras.extras(tmp_path, [])['tasks'][0]['title']
    assert 'hunter2hunter2' not in title
    assert len(title) == 160


def test_tasks_are_capped_at_fifty(tmp_path):
    _contract(tmp_path, [{'id': f't{i:02d}', 'title': f'T{i:02d}'} for i in range(60)])
    assert len(lane_extras.extras(tmp_path, [])['tasks']) == 50


def test_malformed_or_oversized_contracts_give_no_tasks(tmp_path):
    (tmp_path / 'task-contract.json').write_text('{oops', encoding='utf-8')
    assert lane_extras.extras(tmp_path, [])['tasks'] == []
    padded = {'tasks': [{'id': 't1', 'title': 'x'}], 'pad': 'a' * (budget.MAX_CONTRACT_BYTES + 10)}
    (tmp_path / 'task-contract.json').write_text(json.dumps(padded), encoding='utf-8')
    assert lane_extras.extras(tmp_path, [])['tasks'] == []


def test_models_sum_ints_per_lane_and_sort_by_lane(tmp_path):
    events = [
        _event(1, 'token_usage', {'model': 'model-a', 'input_tokens': 100, 'output_tokens': 20}, lane='lane-b'),
        _event(2, 'token_usage', {'model': 'model-b', 'input_tokens': 300, 'output_tokens': 50}, lane='lane-a'),
        _event(3, 'token_usage', {'model': 'model-c', 'input_tokens': 1, 'output_tokens': 2}, lane='lane-b'),
    ]
    assert lane_extras.extras(tmp_path, events)['models'] == [
        {'lane': 'lane-a', 'model': 'model-b', 'input_tokens': 300, 'output_tokens': 50},
        {'lane': 'lane-b', 'model': 'model-c', 'input_tokens': 101, 'output_tokens': 22},
    ]


def test_the_last_model_of_a_lane_wins_by_seq_not_by_list_order(tmp_path):
    events = [
        _event(5, 'token_usage', {'model': 'model-x', 'input_tokens': 1, 'output_tokens': 1}, lane='lane-a'),
        _event(4, 'token_usage', {'model': 'model-y', 'input_tokens': 1, 'output_tokens': 1}, lane='lane-a'),
    ]
    assert lane_extras.extras(tmp_path, events)['models'][0]['model'] == 'model-x'


def test_models_skip_events_without_a_model_or_a_lane_and_ignore_non_int_tokens(tmp_path):
    events = [
        _event(1, 'token_usage', {'input_tokens': 5}, lane='lane-a'),
        _event(2, 'token_usage', {'model': 'model-a', 'input_tokens': 2.5, 'output_tokens': True}, lane='lane-a'),
        _event(3, 'token_usage', {'model': 'model-a', 'input_tokens': 7}, lane=None),
        _event(4, 'token_usage', {'model': 'model-a', 'output_tokens': -4}, lane='lane-a'),
    ]
    assert lane_extras.extras(tmp_path, events)['models'] == [
        {'lane': 'lane-a', 'model': 'model-a', 'input_tokens': 0, 'output_tokens': 0}]


def test_models_are_capped_at_fifty_after_sorting_by_lane(tmp_path):
    events = [_event(i, 'token_usage', {'model': 'model-a', 'input_tokens': 1}, lane=f'lane-{99 - i:02d}')
              for i in range(60)]
    models = lane_extras.extras(tmp_path, events)['models']
    assert len(models) == 50
    assert [m['lane'] for m in models] == sorted(m['lane'] for m in models)
    assert models[0]['lane'] == 'lane-40'


def _heartbeat(tmp_path, events, backlog):
    return lane_extras.extras(tmp_path, events, backlog_path=backlog, now=NOW)['heartbeat']


def test_a_lane_lease_maps_to_the_backlog_heartbeat_with_its_age(tmp_path):
    backlog = _backlog(tmp_path, {'T1': _lease(30, attempt_id='attempt-abc')})
    got = _heartbeat(tmp_path, [_claim(1, 'lane-a', 'attempt-abc')], backlog)
    assert got['state'] == 'PASS'
    assert got['lanes'] == [{'lane': 'lane-a', 'lease_id': 'attempt-abc', 'state': 'MEASURED',
                             'heartbeat_at': _utc(-30), 'age_s': 30, 'stale': False, 'reason': None}]
    assert 'lane-a' in got['reason'] and '30 s' in got['reason']


def test_a_lease_matches_by_attempt_fence_or_lease_id(tmp_path):
    backlog = _backlog(tmp_path, {'T1': _lease(5, attempt_id='att-1'), 'T2': _lease(70, fencing_token='fence-9-x'),
                                  'T3': _lease(200, lease_id='lease-3')})
    events = [_claim(1, 'lane-1', 'att-1'), _claim(2, 'lane-2', 'fence-9-x'), _claim(3, 'lane-3', 'lease-3')]
    ages = {row['lane']: row['age_s'] for row in _heartbeat(tmp_path, events, backlog)['lanes']}
    assert ages == {'lane-1': 5, 'lane-2': 70, 'lane-3': 200}


def test_an_old_heartbeat_is_flagged_stale_with_the_coordination_rule(tmp_path):
    backlog = _backlog(tmp_path, {'T1': _lease(500, ttl=900, attempt_id='a1'), 'T2': _lease(2000, ttl=900, attempt_id='a2')})
    got = _heartbeat(tmp_path, [_claim(1, 'lane-a', 'a1'), _claim(2, 'lane-b', 'a2')], backlog)
    assert [(row['lane'], row['age_s'], row['stale']) for row in got['lanes']] == [
        ('lane-a', 500, True), ('lane-b', 2000, True)]
    assert 'obsoleto' in got['reason']


def test_the_age_is_measured_against_the_clock_passed_in(tmp_path):
    backlog = _backlog(tmp_path, {'T1': _lease(0, attempt_id='a1')})
    events = [_claim(1, 'lane-a', 'a1')]
    first = lane_extras.extras(tmp_path, events, backlog_path=backlog, now=NOW + 10)['heartbeat']['lanes'][0]
    later = lane_extras.extras(tmp_path, events, backlog_path=backlog, now=NOW + 60)['heartbeat']['lanes'][0]
    assert (first['age_s'], later['age_s']) == (10, 60)


def test_a_lane_without_a_lease_id_is_unverified_with_the_reason(tmp_path):
    backlog = _backlog(tmp_path, {'T1': _lease(5, attempt_id='a1')})
    got = _heartbeat(tmp_path, [_claim(1, 'lane-a', '')], backlog)
    assert got['state'] == 'UNVERIFIED'
    assert got['lanes'] == [{'lane': 'lane-a', 'lease_id': None, 'state': 'UNVERIFIED', 'heartbeat_at': None,
                             'age_s': None, 'stale': None, 'reason': 'lane sem lease_id registrado'}]


def test_a_lease_missing_from_the_backlog_is_unverified_not_invented(tmp_path):
    backlog = _backlog(tmp_path, {'T1': _lease(5, attempt_id='a1'), 'T2': {}})
    got = _heartbeat(tmp_path, [_claim(1, 'lane-a', 'ghost')], backlog)
    assert got['state'] == 'UNVERIFIED'
    row = got['lanes'][0]
    assert (row['state'], row['age_s'], row['heartbeat_at'], row['stale']) == ('UNVERIFIED', None, None, None)
    assert row['reason'] == 'lease ghost não está no backlog'


def test_a_missing_or_broken_backlog_leaves_every_lane_unverified(tmp_path):
    events = [_claim(1, 'lane-a', 'a1')]
    missing = _heartbeat(tmp_path, events, tmp_path / 'nope.jsonl')
    assert missing['state'] == 'UNVERIFIED' and missing['lanes'][0]['reason'] == 'backlog não lido: backlog file not found'
    broken = tmp_path / 'broken.jsonl'
    broken.write_text('{oops\n', encoding='utf-8')
    assert _heartbeat(tmp_path, events, broken)['lanes'][0]['state'] == 'UNVERIFIED'


def test_a_lease_without_a_parsable_heartbeat_is_unverified(tmp_path):
    lease = dict(_lease(5, attempt_id='a1'), heartbeat_at='not a time')
    got = _heartbeat(tmp_path, [_claim(1, 'lane-a', 'a1')], _backlog(tmp_path, {'T1': lease}))
    assert got['lanes'][0]['state'] == 'UNVERIFIED' and got['lanes'][0]['reason'] == 'lease sem heartbeat_at medido'


def test_the_latest_claim_of_a_lane_wins_by_seq_and_a_lane_is_found_through_its_task(tmp_path):
    backlog = _backlog(tmp_path, {'T1': _lease(5, attempt_id='new'), 'T2': _lease(9, attempt_id='old')})
    unlaned = dict(_claim(9, None, 'new', task_id='T1'), lane=None)
    events = [_claim(2, 'lane-a', 'old'), dict(_event(3, 'lane_progress', {}, lane='lane-a'), task_id='T1'), unlaned]
    rows = _heartbeat(tmp_path, events, backlog)['lanes']
    assert [(row['lane'], row['lease_id'], row['age_s']) for row in rows] == [('lane-a', 'new', 5)]


def test_the_backlog_defaults_to_the_orchestrator_file_next_to_loop_runs(tmp_path, monkeypatch):
    monkeypatch.delenv('SIMPLICIO_BACKLOG_FILE', raising=False)
    root = tmp_path / '.simplicio-loop'
    run_dir = root / 'loop-runs' / 'r1'
    (root / 'orchestrator' / 'backlog').mkdir(parents=True)
    run_dir.mkdir(parents=True)
    _backlog(root / 'orchestrator' / 'backlog', {})
    (root / 'orchestrator' / 'backlog' / 'backlog.jsonl').write_text(
        json.dumps({'kind': 'item', 'id': 'T1', 'lease': _lease(12, attempt_id='a1')}) + '\n', encoding='utf-8')
    got = lane_extras.extras(run_dir, [_claim(1, 'lane-a', 'a1')], now=NOW)['heartbeat']
    assert got['lanes'][0]['age_s'] == 12
