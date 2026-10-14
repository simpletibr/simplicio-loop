'''Unit tests for the prompt-size price tier of the Live cost estimate (issue #1620, tier slice).

claude-haiku-5-5 costs 0.10/0.50 USD per Mtok up to 100000 prompt tokens and 0.50/2.50 above. A prompt is input + cached +
cache-write tokens. Above the limit the high rate is exact only for one provider request (payload.requests == 1); an event
with no per-request data is priced at the base rate as a floor, and the reply says so. The tests use the real prices.json.
'''
import json
from pathlib import Path

import pytest

from simplicio_loop.dashboard import budget

PRICES = json.loads((Path(budget.__file__).with_name('prices.json')).read_text(encoding='utf-8'))
MODEL = 'claude-haiku-5-5'


def _usage(seq, tokens_in, tokens_out, model=MODEL, task_id='T1', iteration=1, **extra):
    payload = {'model': model, 'input_tokens': tokens_in, 'output_tokens': tokens_out, **extra}
    return {'schema': 'simplicio.dashboard-event/v1', 'seq': seq, 'kind': 'token_usage', 'phase': 'executing', 'lane': None,
            'task_id': task_id, 'iteration': iteration, 'ts': '2026-10-08T10:00:%02dZ' % seq, 'payload': payload}


def test_one_request_above_the_limit_costs_the_high_rate_exactly():
    cost = budget.cost_estimate([_usage(1, 150000, 2000, requests=1)], PRICES)
    assert cost['usd'] == pytest.approx(0.08) and cost['state'] == 'ESTIMADO'
    assert cost['floor'] is False and cost['floor_reason'] is None and cost['floor_tasks'] == []


def test_aggregate_above_the_limit_is_a_floor_at_the_base_rate_with_the_reason():
    cost = budget.cost_estimate([_usage(1, 150000, 2000)], PRICES)
    assert cost['usd'] == pytest.approx(0.016) and cost['state'] == 'ESTIMADO'
    assert cost['floor'] is True
    assert cost['floor_reason'] == ('USD a partir de: 1 evento(s) com prompt acima de 100000 tokens sem dado por requisição; '
                                    'o nível de preço acima do limiar não foi verificado (UNVERIFIED)')
    assert cost['floor_tasks'] == ['T1'] and cost['floor_iterations'] == ['1']


def test_exactly_the_limit_is_the_base_rate_and_not_a_floor():
    cost = budget.cost_estimate([_usage(1, 100000, 0)], PRICES)
    assert cost['usd'] == pytest.approx(0.01) and cost['floor'] is False


def test_cached_and_cache_write_tokens_count_toward_the_prompt_size():
    cost = budget.cost_estimate([_usage(1, 40000, 0, cached_tokens=40000, cache_write_tokens=30000, requests=1)], PRICES)
    assert cost['usd'] == pytest.approx(40000 * 0.5 / 1e6)
    floor = budget.cost_estimate([_usage(1, 40000, 0, cached_tokens=40000, cache_write_tokens=30000)], PRICES)
    assert floor['floor'] is True and floor['usd'] == pytest.approx(0.004)


def test_the_tier_decides_per_event_not_per_model_total():
    events = [_usage(1, 60000, 0, task_id='A', iteration=1), _usage(2, 60000, 0, task_id='B', iteration=2)]
    cost = budget.cost_estimate(events, PRICES)  # the sum passes the limit, neither call does
    assert cost['usd'] == pytest.approx(0.012) and cost['floor'] is False


def test_only_the_over_limit_task_is_marked_as_a_floor():
    events = [_usage(1, 150000, 0, task_id='A', iteration=1), _usage(2, 1000, 0, task_id='B', iteration=2)]
    cost = budget.cost_estimate(events, PRICES)
    assert cost['floor_tasks'] == ['A'] and cost['floor_iterations'] == ['1']


def test_a_model_without_a_tier_is_priced_as_before():
    cost = budget.cost_estimate([_usage(1, 1_000_000, 0, model='claude-sonnet-5-5', requests=1)], PRICES)
    assert cost['usd'] == 2.0 and cost['floor'] is False


def test_requests_must_be_the_integer_one():
    for value in (True, 2, '1', 1.0 if False else None):
        cost = budget.cost_estimate([_usage(1, 150000, 0, requests=value)], PRICES)
        assert cost['floor'] is True, value


def test_a_malformed_tier_leaves_the_cost_unverified():
    table = {'models': {MODEL: {'input_per_mtok': 0.1, 'output_per_mtok': 0.5, 'tier': {'prompt_tokens_above': 'x'}}}}
    cost = budget.cost_estimate([_usage(1, 10, 0)], table)
    assert cost['usd'] is None and cost['state'] == 'UNVERIFIED'


def test_a_provider_reported_cost_is_never_a_floor():
    event = _usage(1, 150000, 0, cost=0.5)
    cost = budget.cost_estimate([event], PRICES)
    assert cost['proof_kind'] == 'medido' and cost['floor'] is False
