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
NO_COMMAND_EVENT = {'state': 'UNVERIFIED', 'reason': 'nenhum command_started no run', 'lanes': []}


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
    assert lane_extras.extras(tmp_path, []) == {'schema': SCHEMA, 'last_command': None, 'running_command': NO_COMMAND_EVENT,
                                                'tasks': [], 'models': [], 'tokens_series': [], 'heartbeat': NO_LANE}


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
    backlog = _backlog(tmp_path, {'T1': _lease(30, lease_id='lease-abc')})
    got = _heartbeat(tmp_path, [_claim(1, 'lane-a', 'lease-abc')], backlog)
    assert got['state'] == 'PASS'
    assert got['lanes'] == [{'lane': 'lane-a', 'lease_id': 'lease-abc', 'state': 'MEASURED',
                             'heartbeat_at': _utc(-30), 'age_s': 30, 'stale': False, 'reason': None}]
    assert 'lane-a' in got['reason'] and '30 s' in got['reason']


def test_a_lease_matches_only_by_its_lease_id_never_by_attempt_or_fence(tmp_path):
    """attempt_id and fence live in other namespaces (task_backlog: fence-N-uuid, attempt-uuid): never a match."""
    backlog = _backlog(tmp_path, {'T1': _lease(10, fence='7'), 'T2': _lease(500, attempt_id='7'),
                                  'T3': _lease(20, fencing_token='7'), 'T4': _lease(30, lease_id='lease-4')})
    got = _heartbeat(tmp_path, [_claim(1, 'lane-a', '7'), _claim(2, 'lane-b', 'lease-4')], backlog)
    by_lane = {row['lane']: row for row in got['lanes']}
    assert by_lane['lane-a']['state'] == 'UNVERIFIED' and by_lane['lane-a']['age_s'] is None
    assert by_lane['lane-a']['reason'] == 'lease 7 não está no backlog'
    assert (by_lane['lane-b']['state'], by_lane['lane-b']['age_s']) == ('MEASURED', 30)


def test_a_lease_id_held_by_two_items_is_ambiguous_and_unverified(tmp_path):
    backlog = _backlog(tmp_path, {'T1': _lease(5, lease_id='dup'), 'T2': _lease(90, lease_id='dup')})
    row = _heartbeat(tmp_path, [_claim(1, 'lane-a', 'dup')], backlog)['lanes'][0]
    assert (row['state'], row['age_s'], row['reason']) == ('UNVERIFIED', None, 'lease dup aparece em mais de um item do backlog')


def test_malformed_lease_values_never_crash_the_reader(tmp_path):
    backlog = _backlog(tmp_path, {'T1': dict(_lease(5, lease_id='a1'), attempt_id=['x'], fence={'k': 1})})
    assert _heartbeat(tmp_path, [_claim(1, 'lane-a', 'a1')], backlog)['lanes'][0]['state'] == 'MEASURED'
    assert _heartbeat(tmp_path, [_claim(1, 'lane-a', 'zz')], backlog)['state'] == 'UNVERIFIED'


def test_a_lease_without_a_worker_or_with_a_future_heartbeat_is_unverified_with_its_reason(tmp_path):
    no_worker = {k: v for k, v in _lease(5, lease_id='a1').items() if k != 'worker'}
    row = _heartbeat(tmp_path, [_claim(1, 'lane-a', 'a1')], _backlog(tmp_path, {'T1': no_worker}))['lanes'][0]
    assert (row['state'], row['reason']) == ('UNVERIFIED', 'lease a1 sem worker no backlog')
    future = _backlog(tmp_path, {'T1': _lease(-100, lease_id='a1')})
    row = _heartbeat(tmp_path, [_claim(1, 'lane-a', 'a1')], future)['lanes'][0]
    assert (row['state'], row['age_s'], row['reason']) == ('UNVERIFIED', None, 'heartbeat_at no futuro do relógio')


def test_an_old_heartbeat_is_flagged_stale_with_the_coordination_rule(tmp_path):
    backlog = _backlog(tmp_path, {'T1': _lease(500, ttl=900, lease_id='a1'), 'T2': _lease(2000, ttl=900, lease_id='a2')})
    got = _heartbeat(tmp_path, [_claim(1, 'lane-a', 'a1'), _claim(2, 'lane-b', 'a2')], backlog)
    assert [(row['lane'], row['age_s'], row['stale']) for row in got['lanes']] == [
        ('lane-a', 500, True), ('lane-b', 2000, True)]
    assert 'obsoleto' in got['reason']


def test_the_age_is_measured_against_the_clock_passed_in(tmp_path):
    backlog = _backlog(tmp_path, {'T1': _lease(0, lease_id='a1')})
    events = [_claim(1, 'lane-a', 'a1')]
    first = lane_extras.extras(tmp_path, events, backlog_path=backlog, now=NOW + 10)['heartbeat']['lanes'][0]
    later = lane_extras.extras(tmp_path, events, backlog_path=backlog, now=NOW + 60)['heartbeat']['lanes'][0]
    assert (first['age_s'], later['age_s']) == (10, 60)


def test_a_lane_without_a_lease_id_is_unverified_with_the_reason(tmp_path):
    backlog = _backlog(tmp_path, {'T1': _lease(5, lease_id='a1')})
    got = _heartbeat(tmp_path, [_claim(1, 'lane-a', '')], backlog)
    assert got['state'] == 'UNVERIFIED'
    assert got['lanes'] == [{'lane': 'lane-a', 'lease_id': None, 'state': 'UNVERIFIED', 'heartbeat_at': None,
                             'age_s': None, 'stale': None, 'reason': 'lane sem lease_id registrado'}]


def test_a_lease_missing_from_the_backlog_is_unverified_not_invented(tmp_path):
    backlog = _backlog(tmp_path, {'T1': _lease(5, lease_id='a1'), 'T2': {}})
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
    lease = dict(_lease(5, lease_id='a1'), heartbeat_at='not a time')
    got = _heartbeat(tmp_path, [_claim(1, 'lane-a', 'a1')], _backlog(tmp_path, {'T1': lease}))
    assert got['lanes'][0]['state'] == 'UNVERIFIED' and got['lanes'][0]['reason'] == 'lease sem heartbeat_at medido'


def test_the_latest_claim_of_a_lane_wins_by_seq_and_a_lane_is_found_through_its_task(tmp_path):
    backlog = _backlog(tmp_path, {'T1': _lease(5, lease_id='new'), 'T2': _lease(9, lease_id='old')})
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
        json.dumps({'kind': 'item', 'id': 'T1', 'lease': _lease(12, lease_id='a1')}) + '\n', encoding='utf-8')
    got = lane_extras.extras(run_dir, [_claim(1, 'lane-a', 'a1')], now=NOW)['heartbeat']
    assert got['lanes'][0]['age_s'] == 12


# --- issue #1551: the command running right now (command_started without a command_finished) -----------------------------
def _started(seq, command_id, ago, command='pytest -q', lane='lane-a', task_id='T1'):
    payload = {'command_id': command_id, 'command': command}
    return dict(_event(seq, 'command_started', payload, lane=lane, ts=_utc(-ago)), task_id=task_id)


def _finished(seq, command_id, ago=0, lane='lane-a', task_id='T1'):
    payload = {'command_id': command_id, 'exit_code': 0, 'duration_s': 1.5, 'status': 'pass'}
    return dict(_event(seq, 'command_finished', payload, lane=lane, ts=_utc(-ago)), task_id=task_id)


def _running(tmp_path, events, now=NOW):
    return lane_extras.extras(tmp_path, events, now=now)['running_command']


def test_a_started_command_without_a_finish_is_running_with_its_measured_age(tmp_path):
    got = _running(tmp_path, [_started(1, 'c1', 12, command='pytest -q tests/x.py')])
    assert got['state'] == 'PASS'
    assert got['lanes'] == [{'lane': 'lane-a', 'task_id': 'T1', 'command_id': 'c1', 'command': 'pytest -q tests/x.py',
                             'started_at': _utc(-12), 'age_s': 12, 'stuck': False, 'state': 'MEASURED', 'reason': None}]
    assert got['reason'] == 'lane-a: em execução há 12 s: pytest -q tests/x.py'


def test_a_finished_command_is_not_shown_as_running(tmp_path):
    got = _running(tmp_path, [_started(1, 'c1', 12), _finished(2, 'c1')])
    assert got == {'state': 'PASS', 'reason': 'nenhum comando em execução segundo os eventos', 'lanes': []}


def test_a_run_without_command_events_is_unverified_with_the_reason(tmp_path):
    assert _running(tmp_path, []) == NO_COMMAND_EVENT
    assert _running(tmp_path, [_event(1, 'test_result', {'command': 'pytest -q'})]) == NO_COMMAND_EVENT


def test_a_finish_alone_does_not_invent_a_running_command(tmp_path):
    assert _running(tmp_path, [_finished(2, 'c1')]) == NO_COMMAND_EVENT


def test_interleaved_events_of_two_lanes_are_paired_by_command_id_and_read_in_seq_order(tmp_path):
    events = [_started(1, 'a1', 50, command='pytest a1', lane='lane-a', task_id='TA'),
              _started(2, 'b1', 40, command='ruff b1', lane='lane-b', task_id='TB'),
              _finished(3, 'a1', 30, lane='lane-a', task_id='TA'),
              _started(4, 'a2', 20, command='pytest a2', lane='lane-a', task_id='TA'),
              _finished(5, 'b1', 10, lane='lane-b', task_id='TB')]
    for order in (events, events[::-1], [events[i] for i in (3, 0, 4, 2, 1)]):
        got = _running(tmp_path, order)
        assert [(row['lane'], row['command'], row['age_s']) for row in got['lanes']] == [('lane-a', 'pytest a2', 20)]
    still = _running(tmp_path, events[:2])
    assert [(row['lane'], row['command']) for row in still['lanes']] == [('lane-a', 'pytest a1'), ('lane-b', 'ruff b1')]
    assert still['reason'] == 'lane-a: em execução há 50 s: pytest a1; lane-b: em execução há 40 s: ruff b1'


def test_the_latest_unfinished_command_of_a_lane_wins_by_seq(tmp_path):
    got = _running(tmp_path, [_started(7, 'c2', 5, command='second'), _started(3, 'c1', 90, command='first')])
    assert [(row['command_id'], row['command']) for row in got['lanes']] == [('c2', 'second')]


def test_a_lane_is_found_through_its_task_when_the_event_carries_none(tmp_path):
    events = [_claim(1, 'lane-a', 'lease-1', task_id='T1'), _started(2, 'c1', 4, lane=None, task_id='T1')]
    assert [(row['lane'], row['task_id']) for row in _running(tmp_path, events)['lanes']] == [('lane-a', 'T1')]
    nameless = _running(tmp_path, [_started(2, 'c1', 4, lane=None, task_id='T9')])
    assert [(row['lane'], row['task_id']) for row in nameless['lanes']] == [(None, 'T9')]
    assert nameless['reason'] == 'T9: em execução há 4 s: pytest -q'


def test_the_age_is_measured_against_the_clock_passed_in_for_a_running_command(tmp_path):
    events = [_started(1, 'c1', 0)]
    ages = [_running(tmp_path, events, now=NOW + delta)['lanes'][0]['age_s'] for delta in (10, 60)]
    assert ages == [10, 60]


def test_a_command_running_longer_than_the_threshold_is_flagged_with_its_age_not_hidden(tmp_path):
    limit = lane_extras.STUCK_AFTER_S
    at_limit = _running(tmp_path, [_started(1, 'c1', limit)])['lanes'][0]
    stuck = _running(tmp_path, [_started(1, 'c1', limit + 100, command='pytest -q')])
    assert at_limit['stuck'] is False
    assert stuck['state'] == 'PASS' and stuck['lanes'][0]['stuck'] is True and stuck['lanes'][0]['age_s'] == limit + 100
    assert stuck['reason'] == (f'lane-a: em execução há {limit + 100} s, sem fim registrado '
                               f'(limite {limit} s): pytest -q')


def test_a_command_started_before_the_run_finished_is_not_shown_as_running(tmp_path):
    events = [_started(1, 'c1', 30), _event(2, 'run_finished', {'outcome': 'done'})]
    assert _running(tmp_path, events) == {'state': 'PASS', 'reason': 'nenhum comando em execução segundo os eventos',
                                          'lanes': []}
    assert _running(tmp_path, events + [_started(3, 'c2', 3)])['lanes'][0]['command_id'] == 'c2'


def test_a_start_without_a_readable_time_or_in_the_future_is_unverified_never_invented(tmp_path):
    no_ts = dict(_started(1, 'c1', 5), ts='not a time')
    future = _started(2, 'c2', -100, lane='lane-b')
    got = _running(tmp_path, [no_ts, future])
    assert got['state'] == 'UNVERIFIED'
    assert [(row['state'], row['age_s'], row['started_at']) for row in got['lanes']] == [
        ('UNVERIFIED', None, None), ('UNVERIFIED', None, None)]
    assert [row['reason'] for row in got['lanes']] == ['command_started sem ts medido',
                                                      'command_started no futuro do relógio']
    assert 'lane-a: command_started sem ts medido' in got['reason']


def test_a_start_without_a_command_id_or_a_command_is_ignored(tmp_path):
    no_id = _event(1, 'command_started', {'command': 'pytest -q'}, lane='lane-a', ts=_utc(-5))
    no_command = _event(2, 'command_started', {'command_id': 'c2', 'command': ''}, lane='lane-b', ts=_utc(-5))
    assert _running(tmp_path, [no_id, no_command]) == NO_COMMAND_EVENT


def test_events_of_another_schema_never_start_a_command(tmp_path):
    foreign = dict(_started(1, 'c1', 5), schema='other/v1')
    assert _running(tmp_path, [foreign, 'not an event']) == NO_COMMAND_EVENT


def test_the_running_command_is_redacted_again_on_read_and_cut_to_200_characters(tmp_path):
    command = 'pytest --token=hunter2hunter2 ' + 'x' * 400
    got = _running(tmp_path, [_started(1, 'c1', 3, command=command)])
    assert 'hunter2hunter2' not in got['lanes'][0]['command'] and len(got['lanes'][0]['command']) == 200
    assert 'hunter2hunter2' not in got['reason']


def test_running_commands_are_capped_at_fifty_lanes(tmp_path):
    events = [_started(i + 1, f'c{i}', 5, lane=f'lane-{i:02d}', task_id=f'T{i}') for i in range(60)]
    assert len(_running(tmp_path, events)['lanes']) == 50


def test_a_hostile_command_in_the_event_file_is_masked_and_cannot_stall_the_reader(tmp_path):
    secrets = {'--token abcdef123456SECRET': 'abcdef123456SECRET', 'mysql -p hunter2hunter2': 'hunter2hunter2',
               'git clone https://u:p4ssw0rdvalue@localhost/x': 'p4ssw0rdvalue'}
    began = time.monotonic()
    for command, secret in secrets.items():
        got = _running(tmp_path, [_started(1, 'c1', 5, command='run ' + command)])
        assert secret not in got['reason'] and secret not in got['lanes'][0]['command'], command
    for hostile in ('password-' * 100_000, 'a-' * 500_000, 'x' * 5_000_000):
        got = _running(tmp_path, [_started(1, 'c1', 5, command=hostile)])
        assert got['state'] in ('PASS', 'UNVERIFIED') and len(got['lanes'][0]['command']) <= lane_extras.RUNNING_MAX
    assert time.monotonic() - began < 5
