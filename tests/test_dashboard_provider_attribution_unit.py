'''A provider receipt is attributed to its task, lane, attempt and call count in the token_usage stream (issue #1550).

The provider-worker receipt carries the measured usage but no task_id and no route, and the route record is written before the
call, so a real run showed every token as "sem tarefa" and "sem iteração". The producer now reads what the run wrote: the task
and route of the sibling execution-route-<task_index>.json, the receipt's attempt (the runner's repair loop of the task) as the
iteration, and its provider call count as ``requests`` (one HTTP call per dispatch), so a prompt above the price tier is priced
exactly instead of as a floor. ``payload.source`` marks the counts as the provider's own report. Every event carries the phase
named by state.json. Nothing is written when the run did not record it.
'''
import json
from pathlib import Path

import pytest

from simplicio_loop import dashboard_events
from simplicio_loop.dashboard import budget

PRICES = json.loads(Path(budget.__file__).with_name('prices.json').read_text(encoding='utf-8'))
MODEL = 'claude-haiku-5-5'
RECEIPT = 'provider-worker-1-attempt-2.json'
EVENTS = dashboard_events.load()


def _write(folder, name, record):
    (folder / name).write_text(json.dumps(record), encoding='utf-8')
    return name


def _receipt(folder, name=RECEIPT, **fields):
    record = {'schema': 'simplicio.provider-worker-receipt/v1', 'status': 'READY', 'provider': 'openrouter', 'model': MODEL,
              'task_index': 1, 'attempt': 2, 'provider_call_count': 1, 'usage_status': 'measured', 'input_tokens': 1000,
              'output_tokens': 200, 'cached_tokens': None, 'cache_write_tokens': None, 'reasoning_tokens': None, 'cost': None}
    record.update(fields)
    return _write(folder, name, record)


def _route(folder, index=1, **fields):
    record = {'task_index': index, 'task_id': 'T-7', 'route': 'provider-lane', 'token_usage': {'input_tokens': None, 'output_tokens': None}}
    record.update(fields)
    return _write(folder, 'execution-route-%d.json' % index, record)


def _spec(folder, name=RECEIPT):
    [spec] = EVENTS.token_usage_specs(folder, only=name)
    return spec


def test_a_receipt_takes_its_task_and_lane_from_the_sibling_route_and_its_attempt_as_the_iteration(tmp_path):
    _route(tmp_path)
    _receipt(tmp_path)
    spec = _spec(tmp_path)
    assert spec['task_id'] == 'T-7' and spec['lane'] == 'provider-lane' and spec['iteration'] == 2
    assert spec['payload']['source'] == 'provider' and spec['payload']['requests'] == 1
    assert spec['payload']['input_tokens'] == 1000 and spec['payload']['model'] == MODEL


def test_a_route_of_another_task_is_not_used(tmp_path):
    _route(tmp_path, index=2)
    _receipt(tmp_path)
    spec = _spec(tmp_path)
    assert 'task_id' not in spec and 'lane' not in spec and spec['iteration'] == 2


def test_a_receipt_without_a_route_keeps_the_attempt_and_the_call_count_and_no_task(tmp_path):
    _receipt(tmp_path)
    spec = _spec(tmp_path)
    assert 'task_id' not in spec and 'lane' not in spec
    assert spec['iteration'] == 2 and spec['payload']['requests'] == 1 and spec['payload']['source'] == 'provider'


@pytest.mark.parametrize('route', ['not json', '[]', '{"task_id": 7, "route": ""}', '{"task_id": "", "route": null}'])
def test_an_unreadable_or_empty_route_adds_nothing_and_does_not_raise(tmp_path, route):
    (tmp_path / 'execution-route-1.json').write_text(route, encoding='utf-8')
    _receipt(tmp_path)
    spec = _spec(tmp_path)
    assert 'task_id' not in spec and 'lane' not in spec


@pytest.mark.parametrize('calls', [None, True, 0, -1, '1', 1.5])
def test_a_call_count_that_is_not_a_positive_integer_is_not_written(tmp_path, calls):
    _receipt(tmp_path, provider_call_count=calls)
    assert 'requests' not in _spec(tmp_path)['payload']


@pytest.mark.parametrize('attempt', [None, True, -1, '2', 2.5])
def test_an_attempt_that_is_not_an_integer_is_no_iteration(tmp_path, attempt):
    _receipt(tmp_path, attempt=attempt)
    assert 'iteration' not in _spec(tmp_path)


def test_a_receipt_task_index_that_is_not_an_integer_reads_no_route(tmp_path):
    _route(tmp_path)
    _receipt(tmp_path, task_index='1')
    assert 'task_id' not in _spec(tmp_path)


def test_the_phase_of_state_json_marks_every_token_usage_spec(tmp_path):
    _write(tmp_path, 'state.json', {'run_id': 'r', 'phase': 'executing'})
    _write(tmp_path, 'execution-route-3.json', {'task_index': 3, 'task_id': 'T-3', 'route': 'lane-x',
                                                'token_usage': {'input_tokens': 5, 'output_tokens': 6}})
    _receipt(tmp_path)
    specs = EVENTS.token_usage_specs(tmp_path)
    assert sorted(spec['payload']['input_tokens'] for spec in specs) == [5, 1000]
    assert {spec['phase'] for spec in specs} == {'executing'}


@pytest.mark.parametrize('state', [None, 'not json', {'run_id': 'r'}, {'phase': ''}, {'phase': 7}, []])
def test_no_readable_phase_means_no_phase(tmp_path, state):
    if isinstance(state, str):
        (tmp_path / 'state.json').write_text(state, encoding='utf-8')
    elif state is not None:
        _write(tmp_path, 'state.json', state)
    _receipt(tmp_path)
    assert 'phase' not in _spec(tmp_path)


def test_a_route_record_gets_no_provider_marks(tmp_path):
    _write(tmp_path, 'execution-route-4.json', {'task_index': 4, 'task_id': 'T-4', 'route': 'lane-y', 'attempt': 3,
                                                'provider_call_count': 1, 'token_usage': {'input_tokens': 5, 'output_tokens': 6}})
    [spec] = EVENTS.token_usage_specs(tmp_path)
    assert spec['task_id'] == 'T-4' and spec['lane'] == 'lane-y'
    assert 'iteration' not in spec and set(spec['payload']) == {'input_tokens', 'output_tokens'}


def test_the_stream_event_carries_the_attribution_and_the_budget_reads_it(tmp_path):
    run_dir = tmp_path / 'run-x'
    run_dir.mkdir()
    _write(run_dir, 'state.json', {'run_id': 'run-x', 'phase': 'executing'})
    _route(run_dir)
    name = _receipt(run_dir)
    assert len(EVENTS.emit_token_usage(run_dir, only=name)) == 1
    [event] = [e for e in EVENTS.read_events(run_dir) if e['kind'] == 'token_usage']
    assert (event['task_id'], event['lane'], event['iteration'], event['phase']) == ('T-7', 'provider-lane', 2, 'executing')
    assert event['payload']['requests'] == 1 and event['payload']['source'] == 'provider'
    usage = budget.usage([event])
    assert usage['by_task'] == {'T-7': 1200} and usage['by_iteration'] == {'2': 1200}
    assert usage['by_phase'] == {'executing': 1200} and usage['by_source'] == {'provider': 1200, 'other': 0}
    assert usage['unattributed_tokens'] == {'task': 0, 'iteration': 0}


def test_one_provider_call_above_the_price_tier_is_priced_exactly_and_without_the_call_count_it_is_a_floor(tmp_path):
    first = tmp_path / 'with-count'
    second = tmp_path / 'without-count'
    for folder, calls in ((first, 1), (second, None)):
        folder.mkdir()
        _receipt(folder, input_tokens=150000, output_tokens=2000, provider_call_count=calls)
    exact = budget.cost_estimate([_as_event(_spec(first))], PRICES)
    floor = budget.cost_estimate([_as_event(_spec(second))], PRICES)
    assert exact['floor'] is False and exact['usd'] == pytest.approx(0.08)
    assert floor['floor'] is True and floor['usd'] == pytest.approx(0.016)


def _as_event(spec):
    return {'schema': 'simplicio.dashboard-event/v1', 'kind': 'token_usage', 'task_id': spec.get('task_id'), 'phase': spec.get('phase'),
            'lane': spec.get('lane'), 'iteration': spec.get('iteration'), 'payload': spec['payload']}
