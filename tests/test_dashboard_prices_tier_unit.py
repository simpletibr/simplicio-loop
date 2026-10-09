'''Contract of the price tier in prices.json (simplicio.price-table/v1, issue #1620).'''
import json
from pathlib import Path

PRICES = json.loads((Path(__file__).resolve().parents[1] / 'simplicio_loop' / 'dashboard' / 'prices.json').read_text(encoding='utf-8'))


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def test_every_tier_is_structured_and_above_the_base_rate():
    tiers = {model: price['tier'] for model, price in PRICES['models'].items() if 'tier' in price}
    assert 'claude-haiku-5-5' in tiers
    for model, tier in tiers.items():
        assert isinstance(tier['prompt_tokens_above'], int) and tier['prompt_tokens_above'] > 0, model
        for field in ('input_per_mtok', 'output_per_mtok'):
            assert _number(tier[field]) and tier[field] > PRICES['models'][model][field], (model, field)


def test_haiku_55_tier_is_five_times_the_base_above_100000_tokens():
    price = PRICES['models']['claude-haiku-5-5']
    tier = price['tier']
    assert tier['prompt_tokens_above'] == 100000
    assert (tier['input_per_mtok'], tier['output_per_mtok']) == (0.50, 2.50)
    assert tier['input_per_mtok'] == 5 * price['input_per_mtok'] and tier['output_per_mtok'] == 5 * price['output_per_mtok']


def test_cache_read_is_a_tenth_of_the_input_and_flagged_as_derived():
    price = PRICES['models']['claude-haiku-5-5']
    assert price['cache_read_per_mtok'] == 0.01 and price['tier']['cache_read_per_mtok'] == 0.05
    assert 'DERIVADA' in price['note'] and 'UNVERIFIED' in price['note']
    assert 'até 100 mil' not in price['note']


def _event(payload):
    return {'schema': 'simplicio.dashboard-event/v1', 'kind': 'token_usage', 'payload': payload}


def test_haiku_55_above_the_tier_costs_the_tier_rate_with_requests_1_and_a_floor_without_it():
    from simplicio_loop.dashboard import budget
    usage = {'model': 'claude-haiku-5-5', 'input_tokens': 150_000, 'output_tokens': 2_000}
    exact = budget.cost_estimate([_event(dict(usage, requests=1))], PRICES)
    assert exact['usd'] == 0.08 and exact['floor'] is False and exact['floor_reason'] is None
    floor = budget.cost_estimate([_event(usage)], PRICES)
    assert floor['usd'] == 0.016 and floor['floor'] is True and floor['floor_reason']
    at_limit = budget.cost_estimate([_event(dict(usage, input_tokens=100_000))], PRICES)
    assert at_limit['floor'] is False
