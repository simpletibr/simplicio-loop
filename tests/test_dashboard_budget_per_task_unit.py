'''Unit tests for the cost per task and per iteration of the run budget (issue #1550, TDD red).

``cost_by_task_and_iteration`` groups the measured token_usage events by the task_id and iteration of their envelope.
Each row is priced with the same ``_event_usd`` and ``_rate`` as the run cost (ESTIMADO). A row with an unpriced model or
a null count has ``usd`` None, state UNVERIFIED and the reason: a missing count is never read as 0.
'''
from simplicio_loop.dashboard import budget

MODEL = 'claude-haiku-5-5'
PRICES = {'as_of': '2026-10-08', 'source_url': 'https://example.test/pricing',
          'models': {MODEL: {'input_per_mtok': 1, 'output_per_mtok': 2}}}


def _usage(seq, input_tokens, output_tokens, task_id=None, iteration=None, model=MODEL):
    return {'schema': 'simplicio.dashboard-event/v1', 'seq': seq, 'kind': 'token_usage', 'phase': 'executing',
            'ts': f'2026-10-08T10:00:{seq:02d}Z', 'task_id': task_id, 'iteration': iteration, 'lane': None,
            'payload': {'input_tokens': input_tokens, 'output_tokens': output_tokens, 'model': model}}


def _two_tasks_two_iterations():
    return [
        _usage(1, 1_000_000, 0, task_id='T1', iteration=1),
        _usage(2, 0, 500_000, task_id='T1', iteration=2),
        _usage(3, 1_000_000, 0, task_id='T2', iteration=1),
        _usage(4, 0, 1_000_000, task_id='T2', iteration=2),
    ]


def _split(events, prices=PRICES):
    return budget.cost_by_task_and_iteration(events, prices)


def _rows(rows):
    return [(row['task_id'], row['iteration'], row['usd'], row['state']) for row in rows]


def test_two_tasks_with_two_iterations_each_are_priced_per_row():
    split = _split(_two_tasks_two_iterations())
    assert _rows(split['per_task']) == [('T1', None, 2.0, 'ESTIMADO'), ('T2', None, 3.0, 'ESTIMADO')]
    assert _rows(split['per_iteration']) == [
        ('T1', 1, 1.0, 'ESTIMADO'), ('T1', 2, 1.0, 'ESTIMADO'), ('T2', 1, 1.0, 'ESTIMADO'), ('T2', 2, 2.0, 'ESTIMADO')]


def test_each_row_carries_the_measured_token_counts_of_its_events():
    split = _split(_two_tasks_two_iterations())
    t1 = split['per_task'][0]
    assert (t1['tokens_in'], t1['tokens_out']) == (1_000_000, 500_000)
    assert (split['per_iteration'][3]['tokens_in'], split['per_iteration'][3]['tokens_out']) == (0, 1_000_000)


def test_an_unpriced_model_gives_usd_null_with_the_reason():
    events = [_usage(1, 10, 10, task_id='T1', iteration=1, model='modelo-sem-preco')]
    row = _split(events)['per_task'][0]
    assert row['usd'] is None and row['state'] == 'UNVERIFIED'
    assert 'modelo-sem-preco' in row['reason']


def test_a_null_count_gives_usd_null_and_the_count_stays_null_not_zero():
    events = [_usage(1, None, 500_000, task_id='T1', iteration=1)]
    row = _split(events)['per_iteration'][0]
    assert row['usd'] is None and row['state'] == 'UNVERIFIED'
    assert row['tokens_in'] is None
    assert row['tokens_out'] == 500_000
    assert row['reason']


def test_events_of_other_kinds_or_schemas_are_ignored():
    events = _two_tasks_two_iterations() + [
        {'schema': 'simplicio.dashboard-event/v1', 'seq': 9, 'kind': 'cost_sample', 'phase': 'executing',
         'ts': '2026-10-08T10:00:09Z', 'task_id': 'T1', 'iteration': 1, 'lane': None, 'payload': {'usd': 99}},
        dict(_usage(10, 1_000_000, 0, task_id='T3', iteration=1), schema='other/v1'),
    ]
    split = _split(events)
    assert _rows(split['per_task']) == [('T1', None, 2.0, 'ESTIMADO'), ('T2', None, 3.0, 'ESTIMADO')]
    assert len(split['per_iteration']) == 4


def test_the_per_task_rows_sum_to_the_per_iteration_rows():
    events = _two_tasks_two_iterations() + [_usage(5, 0, 1_000_000, task_id=None, iteration=3)]
    split = _split(events)
    per_task_usd = sum(row['usd'] for row in split['per_task'])
    per_iteration_usd = sum(row['usd'] for row in split['per_iteration'])
    assert round(per_task_usd, 6) == round(per_iteration_usd, 6) == 7.0


def test_the_run_cost_equals_the_sum_of_the_priced_rows_when_all_are_priced():
    events = _two_tasks_two_iterations()
    run_usd = budget.cost_estimate(events, PRICES)['usd']
    split = _split(events)
    assert run_usd == sum(row['usd'] for row in split['per_task']) == 5.0


def test_report_puts_the_two_lists_into_the_cost_object_next_to_the_existing_fields(tmp_path):
    payload = budget.report(tmp_path, _two_tasks_two_iterations(), PRICES)
    assert payload['cost']['usd'] == 5.0
    assert len(payload['cost']['per_task']) == 2
    assert len(payload['cost']['per_iteration']) == 4
    assert payload['cost']['by_task'] == {'T1': 2.0, 'T2': 3.0}


def test_no_measured_tokens_gives_empty_rows():
    assert _split([]) == {'per_task': [], 'per_iteration': []}
