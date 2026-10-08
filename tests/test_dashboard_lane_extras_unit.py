'''Unit tests for the per-run extras of the Simplicio Live dashboard (TDD red).

The extras are the last measured test or lint command, the declared task list, the model used per lane with its token
totals, and the heartbeat state. The heartbeat stays UNVERIFIED because no lease heartbeat producer exists yet. The
reader is a pure function of the run directory and its events, so no server is needed.
'''
import json

from simplicio_loop.dashboard import budget, lane_extras

SCHEMA = 'simplicio.dashboard-extras/v1'
EVENT_SCHEMA = 'simplicio.dashboard-event/v1'
HEARTBEAT = {'state': 'UNVERIFIED', 'reason': 'no lease heartbeat producer'}


def _event(seq, kind, payload=None, lane=None, ts=None):
    return {'schema': EVENT_SCHEMA, 'seq': seq, 'kind': kind, 'lane': lane,
            'ts': ts or f'2026-10-08T10:00:{seq:02d}Z', 'payload': payload or {}}


def _contract(tmp_path, tasks):
    (tmp_path / 'task-contract.json').write_text(json.dumps({'tasks': tasks}), encoding='utf-8')


def test_an_empty_run_reports_no_extras_and_an_unverified_heartbeat(tmp_path):
    assert lane_extras.extras(tmp_path, []) == {'schema': SCHEMA, 'last_command': None, 'tasks': [],
                                                'models': [], 'heartbeat': HEARTBEAT}


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


def test_heartbeat_is_unverified_until_a_producer_exists(tmp_path):
    assert lane_extras.extras(tmp_path, [])['heartbeat'] == HEARTBEAT
