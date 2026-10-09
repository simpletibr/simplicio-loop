'''Unit tests for the per-task and per-iteration split of the run budget (issue #1404, cost widgets, TDD red).

The token_usage envelope carries task_id, iteration and lane at its top level (dashboard_events.build_envelope). Tokens
are grouped by those fields; USD is the measured tokens times the price table (ESTIMADO). A token or USD with no task or
no iteration on its event goes to the 'unattributed' figure, so the parts add up to the total and nothing is invented.
'''
from simplicio_loop.dashboard import budget

MODEL = 'claude-haiku-5-5'
PRICES = {'as_of': '2026-10-08', 'source_url': 'https://example.test/pricing',
          'models': {MODEL: {'input_per_mtok': 1, 'output_per_mtok': 2}}}


def _usage(seq, input_tokens, output_tokens, task_id=None, iteration=None, lane=None, model=MODEL):
    return {'schema': 'simplicio.dashboard-event/v1', 'seq': seq, 'kind': 'token_usage', 'phase': 'executing',
            'ts': '2026-10-08T10:00:%02dZ' % seq, 'task_id': task_id, 'iteration': iteration, 'lane': lane,
            'payload': {'input_tokens': input_tokens, 'output_tokens': output_tokens, 'model': model}}


def _events():
    return [
        _usage(1, 1_000_000, 0, task_id='T1', iteration=1, lane='route-a'),
        _usage(2, 0, 500_000, task_id='T1', iteration=2, lane='route-a'),
        _usage(3, 1_000_000, 0, task_id='T2', iteration=None, lane='route-b'),
        _usage(4, 0, 1_000_000, task_id=None, iteration=2, lane='route-b'),
    ]


def test_usage_groups_tokens_by_task_and_iteration_from_the_envelope():
    used = budget.usage(_events())
    assert used['by_task'] == {'T1': 1_500_000, 'T2': 1_000_000}
    assert used['by_iteration'] == {'1': 1_000_000, '2': 1_500_000}


def test_usage_reports_the_tokens_with_no_task_or_iteration_as_unattributed():
    used = budget.usage(_events())
    assert used['unattributed_tokens'] == {'task': 1_000_000, 'iteration': 1_000_000}
    assert sum(used['by_task'].values()) + used['unattributed_tokens']['task'] == used['tokens']


def test_usage_groups_by_lane_from_the_envelope_not_the_payload():
    assert budget.usage(_events())['by_lane'] == {'route-a': 1_500_000, 'route-b': 2_000_000}


def test_cost_estimate_prices_each_task_and_iteration_and_keeps_the_rest_unattributed():
    cost = budget.cost_estimate(_events(), PRICES)
    assert cost['state'] == 'ESTIMADO'
    assert cost['usd'] == 5.0
    assert cost['by_task'] == {'T1': 2.0, 'T2': 1.0}
    assert cost['tasks'] == 2
    assert cost['by_iteration'] == {'1': 1.0, '2': 3.0}
    assert cost['iterations'] == 2
    assert cost['unattributed_usd'] == {'task': 2.0, 'iteration': 1.0}
    assert sum(cost['by_task'].values()) + cost['unattributed_usd']['task'] == cost['usd']
    assert sum(cost['by_iteration'].values()) + cost['unattributed_usd']['iteration'] == cost['usd']


def test_cost_estimate_keeps_only_the_most_expensive_tasks_and_counts_them_all():
    events = [_usage(seq, 1_000_000 * seq, 0, task_id='T%d' % seq) for seq in range(1, 26)]
    cost = budget.cost_estimate(events, PRICES)
    assert cost['tasks'] == 25
    assert len(cost['by_task']) == budget.TOP_N
    assert 'T25' in cost['by_task'] and 'T1' not in cost['by_task']


def test_an_unpriced_model_leaves_the_per_task_cost_empty_with_the_reason():
    cost = budget.cost_estimate([_usage(1, 10, 10, task_id='T1', model='modelo-sem-preco')], PRICES)
    assert cost['usd'] is None and cost['state'] == 'UNVERIFIED'
    assert cost['by_task'] == {} and cost['tasks'] == 0
    assert 'modelo-sem-preco' in cost['reason']


def test_no_measured_tokens_means_no_per_task_or_per_iteration_cost():
    cost = budget.cost_estimate([], PRICES)
    assert cost['by_task'] == {} and cost['by_iteration'] == {} and cost['tasks'] == 0
    assert cost['unattributed_usd'] == {'task': None, 'iteration': None}


def test_a_boolean_or_negative_iteration_is_not_an_iteration():
    events = [_usage(1, 1_000_000, 0, task_id='T1', iteration=True), _usage(2, 1_000_000, 0, task_id='T1', iteration=-1)]
    used = budget.usage(events)
    assert used['by_iteration'] == {}
    assert used['unattributed_tokens']['iteration'] == 2_000_000
    assert budget.cost_estimate(events, PRICES)['unattributed_usd']['iteration'] == 2.0
