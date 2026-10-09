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


# --- issue #1550: tokens by phase/lane/model, cost per task and per iteration, agent map -------------------------------

def _ev(seq, kind, payload=None, **fields):
    event = {'schema': 'simplicio.dashboard-event/v1', 'seq': seq, 'kind': kind, 'ts': '2026-10-08T10:00:%02dZ' % seq,
             'payload': payload or {}}
    event.update(fields)
    return event


def _tok(seq, model, tokens_in, tokens_out, **fields):
    return _ev(seq, 'token_usage', {'model': model, 'input_tokens': tokens_in, 'output_tokens': tokens_out}, **fields)


HAIKU, OPUS = 'claude-haiku-5-5', 'claude-opus-5-5'


def _by(rows, key):
    return {row['key']: row for row in rows}[key]


def test_tokens_are_broken_down_by_phase_lane_and_model_with_totals():
    events = [
        _tok(1, OPUS, 1000, 200, phase='planning', lane='coder', task_id='T1'),
        _tok(2, HAIKU, 5000, 800, phase='executing', lane='coder', task_id='T1'),
        _tok(3, HAIKU, 1000, 200, phase='executing', lane='tester', task_id='T2'),
    ]
    breakdown = stage_agents.view(events, PRICES)['breakdown']
    assert _by(breakdown['by_phase'], 'executing')['tokens'] == 7000
    assert _by(breakdown['by_phase'], 'planning')['tokens'] == 1200
    assert _by(breakdown['by_lane'], 'coder')['tokens'] == 7000
    assert _by(breakdown['by_lane'], 'tester')['tokens'] == 1200
    assert _by(breakdown['by_model'], HAIKU)['tokens_in'] == 6000
    assert _by(breakdown['by_model'], OPUS)['tokens_out'] == 200
    assert breakdown['tokens']['total'] == 8200 and breakdown['tokens']['state'] == 'PASS'
    assert breakdown['tokens']['proof_kind'] == 'medido'


def test_cost_per_task_sums_to_the_run_cost_and_is_estimado():
    events = [
        _tok(1, OPUS, 1_000_000, 100_000, phase='planning', task_id='T1'),
        _tok(2, HAIKU, 2_000_000, 1_000_000, phase='executing', task_id='T2'),
        _tok(3, HAIKU, 2_000_000, 1_000_000, phase='executing', task_id='T2'),
    ]
    view = stage_agents.view(events, PRICES)
    tasks = _by(view['breakdown']['by_task'], 'T2')
    assert _by(view['breakdown']['by_task'], 'T1')['cost_usd'] == 6.0
    assert tasks['cost_usd'] == 1.4 and tasks['cost_state'] == 'ESTIMADO' and tasks['proof_kind'] == 'estimado'
    assert round(sum(row['cost_usd'] for row in view['breakdown']['by_task']), 6) == view['cost']['usd'] == 7.4


def test_cost_per_iteration_uses_the_event_iteration_then_the_last_one_seen_before_it():
    events = [
        _ev(1, 'iteration_started', iteration=1),
        _tok(2, HAIKU, 1_000_000, 0, task_id='T1', iteration=1),
        _ev(3, 'iteration_started', iteration=2),
        _tok(4, HAIKU, 2_000_000, 0, task_id='T1'),
        _tok(5, HAIKU, 1_000_000, 0, task_id='T1', iteration=1),
    ]
    by_iteration = {row['key']: row for row in stage_agents.view(events, PRICES)['breakdown']['by_iteration']}
    assert by_iteration[1]['tokens_in'] == 2_000_000 and by_iteration[1]['cost_usd'] == 0.2
    assert by_iteration[2]['tokens_in'] == 2_000_000 and by_iteration[2]['source'] == 'ordem dos eventos'
    assert by_iteration[1]['source'] == 'evento'
    assert [row['key'] for row in stage_agents.view(events, PRICES)['breakdown']['by_iteration']] == [1, 2]


def test_an_event_with_no_iteration_known_stays_unattributed_not_guessed():
    rows = stage_agents.view([_tok(1, HAIKU, 10, 10, task_id='T1')], PRICES)['breakdown']['by_iteration']
    assert [row['key'] for row in rows] == [None] and rows[0]['source'] is None


def test_zero_token_worker_records_stay_unverified_with_the_reason_and_are_never_invented():
    events = [_ev(1, 'token_usage', {'input_tokens': 0, 'output_tokens': 0, 'reason': 'deterministic_worker_no_llm'},
                  lane='worker', task_id='T1')]
    breakdown = stage_agents.view(events, PRICES)['breakdown']
    assert breakdown['tokens']['state'] == 'UNVERIFIED' and breakdown['tokens']['total'] is None
    assert 'tokens do provedor não medidos' in breakdown['tokens']['reason']
    row = breakdown['by_task'][0]
    assert row['cost_usd'] is None and row['cost_state'] == 'UNVERIFIED' and row['reason']
    assert row['tokens'] is None


def test_no_token_usage_gives_an_empty_unverified_breakdown_with_a_reason():
    breakdown = stage_agents.view([], PRICES)['breakdown']
    for key in ('by_phase', 'by_lane', 'by_model', 'by_task', 'by_iteration'):
        assert breakdown[key] == []
    assert breakdown['tokens']['state'] == 'UNVERIFIED' and breakdown['tokens']['reason']


def test_a_model_without_a_price_makes_its_task_cost_unverified_with_the_reason():
    row = stage_agents.view([_tok(1, 'modelo-x', 5, 5, task_id='T9')], PRICES)['breakdown']['by_task'][0]
    assert row['cost_usd'] is None and row['cost_state'] == 'UNVERIFIED' and 'modelo-x' in row['reason']
    assert row['tokens'] == 10


def test_agent_map_comes_from_worker_claimed_events_and_slots_stay_unverified():
    events = [
        _ev(1, 'worker_claimed', {'lease_id': 'L1', 'branch': 'feat/a'}, lane='coder', task_id='T1'),
        _ev(2, 'worker_claimed', {'lease_id': 'L2'}, lane='coder', task_id='T2'),
        _ev(3, 'worker_claimed', {}, lane='tester', task_id='T3'),
    ]
    agent_map = stage_agents.view(events, PRICES)['agent_map']
    lanes = _by(agent_map['lanes'], 'coder')
    assert lanes['claims'] == 2 and lanes['tasks'] == ['T1', 'T2'] and lanes['lease_ids'] == ['L1', 'L2']
    assert lanes['state'] == 'PASS'
    tester = _by(agent_map['lanes'], 'tester')
    assert tester['claims'] == 1 and tester['lease_ids'] == [] and tester['lease_reason']
    assert agent_map['slots']['state'] == 'UNVERIFIED' and agent_map['slots']['reason']
    assert agent_map['state'] == 'PASS'


def test_agent_map_without_claims_is_unverified_with_the_reason():
    agent_map = stage_agents.view([], PRICES)['agent_map']
    assert agent_map['lanes'] == [] and agent_map['state'] == 'UNVERIFIED' and agent_map['reason']


def test_hostile_names_pass_through_as_plain_data():
    name = '<img src=x onerror=alert(1)>'
    breakdown = stage_agents.view([_tok(1, name, 10, 10, phase=name, lane=name, task_id=name)], PRICES)['breakdown']
    assert breakdown['by_task'][0]['key'] == name and breakdown['by_model'][0]['key'] == name
