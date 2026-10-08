'''Unit tests for the run budget reading of the Simplicio Live dashboard (issue #1404, budget slice, TDD red).

The declared budget comes from the run's task-contract.json (sum over tasks of routing.budget). Usage comes from the
token_usage and cost_sample events and from the event clock. The projection extrapolates usage by phase progress. A
figure with no declared limit or no measured usage is UNVERIFIED, never a pass.
'''
import json

from simplicio_loop.dashboard import budget


def _contract(tmp_path, *budgets):
    tasks = [{'routing': {'budget': b}} for b in budgets]
    (tmp_path / 'task-contract.json').write_text(json.dumps({'tasks': tasks}), encoding='utf-8')


def test_declared_sums_the_task_budgets(tmp_path):
    _contract(tmp_path, {'tokens': 1000, 'usd': 1.5, 'seconds': None}, {'tokens': 500, 'usd': None, 'seconds': 60})
    assert budget.declared(tmp_path) == {'tokens': 1500, 'usd': 1.5, 'seconds': 60}


def test_declared_is_none_when_no_task_declares_a_limit(tmp_path):
    _contract(tmp_path, {'tokens': None, 'usd': None, 'seconds': None})
    assert budget.declared(tmp_path) == {'tokens': None, 'usd': None, 'seconds': None}


def test_declared_without_a_contract_file_is_all_none(tmp_path):
    assert budget.declared(tmp_path) == {'tokens': None, 'usd': None, 'seconds': None}


def test_declared_ignores_malformed_contracts(tmp_path):
    (tmp_path / 'task-contract.json').write_text('{oops', encoding='utf-8')
    assert budget.declared(tmp_path)['tokens'] is None


def _usage(seq, kind, phase, payload):
    return {'schema': 'simplicio.dashboard-event/v1', 'seq': seq, 'kind': kind, 'phase': phase,
            'ts': '2026-10-08T10:00:%02dZ' % seq, 'payload': payload}


def test_usage_sums_tokens_and_cost_and_groups_by_phase_and_model():
    events = [
        _usage(1, 'token_usage', 'planning', {'model': 'm-a', 'input_tokens': 100, 'output_tokens': 20}),
        _usage(2, 'token_usage', 'executing', {'model': 'm-a', 'input_tokens': 300, 'output_tokens': 50, 'lane': 'l1'}),
        _usage(3, 'token_usage', 'executing', {'model': 'm-b', 'input_tokens': 10, 'output_tokens': 5}),
        _usage(4, 'cost_sample', 'executing', {'model': 'm-a', 'usd': 0.25}),
    ]
    got = budget.usage(events)
    assert got['tokens'] == 485
    assert got['usd'] == 0.25
    assert got['by_phase'] == {'planning': 120, 'executing': 365}
    assert got['by_model'] == {'m-a': 470, 'm-b': 15}
    assert got['by_lane'] == {'l1': 350}
    assert got['samples'] == 3


def test_usage_without_producer_events_is_unmeasured():
    got = budget.usage([_usage(1, 'phase_entered', 'planning', {})])
    assert got['tokens'] is None and got['usd'] is None and got['samples'] == 0


def test_usage_ignores_bad_numbers():
    got = budget.usage([_usage(1, 'token_usage', 'planning', {'input_tokens': 'x', 'output_tokens': -4})])
    assert got['tokens'] is None


def test_projection_extrapolates_by_phase_and_flags_an_overrun():
    row = budget.project(limit=600, used=300, phase='executing')
    assert row['state'] == 'PROJECTED_OVER'
    assert row['projected'] == 700
    assert row['proof_kind'] == 'estimado'


def test_projection_ok_when_the_forecast_fits():
    row = budget.project(limit=2000, used=300, phase='executing')
    assert row['state'] == 'OK'


def test_projection_exceeded_when_already_over():
    assert budget.project(limit=100, used=101, phase='intake')['state'] == 'EXCEEDED'


def test_projection_unverified_without_limit_or_usage_or_progress():
    assert budget.project(limit=None, used=5, phase='executing')['state'] == 'UNVERIFIED'
    assert budget.project(limit=10, used=None, phase='executing')['state'] == 'UNVERIFIED'
    assert budget.project(limit=10, used=5, phase='intake')['state'] == 'UNVERIFIED'
    assert budget.project(limit=10, used=5, phase=None)['state'] == 'UNVERIFIED'


def test_projection_at_done_is_the_measured_figure():
    row = budget.project(limit=100, used=90, phase='done')
    assert row['state'] == 'OK' and row['projected'] == 90


def _record(run_id, verdict='COMPLETE', **fields):
    base = {'run_id': run_id, 'verdict': verdict, 'duration_s': None, 'tokens': None, 'cost_usd': None, 'iterations': None}
    base.update(fields)
    return base


def test_comparison_averages_the_measured_values_of_the_previous_runs():
    current = _record('now', duration_s=120, tokens=1500, iterations=3)
    previous = [_record('a', duration_s=100, tokens=1000, iterations=2),
                _record('b', duration_s=60, tokens=500, iterations=4),
                _record('c', duration_s=None, tokens=None)]
    got = budget.compare(current, previous)
    assert got['runs'] == 3
    assert got['fields']['duration_s'] == {'current': 120, 'average': 80.0, 'samples': 2, 'delta_pct': 50.0, 'state': 'ESTIMADO'}
    assert got['fields']['tokens']['average'] == 750.0 and got['fields']['tokens']['delta_pct'] == 100.0
    assert got['fields']['cost_usd']['state'] == 'UNVERIFIED'


def test_comparison_skips_the_current_run_and_unfinished_runs_and_keeps_only_ten():
    previous = [_record('now', duration_s=999), _record('live', verdict='RUNNING', duration_s=999)]
    previous += [_record('r%d' % i, duration_s=10) for i in range(12)]
    got = budget.compare(_record('now', duration_s=20), previous)
    assert got['runs'] == 10
    assert got['fields']['duration_s']['average'] == 10.0 and got['fields']['duration_s']['delta_pct'] == 100.0


def test_comparison_with_no_previous_run_is_unverified():
    got = budget.compare(_record('now', duration_s=20), [])
    assert got['runs'] == 0
    assert {row['state'] for row in got['fields'].values()} == {'UNVERIFIED'}
