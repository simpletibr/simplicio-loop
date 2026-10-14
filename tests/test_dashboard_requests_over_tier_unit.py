'''Measured requests_over_tier of the Live cost estimate (issue #1608). It counts the provider requests, measured one by one
(payload.requests == 1), whose total prompt passed the price tier of their model; the goal is zero. An aggregate event
cannot say which request crossed the limit, so it is not counted. The tests use the real prices.json.
'''
import json
from pathlib import Path

from simplicio_loop.dashboard import budget

PRICES = json.loads((Path(budget.__file__).with_name('prices.json')).read_text(encoding='utf-8'))
MODEL = 'claude-haiku-5-5'


def _usage(seq, tokens_in, tokens_out, model=MODEL, **extra):
    payload = {'model': model, 'input_tokens': tokens_in, 'output_tokens': tokens_out, **extra}
    return {'schema': 'simplicio.dashboard-event/v1', 'seq': seq, 'kind': 'token_usage', 'phase': 'executing', 'lane': None,
            'task_id': 'T1', 'iteration': seq, 'ts': '2026-10-10T10:00:%02dZ' % seq, 'payload': payload}


def test_a_per_request_prompt_above_the_tier_is_counted():
    assert budget.cost_estimate([_usage(1, 150000, 2000, requests=1)], PRICES)['requests_over_tier'] == 1


def test_an_aggregate_event_above_the_tier_is_not_counted_though_it_is_a_floor():
    cost = budget.cost_estimate([_usage(1, 150000, 0)], PRICES)
    assert cost['requests_over_tier'] == 0 and cost['floor'] is True


def test_exactly_the_limit_is_not_over_the_tier():
    assert budget.cost_estimate([_usage(1, 100000, 0, requests=1)], PRICES)['requests_over_tier'] == 0


def test_cached_and_cache_write_tokens_count_toward_the_prompt():
    event = _usage(1, 40000, 0, cached_tokens=40000, cache_write_tokens=30000, requests=1)
    assert budget.cost_estimate([event], PRICES)['requests_over_tier'] == 1


def test_a_model_without_a_tier_never_counts():
    event = _usage(1, 500000, 0, model='claude-haiku-4-5', requests=1)
    assert budget.cost_estimate([event], PRICES)['requests_over_tier'] == 0


def test_the_count_adds_up_over_the_per_request_events_only():
    events = [_usage(1, 150000, 0, requests=1), _usage(2, 150000, 0, requests=1), _usage(3, 1000, 0, requests=1),
              _usage(4, 150000, 0)]
    assert budget.cost_estimate(events, PRICES)['requests_over_tier'] == 2


def test_the_count_does_not_depend_on_the_provider_reported_cost():
    event = _usage(1, 150000, 0, requests=1, cost=0.05)
    cost = budget.cost_estimate([event], PRICES)
    assert cost['proof_kind'] == 'medido' and cost['requests_over_tier'] == 1


def test_a_boolean_is_not_a_request_count():
    assert budget.cost_estimate([_usage(1, 150000, 0, requests=True)], PRICES)['requests_over_tier'] == 0


def test_without_a_price_table_the_count_is_unknown():
    event = _usage(1, 150000, 0, requests=1, cost=0.05)
    assert budget.cost_estimate([event], None)['requests_over_tier'] is None


def test_no_measured_tokens_means_no_count():
    assert budget.cost_estimate([], PRICES)['requests_over_tier'] is None
