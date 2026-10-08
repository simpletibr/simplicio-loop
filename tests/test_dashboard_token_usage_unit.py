'''Token usage producer and per-run cost estimate (issue #1404, TDD red).

The producer reads only what the run recorded: the ``token_usage`` block of ``execution-route*.json``. A record with
integer counts becomes a ``token_usage`` event; a record with null counts (route decided before any provider call) is
skipped, never filled in. The cost is an estimate from prices.json and always carries the table's as_of and source_url.
'''
import json

from simplicio_loop import dashboard_events
from simplicio_loop.dashboard import budget


def _route(tmp_path, name, usage, route='worker', model=None):
    record = {'route': route, 'task_id': 't1', 'token_usage': usage}
    if model:
        record['model'] = model
    (tmp_path / name).write_text(json.dumps(record), encoding='utf-8')


def test_route_with_measured_counts_becomes_an_event(tmp_path):
    _route(tmp_path, 'execution-route-1.json',
           {'input_tokens': 120, 'output_tokens': 30, 'reason': 'measured'}, route='provider', model='claude-sonnet-5-5')
    specs = dashboard_events.load().token_usage_specs(tmp_path)
    assert len(specs) == 1
    spec = specs[0]
    assert spec['kind'] == 'token_usage' and spec['lane'] == 'provider'
    assert spec['payload']['input_tokens'] == 120 and spec['payload']['output_tokens'] == 30
    assert spec['payload']['model'] == 'claude-sonnet-5-5'


def test_route_with_null_counts_is_not_invented(tmp_path):
    _route(tmp_path, 'execution-route-1.json',
           {'input_tokens': None, 'output_tokens': None, 'reason': 'route_decision_precedes_provider_invocation'})
    assert dashboard_events.load().token_usage_specs(tmp_path) == []


def test_run_without_route_records_yields_nothing(tmp_path):
    assert dashboard_events.load().token_usage_specs(tmp_path) == []


def test_derived_stream_carries_the_producer_events(tmp_path):
    (tmp_path / 'state.json').write_text(json.dumps({'run_id': 'r1', 'events': []}), encoding='utf-8')
    _route(tmp_path, 'execution-route-1.json', {'input_tokens': 7, 'output_tokens': 3}, route='provider')
    kinds = [e['kind'] for e in dashboard_events.read_events(tmp_path)]
    assert 'token_usage' in kinds


PRICES = {'as_of': '2026-10-08', 'source_url': 'https://example.test/pricing',
          'models': {'m-a': {'input_per_mtok': 2, 'output_per_mtok': 10}}}


def _evt(model, i, o):
    return {'schema': 'simplicio.dashboard-event/v1', 'kind': 'token_usage', 'phase': 'executing',
            'payload': {'model': model, 'input_tokens': i, 'output_tokens': o}}


def test_cost_is_estimado_with_the_price_source():
    cost = budget.cost_estimate([_evt('m-a', 1_000_000, 100_000)], PRICES)
    assert cost['state'] == 'ESTIMADO' and cost['proof_kind'] == 'estimado'
    assert cost['usd'] == 3.0
    assert cost['as_of'] == '2026-10-08' and cost['source_url'] == 'https://example.test/pricing'


def test_cost_is_unverified_without_measured_tokens():
    assert budget.cost_estimate([], PRICES)['state'] == 'UNVERIFIED'


def test_cost_is_unverified_for_a_model_missing_from_the_table():
    cost = budget.cost_estimate([_evt('m-zzz', 10, 10)], PRICES)
    assert cost['state'] == 'UNVERIFIED' and 'm-zzz' in cost['reason']


def test_cost_is_unverified_without_a_price_table():
    assert budget.cost_estimate([_evt('m-a', 10, 10)], None)['state'] == 'UNVERIFIED'


def test_report_includes_the_run_cost(tmp_path):
    got = budget.report(tmp_path, [_evt('m-a', 1_000_000, 0)], PRICES)
    assert got['cost']['usd'] == 2.0


def test_fanout_route_emits_a_live_token_usage_event(tmp_path):
    from simplicio_loop import runner
    runner._fanout_execution_route({'run_id': 'r1', 'task_index': 1, 'task_id': 't1',
                                    'context_pack': {'goal': 'mapear o repositorio e coletar CI'}}, tmp_path)
    events = [e for e in dashboard_events.read_events(tmp_path) if e['kind'] == 'token_usage']
    assert events and events[0]['payload']['input_tokens'] == 0 and events[0]['lane'] == 'worker'
