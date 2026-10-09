'''Unit and contract tests for the per-stage agents and cost reading of the Simplicio Live dashboard (issue #1404).

Each row is one stage (phase) of the run: the role and effort come from the model-roles table, the model and the tokens
come from the token_usage events, and the cost comes from the same price path as the budget panel. Every cost is an
estimate and carries proof_kind "estimado". A model the table does not list is UNVERIFIED for role and effort, never a guess.
'''
import copy
import json
import os
import random
import threading
import time
from pathlib import Path

import pytest

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


# --- post-merge audit of #1556 (D1-D7): row cap, single pass, memoized view, finite numbers, short names -----------------
TOP = stage_agents.TOP_N
DIMS = ('by_phase', 'by_lane', 'by_model', 'by_task', 'by_iteration')


def _old_usage_events(events):
    out, current = [], None
    for event in events:
        if isinstance(event, dict) and event.get('schema') == stage_agents.SCHEMA:
            own = event.get('iteration') if isinstance(event.get('iteration'), int) and not isinstance(event.get('iteration'), bool) and event.get('iteration') >= 0 else None
            if event.get('kind') == 'token_usage':
                out.append((event, own, 'evento') if own is not None else (event, current, 'ordem dos eventos' if current is not None else None))
            if own is not None:
                current = own
    return out


def _old_text(value):
    return value if isinstance(value, str) and value else None


def _old_payload(event):
    return event['payload'] if isinstance(event.get('payload'), dict) else {}


def _old_breakdown(events, prices):
    '''The #1556 implementation, kept here as the oracle: it rescans the events once per group.'''
    usage = _old_usage_events(list(events))
    keys = {'by_phase': lambda e, i: _old_text(e.get('phase')), 'by_lane': lambda e, i: _old_text(e.get('lane')),
            'by_model': lambda e, i: _old_text(_old_payload(e).get('model')), 'by_task': lambda e, i: _old_text(e.get('task_id')),
            'by_iteration': lambda e, i: i}
    out = {}
    for name, pick in keys.items():
        groups = {}
        for event, iteration, source in usage:
            groups.setdefault(pick(event, iteration), []).append((event, source))
        found = []
        for key, members in groups.items():
            sources = {source for _, source in members}
            source = None if None in sources else ('ordem dos eventos' if 'ordem dos eventos' in sources else 'evento')
            tokens_in = sum(budget._number(_old_payload(e).get('input_tokens')) or 0 for e, _ in members)
            tokens_out = sum(budget._number(_old_payload(e).get('output_tokens')) or 0 for e, _ in members)
            cost = budget.cost_estimate([e for e, _ in members], prices)
            found.append({'key': key, 'tokens_in': tokens_in, 'tokens_out': tokens_out, 'tokens': (tokens_in + tokens_out) or None,
                          'tokens_proof_kind': 'medido', 'cost_usd': cost['usd'], 'cost_state': cost['state'],
                          'proof_kind': 'estimado', 'reason': cost['reason'], 'source': source if name == 'by_iteration' else None})
        if name == 'by_iteration':
            found.sort(key=lambda row: (row['key'] is None, row['key'] if row['key'] is not None else 0))
        out[name] = found
    total = sum((budget._number(_old_payload(e).get('input_tokens')) or 0) + (budget._number(_old_payload(e).get('output_tokens')) or 0)
                for e, _, _ in usage)
    tokens = {'total': total or None, 'state': 'PASS' if total else 'UNVERIFIED', 'proof_kind': 'medido', 'reason': None}
    if not total:
        tokens['reason'] = ('tokens do provedor não medidos: o registro do worker traz 0 ou null (sem contagem do provedor)'
                            if usage else 'tokens do provedor não medidos: nenhum token_usage no run')
    out['tokens'] = tokens
    return out


def _small_fixture(seed=7, count=240):
    rnd = random.Random(seed)
    events, seq = [], 0
    for _ in range(count):
        seq += 1
        roll = rnd.random()
        fields = {k: v for k, v in (('phase', rnd.choice(['planning', 'executing', 'testing', None, ''])),
                                    ('lane', rnd.choice(['coder', 'tester', 'review', None])),
                                    ('task_id', rnd.choice(['T1', 'T2', 'T3', 'T4', 'T5', None])),
                                    ('iteration', rnd.choice([None, None, 0, 1, 2, 3, True, -1, 'x']))) if v is not None}
        if roll < 0.7:
            events.append(_tok(seq, rnd.choice([HAIKU, OPUS, 'modelo-x', HAIKU + '-20260101']), rnd.choice([0, 10, 1000, 250_000]),
                               rnd.choice([0, 5, 700, 90_000, None]), **fields))
        elif roll < 0.85:
            events.append(_ev(seq, 'worker_claimed', {'lease_id': rnd.choice(['L1', 'L2', 'L3', None]), 'branch': rnd.choice(['a', 'b', None])}, **fields))
        elif roll < 0.95:
            events.append(_ev(seq, 'iteration_started', **fields))
        else:
            events.append(rnd.choice([{'schema': 'other/v1', 'kind': 'token_usage'}, 'junk', None, {'kind': 'token_usage'}]))
    return events


def _old_agent_map_lanes(events):
    lanes = {}
    for event in events:
        if not (isinstance(event, dict) and event.get('schema') == stage_agents.SCHEMA and event.get('kind') == 'worker_claimed'):
            continue
        lane = _old_text(event.get('lane'))
        row = lanes.setdefault(lane, {'key': lane, 'claims': 0, 'tasks': [], 'lease_ids': [], 'branches': [],
                                      'state': 'PASS', 'proof_kind': 'medido', 'lease_reason': None})
        row['claims'] += 1
        for field, value in (('tasks', _old_text(event.get('task_id'))), ('lease_ids', _old_text(_old_payload(event).get('lease_id'))),
                             ('branches', _old_text(_old_payload(event).get('branch')))):
            if value and value not in row[field]:
                row[field].append(value)
    for row in lanes.values():
        row['lease_reason'] = None if row['lease_ids'] else stage_agents.NO_LEASE
    return list(lanes.values())


def _without_totals(lanes):
    return [{k: v for k, v in lane.items() if not k.endswith('_total')} for lane in lanes]


def test_the_single_pass_output_equals_the_old_output_when_every_dimension_is_under_the_cap():
    for seed in (7, 8, 9):
        events = _small_fixture(seed)
        new = stage_agents.breakdown(events, PRICES)
        old = _old_breakdown(events, PRICES)
        assert all(len(new[dim]) <= TOP for dim in DIMS)
        assert new == old
        assert stage_agents.view(events, PRICES)['cost'] == budget.cost_estimate(events, PRICES)
        assert _without_totals(stage_agents.agent_map(events)['lanes']) == _old_agent_map_lanes(events)


def test_stage_rows_equal_the_old_per_group_cost_estimate_when_under_the_cap():
    events = _small_fixture(11)
    groups = {}
    for event in events:
        if isinstance(event, dict) and event.get('schema') == stage_agents.SCHEMA and event.get('kind') == 'token_usage':
            payload = _old_payload(event)
            phase = event['phase'] if isinstance(event.get('phase'), str) else ''
            model = payload['model'] if isinstance(payload.get('model'), str) else ''
            groups.setdefault((phase, model), []).append(event)
    got = {(row['phase'] or '', row['model'] or ''): row for row in stage_agents.rows(events, PRICES)}
    assert set(got) == set(groups) and len(got) <= TOP
    for key, group in groups.items():
        cost = budget.cost_estimate(group, PRICES)
        assert (got[key]['cost_usd'], got[key]['cost_state']) == (cost['usd'], cost['state'])
        assert got[key]['tokens_in'] == sum(budget._number(_old_payload(e).get('input_tokens')) or 0 for e in group)


def _distinct(count, **per_dimension):
    '''One token_usage event per index; dimension i carries tokens 100 + i, so the top 20 are the highest indexes.'''
    return [_tok(i + 1, per_dimension.get('model', lambda n: HAIKU)(i), 100 + i, 0, phase='p%d' % i, lane='l%d' % i,
                 task_id='t%d' % i, iteration=i) for i in range(count)]


def test_every_breakdown_dimension_keeps_20_rows_plus_one_others_row_that_sums_the_rest():
    count = 50
    breakdown = stage_agents.view(_distinct(count, model=lambda i: '%s-v%d' % (HAIKU, i)), PRICES)['breakdown']
    for dim in DIMS:
        rows = breakdown[dim]
        assert len(rows) == TOP + 1, dim
        *kept, others = rows
        assert others['key'] is None and others['others'] == count - TOP, dim
        assert sum(r['tokens_in'] for r in rows) == sum(100 + i for i in range(count)), dim
        assert others['tokens_in'] == sum(100 + i for i in range(count - TOP)), dim
        assert others['proof_kind'] == 'estimado' and others['cost_state'] == 'ESTIMADO' and others['cost_usd'] is not None
        assert all('others' not in r for r in kept)
    assert [r['tokens_in'] for r in breakdown['by_task'][:TOP]] == [100 + i for i in range(count - TOP, count)]
    assert [r['key'] for r in breakdown['by_iteration'][:TOP]] == list(range(count - TOP, count))
    assert [r['key'] for r in breakdown['by_phase'][:TOP]] == ['p%d' % i for i in range(count - TOP, count)]


def test_a_breakdown_with_exactly_20_groups_has_no_others_row_and_21_groups_fold_one():
    for count, rows_expected, others in ((TOP, TOP, None), (TOP + 1, TOP + 1, 1)):
        rows = stage_agents.breakdown(_distinct(count), PRICES)['by_task']
        assert len(rows) == rows_expected
        assert rows[-1].get('others') == others


def test_the_others_row_of_an_unpriced_model_is_unverified_with_the_reason_and_never_a_made_up_price():
    events = [_tok(i + 1, 'modelo-%d' % i, 10 + i, 0, task_id='t%d' % i) for i in range(30)]
    others = stage_agents.breakdown(events, PRICES)['by_task'][-1]
    assert others['others'] == 10 and others['cost_usd'] is None and others['cost_state'] == 'UNVERIFIED'
    assert 'sem preço' in others['reason'] and others['proof_kind'] == 'estimado'


def test_the_stage_rows_are_capped_too_and_the_others_row_is_not_a_phase():
    rows = stage_agents.view(_distinct(35), PRICES)['rows']
    assert len(rows) == TOP + 1
    assert rows[-1]['others'] == 15 and rows[-1]['phase'] is None and rows[-1]['model'] is None and rows[-1]['role'] is None
    assert sum(r['tokens_in'] for r in rows) == sum(100 + i for i in range(35))


def test_the_agent_map_keeps_20_lanes_plus_an_others_row_with_the_claims_of_the_rest():
    events = []
    for i in range(50):
        for n in range(i + 1):
            events.append(_ev(len(events) + 1, 'worker_claimed', {'lease_id': 'L%d-%d' % (i, n)}, lane='l%d' % i, task_id='t%d' % i))
    agent_map = stage_agents.view(events, PRICES)['agent_map']
    lanes = agent_map['lanes']
    assert len(lanes) == TOP + 1 and agent_map['state'] == 'PASS'
    assert [lane['key'] for lane in lanes[:TOP]] == ['l%d' % i for i in range(50 - TOP, 50)]
    others = lanes[-1]
    assert others['key'] is None and others['others'] == 30 and others['claims'] == sum(range(1, 31))
    assert others['tasks'] == [] and others['lease_ids'] == [] and others['lease_reason'] is None
    assert sum(lane['claims'] for lane in lanes) == len(events)


def test_a_lane_lists_its_first_20_distinct_values_and_counts_every_distinct_one():
    events = []
    for i in range(100):
        for _ in range(2):
            events.append(_ev(len(events) + 1, 'worker_claimed', {'lease_id': 'L%d' % i, 'branch': 'b%d' % (i % 30)}, lane='coder', task_id='t%d' % i))
    [lane] = stage_agents.agent_map(events)['lanes']
    assert lane['claims'] == 200
    assert lane['tasks'] == ['t%d' % i for i in range(TOP)] and lane['tasks_total'] == 100
    assert lane['lease_ids'] == ['L%d' % i for i in range(TOP)] and lane['lease_ids_total'] == 100
    assert lane['branches'] == ['b%d' % i for i in range(TOP)] and lane['branches_total'] == 30


def test_agent_map_does_not_rescan_lists_per_claim():
    events = [_ev(i + 1, 'worker_claimed', {'lease_id': 'L%d' % i, 'branch': 'b%d' % i}, lane='coder', task_id='t%d' % i) for i in range(20_000)]
    start = time.perf_counter()
    [lane] = stage_agents.agent_map(events)['lanes']
    assert time.perf_counter() - start < 1.5
    assert lane['claims'] == 20_000 and lane['tasks_total'] == 20_000 and len(lane['tasks']) == TOP


class _CountingList(list):
    iterations = 0

    def __iter__(self):
        type(self).iterations += 1
        return super().__iter__()


def test_view_scans_the_events_at_most_twice_and_prices_a_bounded_number_of_buckets(monkeypatch):
    events = _CountingList(_distinct(400, model=lambda i: '%s-v%d' % (HAIKU, i % 7)) + [
        _ev(500 + i, 'worker_claimed', {'lease_id': 'L%d' % i}, lane='l%d' % (i % 9), task_id='t%d' % i) for i in range(100)])
    priced, real = [], budget.cost_estimate
    monkeypatch.setattr(budget, 'cost_estimate', lambda evs, prices: (priced.append(len(evs)), real(evs, prices))[1])
    _CountingList.iterations = 0
    stage_agents.view(events, PRICES)
    assert _CountingList.iterations <= 2
    assert sum(priced) < 400 and max(priced) <= 7


def test_a_million_event_names_cannot_inflate_the_view_names_are_cut_to_120_characters():
    huge = 'x' * 1_000_000
    events = [_tok(1, huge, 10, 10, phase=huge, lane=huge, task_id=huge),
              _ev(2, 'worker_claimed', {'lease_id': huge, 'branch': huge}, lane=huge, task_id=huge)]
    view = stage_agents.view(events, PRICES)
    assert len(json.dumps(view)) < 12_000
    cut = 'x' * 119 + '…'
    breakdown = view['breakdown']
    assert (breakdown['by_phase'][0]['key'], breakdown['by_lane'][0]['key'], breakdown['by_task'][0]['key'],
            breakdown['by_model'][0]['key']) == (cut, cut, cut, cut)
    assert breakdown['by_task'][0]['reason'] and len(breakdown['by_task'][0]['reason']) < 300
    [lane] = view['agent_map']['lanes']
    assert lane['key'] == cut and lane['tasks'] == [cut] and lane['lease_ids'] == [cut] and lane['branches'] == [cut]
    assert view['rows'][0]['phase'] == cut and view['rows'][0]['model'] == cut
    assert list(view['cost']['by_model']) == [] and len(view['cost']['reason']) < 300


def test_a_name_of_120_characters_or_less_is_kept_whole():
    name = 'n' * 120
    assert stage_agents.breakdown([_tok(1, HAIKU, 1, 1, task_id=name)], PRICES)['by_task'][0]['key'] == name


# --- D6: a non-finite token count is rejected, never serialised as NaN -----------------------------------------------------
@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf'), -1, True, None, 'x'])
def test_budget_number_rejects_non_finite_negative_and_non_numbers(value):
    assert budget._number(value) is None


def test_budget_number_still_accepts_finite_numbers():
    assert budget._number(0) == 0 and budget._number(12) == 12 and budget._number(1.5) == 1.5


def test_a_nan_or_infinite_token_count_stays_unverified_and_the_json_has_no_nan():
    events = [_tok(1, HAIKU, float('nan'), float('inf'), task_id='T1'), _tok(2, HAIKU, float('nan'), 5, task_id='T1')]
    view = stage_agents.view(events, PRICES)
    body = json.dumps(view, allow_nan=False)
    assert 'NaN' not in body and 'Infinity' not in body
    assert view['breakdown']['tokens']['total'] == 5 and view['breakdown']['tokens']['state'] == 'PASS'
    only_nan = stage_agents.view([_tok(1, HAIKU, float('nan'), float('nan'))], PRICES)['breakdown']['tokens']
    assert only_nan['state'] == 'UNVERIFIED' and only_nan['total'] is None and only_nan['reason']


# --- D3: the view of an unchanged run is memoized ----------------------------------------------------------------------
class _Reader:
    def __init__(self, events=None):
        self.calls = 0
        self.events = events if events is not None else [_tok(1, HAIKU, 1000, 200, phase='executing', lane='coder', task_id='T1')]

    def __call__(self, run_dir):
        self.calls += 1
        return list(self.events)


@pytest.fixture
def run_dir(tmp_path):
    stage_agents.clear_cache()
    path = tmp_path / 'run-1'
    path.mkdir()
    (path / 'events.jsonl').write_text('{"seq": 1}\n', encoding='utf-8')
    yield path
    stage_agents.clear_cache()


def test_an_unchanged_run_is_served_from_the_cache_without_reading_the_events_again(run_dir):
    reader = _Reader()
    first = stage_agents.run_view(run_dir, PRICES, read=reader)
    second = stage_agents.run_view(run_dir, PRICES, read=reader)
    assert reader.calls == 1 and second == first
    assert first['breakdown']['by_task'][0]['key'] == 'T1' and first == stage_agents.view(reader.events, PRICES)


def test_a_grown_rewritten_touched_or_rotated_events_file_invalidates_the_cache(run_dir):
    reader = _Reader()
    stage_agents.run_view(run_dir, PRICES, read=reader)
    stream = run_dir / 'events.jsonl'
    with stream.open('a', encoding='utf-8') as fh:
        fh.write('{"seq": 2}\n')
    stage_agents.run_view(run_dir, PRICES, read=reader)
    assert reader.calls == 2
    stage_agents.run_view(run_dir, PRICES, read=reader)
    assert reader.calls == 2
    stat = stream.stat()
    os.utime(stream, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    stage_agents.run_view(run_dir, PRICES, read=reader)
    assert reader.calls == 3
    replacement = run_dir / 'events.jsonl.new'
    replacement.write_bytes(stream.read_bytes())
    os.utime(replacement, ns=(stat.st_atime_ns, stream.stat().st_mtime_ns))
    replacement.replace(stream)
    stage_agents.run_view(run_dir, PRICES, read=reader)
    assert reader.calls == 4
    (run_dir / 'events.jsonl.1').write_text('{"seq": 0}\n', encoding='utf-8')
    stage_agents.run_view(run_dir, PRICES, read=reader)
    assert reader.calls == 5


def test_a_different_price_table_recomputes_and_the_new_cost_shows(run_dir):
    reader = _Reader([_tok(1, HAIKU, 1_000_000, 0, task_id='T1')])
    cheap = stage_agents.run_view(run_dir, PRICES, read=reader)
    dear = copy.deepcopy(PRICES)
    dear['models'][next(k for k in dear['models'] if HAIKU.startswith(k))]['input_per_mtok'] = 99
    assert stage_agents.run_view(run_dir, dear, read=reader)['cost']['usd'] == 99.0 != cheap['cost']['usd']
    assert reader.calls == 2


def test_a_run_without_a_live_stream_or_with_a_derived_one_is_never_cached(tmp_path):
    stage_agents.clear_cache()
    bare = tmp_path / 'bare'
    bare.mkdir()
    reader = _Reader()
    stage_agents.run_view(bare, PRICES, read=reader)
    stage_agents.run_view(bare, PRICES, read=reader)
    assert reader.calls == 2
    (bare / 'events.jsonl').write_text('', encoding='utf-8')
    derived = _Reader([dict(_tok(1, HAIKU, 1, 1), derived=True)])
    stage_agents.run_view(bare, PRICES, read=derived)
    stage_agents.run_view(bare, PRICES, read=derived)
    assert derived.calls == 2
    stage_agents.clear_cache()


def test_the_cache_holds_a_bounded_number_of_runs(tmp_path):
    stage_agents.clear_cache()
    reader = _Reader()
    for i in range(stage_agents.CACHE_MAX + 10):
        run = tmp_path / ('run-%d' % i)
        run.mkdir()
        (run / 'events.jsonl').write_text('{"seq": 1}\n', encoding='utf-8')
        stage_agents.run_view(run, PRICES, read=reader)
    assert stage_agents.cache_size() <= stage_agents.CACHE_MAX
    stage_agents.clear_cache()


def test_concurrent_polls_of_one_run_read_the_events_once_and_get_the_same_view(run_dir):
    gate = threading.Event()

    class Slow(_Reader):
        def __call__(self, path):
            gate.wait(5)
            return super().__call__(path)

    reader, results = Slow(), []
    threads = [threading.Thread(target=lambda: results.append(stage_agents.run_view(run_dir, PRICES, read=reader))) for _ in range(8)]
    for thread in threads:
        thread.start()
    time.sleep(0.2)
    gate.set()
    for thread in threads:
        thread.join(10)
    assert reader.calls == 1 and len(results) == 8 and all(r == results[0] for r in results)


# --- review of #1562: gaps the mutation run found in the cache and the others row -----------------------------------------
def test_the_others_row_sums_the_output_tokens_of_the_folded_groups_too():
    events = [_tok(i + 1, HAIKU, 100 + i, 7 + i, phase='p%d' % i, lane='l%d' % i, task_id='t%d' % i, iteration=i)
              for i in range(TOP + 5)]
    breakdown = stage_agents.view(events, PRICES)['breakdown']
    for dim in DIMS:
        assert sum(row['tokens_out'] for row in breakdown[dim]) == sum(7 + i for i in range(TOP + 5)), dim
        assert breakdown[dim][-1]['tokens_out'] > 0 and breakdown[dim][-1]['tokens'] == (
            breakdown[dim][-1]['tokens_in'] + breakdown[dim][-1]['tokens_out']), dim


def test_an_append_that_restores_the_mtime_still_invalidates_by_size(run_dir):
    reader = _Reader()
    stage_agents.run_view(run_dir, PRICES, read=reader)
    stream = run_dir / 'events.jsonl'
    before = stream.stat()
    with stream.open('a', encoding='utf-8') as fh:
        fh.write('{"seq": 2}\n')
    os.utime(stream, ns=(before.st_atime_ns, before.st_mtime_ns))
    stage_agents.run_view(run_dir, PRICES, read=reader)
    assert reader.calls == 2


def test_a_same_size_rewrite_in_place_that_restores_the_mtime_still_invalidates(run_dir):
    reader = _Reader()
    stage_agents.run_view(run_dir, PRICES, read=reader)
    stream = run_dir / 'events.jsonl'
    before = stream.stat()
    with stream.open('r+b') as fh:
        fh.write(b'{"seq": 9}\n')
    after = stream.stat()
    assert after.st_size == before.st_size and after.st_ino == before.st_ino
    os.utime(stream, ns=(before.st_atime_ns, before.st_mtime_ns))
    stage_agents.run_view(run_dir, PRICES, read=reader)
    assert reader.calls == 2


def test_two_run_dirs_with_identical_events_never_share_an_entry(tmp_path):
    stage_agents.clear_cache()
    first, second = tmp_path / 'run-a', tmp_path / 'run-b'
    for run in (first, second):
        run.mkdir()
        (run / 'events.jsonl').write_text('{"seq": 1}\n', encoding='utf-8')
    stat = (first / 'events.jsonl').stat()
    os.utime(second / 'events.jsonl', ns=(stat.st_atime_ns, stat.st_mtime_ns))
    a = _Reader([_tok(1, HAIKU, 111, 0, task_id='A')])
    b = _Reader([_tok(1, HAIKU, 222, 0, task_id='B')])
    view_a = stage_agents.run_view(first, PRICES, read=a)
    view_b = stage_agents.run_view(second, PRICES, read=b)
    assert [r['key'] for r in view_a['breakdown']['by_task']] == ['A'] and [r['key'] for r in view_b['breakdown']['by_task']] == ['B']
    assert stage_agents.run_view(first, PRICES, read=a) is view_a and stage_agents.run_view(second, PRICES, read=b) is view_b
    assert (a.calls, b.calls) == (1, 1)
    stage_agents.clear_cache()


def test_a_failing_read_is_not_cached_and_does_not_hold_the_lock(run_dir):
    class Boom(Exception):
        pass

    def failing(path):
        raise Boom()

    with pytest.raises(Boom):
        stage_agents.run_view(run_dir, PRICES, read=failing)
    with pytest.raises(Boom):
        stage_agents.run_view(run_dir, PRICES, read=failing)
    reader, results = _Reader(), []
    thread = threading.Thread(target=lambda: results.append(stage_agents.run_view(run_dir, PRICES, read=reader)))
    thread.start()
    thread.join(5)
    assert not thread.is_alive() and reader.calls == 1 and results[0]['breakdown']['by_task'][0]['key'] == 'T1'
    good = stage_agents.run_view(run_dir, PRICES, read=reader)
    with run_dir.joinpath('events.jsonl').open('a', encoding='utf-8') as fh:
        fh.write('{"seq": 2}\n')
    with pytest.raises(Boom):
        stage_agents.run_view(run_dir, PRICES, read=failing)
    assert stage_agents.run_view(run_dir, PRICES, read=reader) is not good and reader.calls == 2


def test_a_slow_run_does_not_block_another_run(tmp_path):
    stage_agents.clear_cache()
    slow, fast = tmp_path / 'slow', tmp_path / 'fast'
    for run in (slow, fast):
        run.mkdir()
        (run / 'events.jsonl').write_text('{"seq": 1}\n', encoding='utf-8')
    gate, started = threading.Event(), threading.Event()

    def blocked(path):
        started.set()
        gate.wait(10)
        return [_tok(1, HAIKU, 1, 0)]

    worker = threading.Thread(target=lambda: stage_agents.run_view(slow, PRICES, read=blocked))
    worker.start()
    assert started.wait(5)
    done = []
    other = threading.Thread(target=lambda: done.append(stage_agents.run_view(fast, PRICES, read=_Reader())))
    other.start()
    other.join(3)
    finished = not other.is_alive()
    gate.set()
    worker.join(10)
    stage_agents.clear_cache()
    assert finished and len(done) == 1


def test_a_stream_that_grows_while_it_is_read_is_read_again_on_the_next_poll(run_dir):
    class Growing(_Reader):
        def __call__(self, path):
            events = super().__call__(path)
            if self.calls == 1:
                with (run_dir / 'events.jsonl').open('a', encoding='utf-8') as fh:
                    fh.write('{"seq": 2}\n')
            return events

    reader = Growing()
    stage_agents.run_view(run_dir, PRICES, read=reader)
    stage_agents.run_view(run_dir, PRICES, read=reader)
    assert reader.calls == 2
    stage_agents.run_view(run_dir, PRICES, read=reader)
    assert reader.calls == 2


def test_the_cache_evicts_the_least_recently_used_run_first(tmp_path):
    stage_agents.clear_cache()
    runs = []
    for i in range(stage_agents.CACHE_MAX + 1):
        run = tmp_path / ('run-%d' % i)
        run.mkdir()
        (run / 'events.jsonl').write_text('{"seq": 1}\n', encoding='utf-8')
        runs.append(run)
    reader = _Reader()
    for run in runs[:stage_agents.CACHE_MAX]:
        stage_agents.run_view(run, PRICES, read=reader)
    stage_agents.run_view(runs[0], PRICES, read=reader)
    stage_agents.run_view(runs[-1], PRICES, read=reader)
    calls = reader.calls
    stage_agents.run_view(runs[0], PRICES, read=reader)
    assert reader.calls == calls
    stage_agents.run_view(runs[1], PRICES, read=reader)
    assert reader.calls == calls + 1
    stage_agents.clear_cache()


def test_two_run_dirs_with_the_same_name_under_different_parents_never_share_an_entry(tmp_path, monkeypatch):
    stage_agents.clear_cache()
    monkeypatch.setattr(stage_agents, '_stamp', lambda run_dir: (('events.jsonl', 1, 11, 1, 1),))  # the same stat everywhere
    first, second = tmp_path / 'repo-a' / 'loop-runs' / 'big-1', tmp_path / 'repo-b' / 'loop-runs' / 'big-1'
    a, b = _Reader([_tok(1, HAIKU, 111, 0, task_id='A')]), _Reader([_tok(1, HAIKU, 222, 0, task_id='B')])
    assert stage_agents.run_view(first, PRICES, read=a)['breakdown']['by_task'][0]['key'] == 'A'
    assert stage_agents.run_view(second, PRICES, read=b)['breakdown']['by_task'][0]['key'] == 'B'
    assert stage_agents.run_view(first, PRICES, read=a)['breakdown']['by_task'][0]['key'] == 'A' and (a.calls, b.calls) == (1, 1)
    stage_agents.clear_cache()


# --- #1565 item 1: cost.by_model is capped like every other dimension -------------------------------------------------------
def _models(count, **fields):
    '''One token_usage event per model id ``<haiku>-v<i>``: every id is priced by its prefix, tokens 100 + i in, 10 out.'''
    return [_tok(i + 1, '%s-v%d' % (HAIKU, i), 100 + i, 10, **fields) for i in range(count)]


def _closes(cost):
    '''The kept models plus the others row add up to the total: exactly when rows were folded (the others row is the rest of the
    total), within the rounding of each listed model (6 decimals) when nothing was.'''
    if 'others' in cost:
        return round(sum(cost['by_model'].values()) + cost['others']['usd'], 6) == cost['usd']
    return abs(sum(cost['by_model'].values()) - cost['usd']) <= 0.5e-6 * len(cost['by_model']) + 1e-9


def test_cost_by_model_keeps_20_models_plus_an_others_row_and_the_parts_close_the_total():
    count = 5000
    cost = stage_agents.view(_models(count), PRICES)['cost']
    assert cost['state'] == 'ESTIMADO' and len(cost['by_model']) == TOP
    others = cost['others']
    assert others['models'] == count - TOP and others['state'] == 'ESTIMADO' and others['reason'] is None
    assert others['tokens_in'] == sum(100 + i for i in range(count - TOP)) and others['tokens_out'] == 10 * (count - TOP)
    assert others['tokens'] == others['tokens_in'] + others['tokens_out'] and others['usd'] > 0
    assert _closes(cost)
    assert len(json.dumps(cost)) < 4000
    # the kept models are the 20 with the highest cost, here the highest indexes
    assert sorted(cost['by_model']) == sorted('%s-v%d' % (HAIKU, i) for i in range(count - TOP, count))


def test_cost_by_model_total_is_the_same_as_without_the_cap():
    events = _models(60)
    cost = stage_agents.view(events, PRICES)['cost']
    price = budget.price_for(PRICES['models'], HAIKU)
    expected = sum((100 + i) * price['input_per_mtok'] + 10 * price['output_per_mtok'] for i in range(60)) / 1_000_000
    assert cost['usd'] == round(expected, 6) and _closes(cost)


@pytest.mark.parametrize('count, folded', [(TOP - 1, None), (TOP, None), (TOP + 1, 1), (TOP + 2, 2)])
def test_cost_by_model_has_no_others_row_up_to_20_models_and_folds_the_rest_after(count, folded):
    cost = stage_agents.view(_models(count), PRICES)['cost']
    assert len(cost['by_model']) == min(count, TOP) and _closes(cost)
    assert (cost['others']['models'] if 'others' in cost else None) == folded


def test_cost_by_model_up_to_20_models_is_listed_by_name_as_before():
    cost = stage_agents.view(_models(TOP), PRICES)['cost']
    assert list(cost['by_model']) == sorted(cost['by_model']) and 'others' not in cost


def test_cost_by_model_keeps_the_most_expensive_models_not_the_first_seen():
    events = [_tok(1, HAIKU + '-cheap-%d' % i, 1, 0) for i in range(30)] + [_tok(2, OPUS + '-dear-%d' % i, 1_000_000, 0) for i in range(5)]
    cost = stage_agents.view(events, PRICES)['cost']
    assert sum(1 for name in cost['by_model'] if name.startswith(OPUS)) == 5 and len(cost['by_model']) == TOP
    assert cost['others']['models'] == 15 and _closes(cost)


def test_cost_by_model_is_capped_on_the_budget_route_too():
    cost = budget.cost_estimate(_models(500), PRICES)
    assert len(cost['by_model']) == TOP and cost['others']['models'] == 500 - TOP and _closes(cost)


def test_cost_by_model_with_an_unpriced_model_among_many_is_unverified_with_the_reason_and_lists_nothing():
    events = _models(100) + [_tok(200, 'modelo-sem-preco', 10, 10)]
    cost = stage_agents.view(events, PRICES)['cost']
    assert cost['state'] == 'UNVERIFIED' and cost['usd'] is None and cost['by_model'] == {} and 'others' not in cost
    assert 'sem preço' in cost['reason'] and 'modelo-sem-preco' in cost['reason']


def test_a_hundred_thousand_distinct_models_keep_the_cost_small():
    cost = stage_agents.view(_models(100_000), PRICES)['cost']
    assert len(json.dumps(cost)) < 4000 and cost['others']['models'] == 100_000 - TOP and _closes(cost)


# --- #1565 item 2: a non-finite or absurd count never reaches the JSON -----------------------------------------------------
STRICT = dict(allow_nan=False)


def test_two_events_of_1e308_tokens_do_not_overflow_to_infinity():
    events = [_tok(1, HAIKU, 1e308, 0, task_id='T1'), _tok(2, HAIKU, 1e308, 0, task_id='T1')]
    view = stage_agents.view(events, PRICES)
    json.dumps(view, **STRICT)
    tokens = view['breakdown']['tokens']
    assert tokens['state'] == 'UNVERIFIED' and tokens['total'] is None and tokens['ignored'] == 2
    assert 'ignorad' in tokens['reason'] and view['cost']['state'] == 'UNVERIFIED' and view['cost']['reason']
    assert all(r['tokens_in'] == 0 and r['tokens_out'] == 0 and r['cost_usd'] is None and r['reason'] for r in view['rows'])


def test_a_valid_count_next_to_an_absurd_one_is_kept_and_the_absurd_one_is_counted_as_ignored():
    events = [_tok(1, HAIKU, 1e308, 0, task_id='T1'), _tok(2, HAIKU, 7, 3, task_id='T1')]
    view = stage_agents.view(events, PRICES)
    json.dumps(view, **STRICT)
    tokens = view['breakdown']['tokens']
    assert tokens['total'] == 10 and tokens['state'] == 'PASS' and tokens['ignored'] == 1 and tokens['ignored_reason']
    assert 'ignored' not in stage_agents.view([_tok(1, HAIKU, 7, 3)], PRICES)['breakdown']['tokens']


@pytest.mark.parametrize('line', [
    '{"schema":"simplicio.dashboard-event/v1","seq":%d,"kind":"token_usage","payload":{"model":"claude-haiku-5-5","input_tokens":1e999,"output_tokens":5}}',
    '{"schema":"simplicio.dashboard-event/v1","seq":%d,"kind":"token_usage","payload":{"model":"claude-haiku-5-5","input_tokens":NaN,"output_tokens":5}}',
    '{"schema":"simplicio.dashboard-event/v1","seq":%d,"kind":"token_usage","payload":{"model":"claude-haiku-5-5","input_tokens":-Infinity,"output_tokens":5}}',
    '{"schema":"simplicio.dashboard-event/v1","seq":%d,"kind":"token_usage","payload":{"model":"claude-haiku-5-5","input_tokens":1e308,"output_tokens":1e308}}',
])
def test_raw_event_json_with_literal_nan_infinity_or_1e999_gives_strict_json(line):
    events = [json.loads(line % i) for i in (1, 2)]
    view = stage_agents.view(events, PRICES)
    body = json.dumps(view, **STRICT)
    assert 'NaN' not in body and 'Infinity' not in body
    tokens = view['breakdown']['tokens']
    assert tokens['ignored'] == 2 and tokens['total'] in (None, 10)
    assert (tokens['reason'] if tokens['total'] is None else tokens['ignored_reason'])
    assert view['cost']['reason'] if tokens['total'] is None else view['cost']['state'] == 'ESTIMADO'


def test_the_budget_report_stays_finite_for_absurd_tokens_and_costs():
    events = [_tok(1, HAIKU, 1e308, 1e308), _tok(2, HAIKU, 1e308, 1e308),
              _ev(3, 'cost_sample', {'usd': 1e308}), _ev(4, 'cost_sample', {'usd': 1e308})]
    json.dumps(budget.report('/nonexistent-run-dir', events, PRICES), **STRICT)
    assert budget.usage(events)['tokens'] is None and budget.usage(events)['usd'] is None


def test_budget_number_rejects_a_count_above_the_sanity_limit_and_keeps_the_limit_itself():
    assert budget._number(budget.MAX_NUMBER) == budget.MAX_NUMBER
    assert budget._number(budget.MAX_NUMBER + 1) is None and budget._number(1e308) is None and budget._number(10 ** 400) is None
    assert budget.MAX_NUMBER == 10 ** 15


# --- #1565 item 3: waiters of one run coalesce on one newer computation, and a stuck computation cannot hang them ------------
def _append(run_dir, text='{"seq": 2}\n'):
    with (run_dir / 'events.jsonl').open('a', encoding='utf-8') as fh:
        fh.write(text)


def _task_keys(view):
    return [row['key'] for row in view['breakdown']['by_task']]


class _Calls:
    '''A reader that records its calls; ``hold`` maps a call number to a gate it waits on, ``on_call`` runs inside the call.'''

    def __init__(self, hold=None, on_call=None, fail=(), derived=False):
        self.calls, self.hold, self.on_call, self.fail, self.derived = [], hold or {}, on_call or {}, set(fail), derived
        self.started = {n: threading.Event() for n in range(1, 9)}
        self.lock = threading.Lock()

    def __call__(self, path):
        with self.lock:
            self.calls.append(1)
            n = len(self.calls)
        self.started[n].set()
        if n in self.on_call:
            self.on_call[n]()
        if n in self.hold:
            assert self.hold[n].wait(10), 'gate %d never opened' % n
        if n in self.fail:
            raise RuntimeError('boom %d' % n)
        return [dict(_tok(1, HAIKU, 100 * n, 0, task_id='T%d' % n), **({'derived': True} if self.derived else {}))]


def _spawn(run_dir, reader, results, count=1):
    threads = [threading.Thread(target=lambda: results.append(stage_agents.run_view(run_dir, PRICES, read=reader))) for _ in range(count)]
    for thread in threads:
        thread.start()
    return threads


def _join(threads):
    for thread in threads:
        thread.join(15)
        assert not thread.is_alive()


def test_pollers_that_arrive_during_a_computation_share_one_newer_computation_not_one_each(run_dir):
    release = threading.Event()
    reader = _Calls(hold={1: release})
    first, later = [], []
    [leader] = _spawn(run_dir, reader, first)
    assert reader.started[1].wait(5)
    _append(run_dir)  # the writer is hot: the stamp the first computation took is already old
    waiters = _spawn(run_dir, reader, later, count=7)
    time.sleep(0.3)
    release.set()
    _join([leader, *waiters])
    assert len(reader.calls) == 2  # one computation for the leader, ONE for the seven waiters (not seven)
    assert _task_keys(first[0]) == ['T1'] and all(_task_keys(v) == ['T2'] for v in later) and len(later) == 7
    assert all(v is later[0] for v in later)


@pytest.mark.parametrize('derived', [False, True])
def test_a_poller_that_arrives_after_the_stamp_but_sees_unchanged_files_reuses_the_computation_in_flight(run_dir, derived):
    release = threading.Event()
    reader = _Calls(hold={1: release}, derived=derived)  # a derived view is never cached: only the stamp lets the waiters share it
    first, later = [], []
    [leader] = _spawn(run_dir, reader, first)
    assert reader.started[1].wait(5)  # the computation has taken its stamp; nothing is appended after it
    waiters = _spawn(run_dir, reader, later, count=6)
    time.sleep(0.3)
    release.set()
    _join([leader, *waiters])
    assert len(reader.calls) == 1 and all(v is first[0] for v in later) and len(later) == 6


def test_a_poller_that_starts_after_an_append_never_gets_a_result_computed_before_it(run_dir):
    release = threading.Event()
    reader = _Calls(hold={1: release})
    first, late = [], []
    [leader] = _spawn(run_dir, reader, first)
    assert reader.started[1].wait(5)
    _append(run_dir)
    [poller] = _spawn(run_dir, reader, late)
    time.sleep(0.2)
    release.set()
    _join([leader, poller])
    assert _task_keys(first[0]) == ['T1'] and _task_keys(late[0]) == ['T2']


def test_waiters_that_arrived_before_the_new_computation_took_its_stamp_reuse_it_even_if_the_writer_keeps_appending(run_dir):
    release1, release2 = threading.Event(), threading.Event()
    reader = _Calls(hold={1: release1, 2: release2}, on_call={2: lambda: _append(run_dir, '{"seq": 3}\n')})
    first, parked = [], []
    [leader] = _spawn(run_dir, reader, first)
    assert reader.started[1].wait(5)
    _append(run_dir)
    waiters = _spawn(run_dir, reader, parked, count=5)
    time.sleep(0.2)
    release1.set()
    assert reader.started[2].wait(5)
    release2.set()
    _join([leader, *waiters])
    assert len(reader.calls) == 2 and all(_task_keys(v) == ['T2'] for v in parked)


def test_a_poller_that_arrives_after_the_new_computation_took_its_stamp_waits_for_a_still_newer_one(run_dir):
    release1, release2 = threading.Event(), threading.Event()
    reader = _Calls(hold={1: release1, 2: release2})
    first, parked, late = [], [], []
    [leader] = _spawn(run_dir, reader, first)
    assert reader.started[1].wait(5)
    _append(run_dir)
    waiters = _spawn(run_dir, reader, parked, count=2)
    time.sleep(0.2)
    release1.set()
    assert reader.started[2].wait(5)  # the second computation has taken its stamp
    _append(run_dir, '{"seq": 3}\n')  # an append it cannot have seen
    [straggler] = _spawn(run_dir, reader, late)
    time.sleep(0.2)
    release2.set()
    _join([leader, *waiters, straggler])
    assert len(reader.calls) == 3
    assert all(_task_keys(v) == ['T2'] for v in parked) and _task_keys(late[0]) == ['T3']


def test_many_pollers_and_a_hot_writer_cost_a_few_computations_not_one_per_poller(run_dir):
    stop = threading.Event()

    def writer():
        while not stop.is_set():
            _append(run_dir)
            time.sleep(0.003)

    def slow_reader_factory():
        calls = []

        def read(path):
            calls.append(1)
            time.sleep(0.1)
            return [_tok(1, HAIKU, 1, 0)]
        return read, calls

    read, calls = slow_reader_factory()
    hot = threading.Thread(target=writer)
    hot.start()
    try:
        results = []
        _join(_spawn(run_dir, read, results, count=12))
    finally:
        stop.set()
        hot.join(5)
    assert len(results) == 12 and len(calls) <= 3


def test_a_stuck_computation_serves_the_last_good_view_flagged_stale_with_its_age(run_dir, monkeypatch):
    monkeypatch.setattr(stage_agents, 'WAIT_TIMEOUT_S', 0.3)
    good = stage_agents.run_view(run_dir, PRICES, read=_Reader())
    assert 'stale' not in good
    _append(run_dir)
    stuck_gate = threading.Event()
    reader = _Calls(hold={1: stuck_gate})
    sink = []
    [stuck] = _spawn(run_dir, reader, sink)
    assert reader.started[1].wait(5)
    begun = time.monotonic()
    served = stage_agents.run_view(run_dir, PRICES, read=_Reader())
    assert time.monotonic() - begun < 5
    assert served['stale'] is True and isinstance(served['age_s'], float) and served['age_s'] >= 0
    assert served['breakdown'] == good['breakdown'] and 'stale' not in good  # the cached view itself is never marked
    stuck_gate.set()
    _join([stuck])
    fresh = stage_agents.run_view(run_dir, PRICES, read=_Reader())
    assert 'stale' not in fresh and 'age_s' not in fresh


def test_a_stuck_computation_with_nothing_cached_is_a_busy_error_with_a_retry_after(run_dir, monkeypatch):
    monkeypatch.setattr(stage_agents, 'WAIT_TIMEOUT_S', 0.3)
    stuck_gate = threading.Event()
    reader = _Calls(hold={1: stuck_gate})
    [stuck] = _spawn(run_dir, reader, [])
    assert reader.started[1].wait(5)
    _append(run_dir)
    begun = time.monotonic()
    with pytest.raises(stage_agents.ViewBusy) as busy:
        stage_agents.run_view(run_dir, PRICES, read=_Reader())
    assert time.monotonic() - begun < 5 and busy.value.retry_after >= 1
    stuck_gate.set()
    _join([stuck])


def test_a_failing_computation_does_not_strand_the_pollers_behind_it(run_dir):
    release = threading.Event()
    reader = _Calls(hold={1: release}, fail={1})
    failed, later, errors = [], [], []

    def lead():
        try:
            failed.append(stage_agents.run_view(run_dir, PRICES, read=reader))
        except RuntimeError as exc:
            errors.append(str(exc))

    leader = threading.Thread(target=lead)
    leader.start()
    assert reader.started[1].wait(5)
    _append(run_dir)
    waiters = _spawn(run_dir, reader, later, count=3)
    time.sleep(0.2)
    release.set()
    _join([leader, *waiters])
    assert errors == ['boom 1'] and failed == [] and len(later) == 3 and all(_task_keys(v) == ['T2'] for v in later)
    assert len(reader.calls) == 2
