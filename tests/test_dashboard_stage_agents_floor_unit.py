'''/stage-agents and /budget price the run with one path, so the "a partir de" floor and the USD agree (issue #1550).'''
import json
from pathlib import Path

from simplicio_loop.dashboard import budget, stage_agents

PRICES = json.loads((Path(__file__).resolve().parents[1] / 'simplicio_loop' / 'dashboard' / 'prices.json').read_text(encoding='utf-8'))
HAIKU = 'claude-haiku-5-5'


def _tok(seq, task, tokens_in, tokens_out, phase='executing', iteration=None, **extra):
    event = {'schema': 'simplicio.dashboard-event/v1', 'seq': seq, 'kind': 'token_usage', 'phase': phase, 'task_id': task,
             'payload': dict({'model': HAIKU, 'input_tokens': tokens_in, 'output_tokens': tokens_out}, **extra)}
    if iteration is not None:
        event['iteration'] = iteration
    return event


MIXED = [_tok(1, 'T1', 150_000, 2_000, requests=1, iteration=1), _tok(2, 'T2', 150_000, 2_000, iteration=2)]
FLOOR_KEYS = ('usd', 'floor', 'floor_reason', 'floor_tasks', 'floor_iterations', 'floor_unattributed', 'by_task')


def test_stage_agents_total_and_floor_equal_the_budget_on_a_mixed_run():
    cost = stage_agents.view(MIXED, PRICES)['cost']
    expected = budget.cost_estimate(MIXED, PRICES)
    assert {key: cost[key] for key in FLOOR_KEYS} == {key: expected[key] for key in FLOOR_KEYS}
    assert cost['usd'] == 0.096 and cost['floor'] is True and cost['floor_tasks'] == ['T2'] and cost['floor_iterations'] == ['2']


def test_a_stage_row_carries_the_floor_of_its_own_events():
    events = [_tok(1, 'T1', 150_000, 0, phase='planning'), _tok(2, 'T1', 150_000, 0, phase='executing', requests=1)]
    rows = {row['phase']: row for row in stage_agents.rows(events, PRICES)}
    assert rows['planning']['cost_floor'] is True and rows['planning']['floor_reason']
    assert rows['planning']['cost_usd'] == 0.015
    assert rows['executing']['cost_floor'] is False and rows['executing']['cost_usd'] == 0.075


def test_the_others_stage_row_prices_every_folded_stage_and_is_a_floor():
    events = [_tok(i + 1, 'T', 150_000 + i, 0, phase='p%d' % i) for i in range(25)]
    others = stage_agents.rows(events, PRICES)[-1]
    folded = budget.cost_estimate(events[:5], PRICES)
    assert others['others'] == 5 and others['cost_floor'] is True and others['cost_usd'] == folded['usd']
    assert others['floor_reason'] == folded['floor_reason']


def test_requests_1_alone_is_exact_and_never_a_floor():
    cost = stage_agents.view([_tok(1, 'T1', 150_000, 2_000, requests=1)], PRICES)['cost']
    assert cost['usd'] == 0.08 and cost['floor'] is False and cost['floor_tasks'] == []
