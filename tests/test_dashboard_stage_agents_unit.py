'''Unit and contract tests for the per-stage agents and cost reading of the Simplicio Live dashboard (issue #1404).

Each row is one stage (phase) of the run: the role and effort come from the model-roles table, the model and the tokens
come from the token_usage events, and the cost comes from the same price path as the budget panel. Every cost is an
estimate and carries proof_kind "estimado". A model the table does not list is UNVERIFIED for role and effort, never a guess.
'''
import json
from pathlib import Path

from simplicio_loop.dashboard import budget, stage_agents

PRICES = json.loads((Path(__file__).resolve().parents[1] / 'simplicio_loop' / 'dashboard' / 'prices.json').read_text(encoding='utf-8'))


def _usage(seq, phase, payload):
    return {'schema': 'simplicio.dashboard-event/v1', 'seq': seq, 'kind': 'token_usage', 'phase': phase,
            'ts': '2026-10-08T10:00:%02dZ' % seq, 'payload': payload}


def test_each_stage_row_reads_role_effort_model_and_tokens_from_the_events():
    events = [
        _usage(1, 'planning', {'model': 'claude-opus-5-5', 'input_tokens': 1000, 'output_tokens': 200}),
        _usage(2, 'executing', {'model': 'claude-haiku-5-5', 'input_tokens': 5000, 'output_tokens': 800}),
        _usage(3, 'executing', {'model': 'claude-haiku-5-5', 'input_tokens': 1000, 'output_tokens': 200}),
    ]
    rows = {row['phase']: row for row in stage_agents.rows(events, PRICES)}
    assert rows['planning']['role'] == 'planning'
    assert rows['planning']['effort'] == 'high'
    assert rows['planning']['model'] == 'claude-opus-5-5'
    assert (rows['planning']['tokens_in'], rows['planning']['tokens_out']) == (1000, 200)
    assert rows['executing']['role'] == 'execution'
    assert rows['executing']['model'] == 'claude-haiku-5-5'
    assert (rows['executing']['tokens_in'], rows['executing']['tokens_out']) == (6000, 1000)


def test_stage_costs_match_the_budget_cost_estimate_total_on_the_fixture():
    events = [
        _usage(1, 'planning', {'model': 'claude-opus-5-5', 'input_tokens': 1_000_000, 'output_tokens': 100_000}),
        _usage(2, 'executing', {'model': 'claude-haiku-5-5', 'input_tokens': 2_000_000, 'output_tokens': 1_000_000}),
    ]
    rows = stage_agents.rows(events, PRICES)
    # opus-5-5: 1M in x $4 + 0.1M out x $20 = $6.00; haiku-5-5: 2M in x $0.10 + 1M out x $0.50 = $0.70
    by_phase = {row['phase']: row for row in rows}
    assert by_phase['planning']['cost_usd'] == 6.0
    assert by_phase['executing']['cost_usd'] == 0.7
    total = budget.cost_estimate(events, PRICES)['usd']
    assert round(sum(row['cost_usd'] for row in rows), 6) == total == 6.7


def test_every_stage_cost_is_labelled_estimado():
    events = [_usage(1, 'executing', {'model': 'claude-haiku-5-5', 'input_tokens': 10, 'output_tokens': 10})]
    row = stage_agents.rows(events, PRICES)[0]
    assert row['proof_kind'] == 'estimado'
    assert row['cost_state'] == 'ESTIMADO'


def test_unknown_model_has_no_role_and_an_unverified_cost_with_a_reason():
    events = [_usage(1, 'executing', {'model': 'modelo-x', 'input_tokens': 10, 'output_tokens': 10})]
    row = stage_agents.rows(events, PRICES)[0]
    assert row['role'] is None and row['effort'] is None
    assert row['cost_usd'] is None and row['cost_state'] == 'UNVERIFIED'
    assert row['reason']


def test_no_token_usage_means_no_stage_rows():
    assert stage_agents.rows([{'schema': 'simplicio.dashboard-event/v1', 'kind': 'phase_entered', 'phase': 'planning'}], PRICES) == []


def test_view_carries_the_rows_and_the_run_cost_under_the_stage_agents_schema():
    events = [_usage(1, 'executing', {'model': 'claude-haiku-5-5', 'input_tokens': 1000, 'output_tokens': 200})]
    view = stage_agents.view(events, PRICES)
    assert view['schema'] == 'simplicio.dashboard-stage-agents/v1'
    assert view['rows'] == stage_agents.rows(events, PRICES)
    assert view['cost'] == budget.cost_estimate(events, PRICES)
    assert stage_agents.view([], PRICES)['rows'] == []
    assert stage_agents.view([], PRICES)['cost']['state'] == 'UNVERIFIED'
