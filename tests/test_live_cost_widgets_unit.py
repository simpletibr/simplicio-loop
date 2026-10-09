'''View tests for the cost widgets of the Simplicio Live cost panel (issue #1404, cost widgets, TDD red).

The widgets read the GET /api/runs/<id>/budget body (budget.report). Token bars list the measured tokens by phase and by
model: they show numbers only when token_usage was measured, else they stay UNVERIFIED with a reason and draw no bar.
Cost per task and per iteration joins the measured tokens with the ESTIMADO USD of the price table. A row with no price
keeps its measured tokens and shows USD UNVERIFIED with the reason. Tokens with no task or no iteration go to a labelled
unattributed row, so no figure is invented. The view (static/extras/cost-widgets.js) runs in node through tests/fixtures/live_pipeline/cost_driver.mjs.
'''
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / 'simplicio_loop' / 'dashboard' / 'static'
WIDGETS = STATIC / 'extras' / 'cost-widgets.js'
DRIVER = REPO / 'tests' / 'fixtures' / 'live_pipeline' / 'cost_driver.mjs'


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed')


def _view(budget):
    proc = subprocess.run([_node(), str(DRIVER)], input=json.dumps({'budget': budget}).replace('"__INF__"', '1e999'), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _unverified(reason):
    return {'limit': None, 'used': None, 'projected': None, 'state': 'UNVERIFIED', 'proof_kind': 'estimado', 'reason': reason}


def _budget(usage=None, cost=None):
    usage = usage if usage is not None else {
        'tokens': 2_500_000, 'usd': None, 'samples': 4,
        'by_phase': {'executing': 1_500_000, 'validating': 1_000_000},
        'by_lane': {'route-a': 1_500_000, 'route-b': 1_000_000},
        'by_model': {'claude-haiku-5-5': 2_000_000, 'claude-sonnet-4-6': 500_000},
        'by_task': {'T1': 1_500_000, 'T2': 1_000_000},
        'by_iteration': {'1': 1_000_000, '2': 1_000_000},
        'unattributed_tokens': {'task': 0, 'iteration': 500_000},
    }
    cost = cost if cost is not None else {
        'usd': 5.0, 'state': 'ESTIMADO', 'proof_kind': 'estimado', 'reason': None, 'as_of': '2026-10-08',
        'source_url': 'https://example.test/pricing', 'by_model': {'claude-haiku-5-5': 5.0},
        'by_task': {'T1': 2.0, 'T2': 1.0}, 'tasks': 2, 'by_iteration': {'1': 1.0, '2': 1.5}, 'iterations': 2,
        'unattributed_usd': {'task': 0.0, 'iteration': 0.5},
    }
    return {'phase': 'executing', 'limits': {}, 'rows': {key: _unverified('sem limite') for key in ('tokens', 'usd', 'seconds')},
            'usage': usage, 'cost': cost, 'comparison': None}


def test_token_bars_show_the_measured_tokens_by_phase_and_model_largest_first():
    bars = _view(_budget())['tokenBars']
    assert bars['state'] == 'MEASURED'
    assert bars['total'] == 2_500_000
    assert bars['phases'] == [{'label': 'executing', 'value': 1_500_000}, {'label': 'validating', 'value': 1_000_000}]
    assert bars['models'] == [{'label': 'claude-haiku-5-5', 'value': 2_000_000}, {'label': 'claude-sonnet-4-6', 'value': 500_000}]
    assert bars['modelsOther'] is None


def test_token_bars_without_measured_tokens_stay_unverified_with_a_reason_and_no_bar():
    for budget in (None, _budget(usage={'tokens': None, 'usd': None, 'samples': 0, 'by_phase': {}, 'by_lane': {},
                                        'by_model': {}, 'by_task': {}, 'by_iteration': {},
                                        'unattributed_tokens': {'task': 0, 'iteration': 0}})):
        bars = _view(budget)['tokenBars']
        assert bars['state'] == 'UNVERIFIED'
        assert bars['reason'] and 'token_usage' in bars['reason']
        assert bars['phases'] == [] and bars['models'] == [] and bars['total'] is None


def test_token_bars_fold_the_models_past_eight_into_one_other_row():
    models = {'modelo-%02d' % i: 1000 * (i + 1) for i in range(10)}
    usage = {'tokens': sum(models.values()), 'usd': None, 'samples': 10, 'by_phase': {'executing': sum(models.values())},
             'by_lane': {}, 'by_model': models, 'by_task': {}, 'by_iteration': {}, 'unattributed_tokens': {'task': 0, 'iteration': 0}}
    bars = _view(_budget(usage=usage))['tokenBars']
    assert len(bars['models']) == 8
    assert bars['models'][0] == {'label': 'modelo-09', 'value': 10000}
    assert bars['modelsOther'] == {'models': 2, 'value': 1000 + 2000}


def test_cost_per_task_joins_the_measured_tokens_with_the_estimated_usd():
    rows = {row['key']: row for row in _view(_budget())['taskCosts']['rows']}
    assert _view(_budget())['taskCosts']['state'] == 'ESTIMADO'
    assert rows['task:T1']['label'] == 'Tarefa T1'
    assert rows['task:T1']['state'] == 'ESTIMADO'
    assert 'USD 2.0000' in rows['task:T1']['detail'] and '1.500.000 tokens' in rows['task:T1']['detail']
    assert 'USD 1.0000' in rows['task:T2']['detail']


def test_tokens_with_no_task_are_a_labelled_unattributed_row_not_a_task():
    usage = _budget()['usage']
    usage = dict(usage, by_task={'T1': 1_500_000}, unattributed_tokens={'task': 1_000_000, 'iteration': 0})
    budget = _budget(usage=usage, cost={**_budget()['cost'], 'by_task': {'T1': 2.0}, 'unattributed_usd': {'task': 1.0, 'iteration': 0.0}})
    rows = _view(budget)['taskCosts']['rows']
    last = rows[-1]
    assert last['key'] == 'unattributed-task'
    assert last['label'] == 'Sem tarefa identificada'
    assert '1.000.000 tokens' in last['detail'] and 'USD 1.0000' in last['detail']
    assert [row['key'] for row in rows] == ['task:T1', 'unattributed-task']


def test_cost_per_task_keeps_the_tokens_and_says_why_the_usd_is_unverified_without_a_price():
    cost = {'usd': None, 'state': 'UNVERIFIED', 'reason': 'tabela de preços indisponível', 'by_model': {}, 'by_task': {},
            'tasks': 0, 'by_iteration': {}, 'iterations': 0, 'unattributed_usd': {'task': None, 'iteration': None}}
    tasks = _view(_budget(cost=cost))['taskCosts']
    row = next(row for row in tasks['rows'] if row['key'] == 'task:T1')
    assert row['state'] == 'UNVERIFIED'
    assert '1.500.000 tokens' in row['detail'] and 'tabela de preços indisponível' in row['detail']
    assert tasks['state'] == 'UNVERIFIED'


def test_no_task_id_on_any_event_makes_the_task_split_unverified_with_the_reason():
    usage = {'tokens': 500, 'usd': None, 'samples': 1, 'by_phase': {'executing': 500}, 'by_lane': {}, 'by_model': {},
             'by_task': {}, 'by_iteration': {}, 'unattributed_tokens': {'task': 500, 'iteration': 500}}
    cost = {'usd': None, 'state': 'UNVERIFIED', 'reason': 'tabela de preços indisponível', 'by_model': {}, 'by_task': {},
            'tasks': 0, 'by_iteration': {}, 'iterations': 0, 'unattributed_usd': {'task': None, 'iteration': None}}
    tasks = _view(_budget(usage=usage, cost=cost))['taskCosts']
    assert tasks['state'] == 'UNVERIFIED'
    assert 'task_id' in tasks['reason']
    assert [row['key'] for row in tasks['rows']] == ['unattributed-task']


def test_cost_per_iteration_lists_each_measured_iteration_and_its_unattributed_remainder():
    iterations = _view(_budget())['iterationCosts']
    rows = {row['key']: row for row in iterations['rows']}
    assert iterations['state'] == 'ESTIMADO'
    assert rows['iteration:1']['label'] == 'Iteração 1'
    assert 'USD 1.0000' in rows['iteration:1']['detail'] and '1.000.000 tokens' in rows['iteration:1']['detail']
    assert 'USD 1.5000' in rows['iteration:2']['detail'] and '1.000.000 tokens' in rows['iteration:2']['detail']
    assert rows['unattributed-iteration']['label'] == 'Sem iteração identificada'


def test_no_iteration_on_any_event_says_the_producer_does_not_write_it():
    usage = {'tokens': 500, 'usd': None, 'samples': 1, 'by_phase': {'executing': 500}, 'by_lane': {}, 'by_model': {},
             'by_task': {'T1': 500}, 'by_iteration': {}, 'unattributed_tokens': {'task': 0, 'iteration': 500}}
    iterations = _view(_budget(usage=usage))['iterationCosts']
    assert iterations['state'] == 'UNVERIFIED'
    assert 'iteração' in iterations['reason']
    assert [row['key'] for row in iterations['rows']] == ['unattributed-iteration']


def test_a_long_task_list_shows_eight_rows_and_counts_the_rest():
    by_task = {'T%02d' % i: 1000 * (i + 1) for i in range(12)}
    usage = {'tokens': sum(by_task.values()), 'usd': None, 'samples': 12, 'by_phase': {'executing': sum(by_task.values())},
             'by_lane': {}, 'by_model': {}, 'by_task': by_task, 'by_iteration': {}, 'unattributed_tokens': {'task': 0, 'iteration': 0}}
    tasks = _view(_budget(usage=usage, cost={**_budget()['cost'], 'by_task': {}}))['taskCosts']
    attributed = [row for row in tasks['rows'] if row['key'].startswith('task:')]
    assert len(attributed) == 8
    assert attributed[0]['key'] == 'task:T11'
    assert tasks['more'] == 4


def test_a_zero_measured_total_draws_no_bar_so_no_share_is_ever_a_division_by_zero():
    usage = {'tokens': 0, 'usd': None, 'samples': 0, 'by_phase': {'executing': 0}, 'by_lane': {}, 'by_model': {'m': 0},
             'by_task': {}, 'by_iteration': {}, 'unattributed_tokens': {'task': 0, 'iteration': 0}}
    bars = _view(_budget(usage=usage))['tokenBars']
    assert bars['state'] == 'UNVERIFIED'
    assert bars['phases'] == [] and bars['models'] == []


def test_the_cost_widgets_load_on_demand_so_static_live_keeps_its_gzip_budget():
    static_import = re.compile(r"^\s*(?:import|export)\b[^;]*\bfrom\s+['\"][^'\"]*cost-widgets\.js['\"]", re.M)
    for path in sorted(STATIC.rglob('*.js')):
        assert not static_import.search(path.read_text(encoding='utf-8')), '%s imports cost-widgets.js statically' % path.name
    extras = (STATIC / 'extras' / 'extras.js').read_text(encoding='utf-8')
    assert re.search(r"import\(\s*['\"]\./cost-widgets\.js['\"]\s*\)", extras), 'extras.js does not import cost-widgets.js on demand'
    live = ''.join(path.read_text(encoding='utf-8') for path in (STATIC / 'live').iterdir() if path.suffix in ('.js', '.html'))
    assert 'cost-widgets' not in live and 'costWidgets' not in live, 'static/live still carries the cost widgets'


def test_the_cost_widgets_never_write_markup_from_event_names():
    text = WIDGETS.read_text(encoding='utf-8')
    for banned in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'createContextualFragment', 'DOMParser'):
        assert banned not in text, banned


def test_counts_that_are_not_finite_numbers_never_become_a_bar():
    usage = {'tokens': 1000, 'usd': None, 'samples': 1, 'by_phase': {'executing': 1000, 'text': '5', 'nothing': None, 'huge': '__INF__', 'flag': True},
             'by_lane': {}, 'by_model': {}, 'by_task': {}, 'by_iteration': {}, 'unattributed_tokens': {'task': 0, 'iteration': 0}}
    bars = _view(_budget(usage=usage))['tokenBars']
    assert [item['label'] for item in bars['phases']] == ['executing']
