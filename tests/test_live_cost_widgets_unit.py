'''View tests for the cost widgets of the Simplicio Live cost panel (issues #1404 and #1550, TDD red).

The widgets read the GET /api/runs/<id>/budget body (budget.report). The origin rows say how many measured tokens the provider
itself reported (by_source) and whether the USD of the run is the provider's reported cost (medido) or the price table's
estimate (estimado); with no measured token they stay UNVERIFIED with a reason and have no row. Cost per task and per iteration
joins the measured tokens with the USD of the run. A row with no USD keeps its measured tokens and shows USD UNVERIFIED with the
reason. Tokens with no task or no iteration go to a labelled unattributed row, so no figure is invented. The tokens by phase, lane
and model are the stacked bars of extras.js, so this view draws none. The view (static/extras/cost-widgets.js) runs in node through
tests/fixtures/live_pipeline/cost_driver.mjs.
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
        'by_source': {'provider': 1_000_000, 'other': 1_500_000},
    }
    cost = cost if cost is not None else {
        'usd': 5.0, 'state': 'ESTIMADO', 'proof_kind': 'estimado', 'reason': None, 'as_of': '2026-10-08',
        'source_url': 'https://example.test/pricing', 'by_model': {'claude-haiku-5-5': 5.0},
        'by_task': {'T1': 2.0, 'T2': 1.0}, 'tasks': 2, 'by_iteration': {'1': 1.0, '2': 1.5}, 'iterations': 2,
        'unattributed_usd': {'task': 0.0, 'iteration': 0.5},
    }
    return {'phase': 'executing', 'limits': {}, 'rows': {key: _unverified('sem limite') for key in ('tokens', 'usd', 'seconds')},
            'usage': usage, 'cost': cost, 'comparison': None}


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


def _floor_budget(**cost_extra):
    cost = {'state': 'ESTIMADO', 'usd': 0.016, 'proof_kind': 'estimado', 'reason': None, 'as_of': '2026-10-08', 'by_task': {'T1': 0.016},
            'by_iteration': {'1': 0.016}, 'unattributed_usd': {'task': 0.0, 'iteration': 0.0}, 'floor': True,
            'floor_reason': 'USD a partir de: 1 evento(s) com prompt acima de 100000 tokens sem dado por requisição; o nível de preço acima do limiar não foi verificado (UNVERIFIED)',
            'floor_tasks': ['T1'], 'floor_iterations': ['1'], 'floor_unattributed': {'task': False, 'iteration': False}}
    cost.update(cost_extra)
    usage = {'tokens': 152000, 'by_task': {'T1': 152000}, 'by_iteration': {'1': 152000}, 'unattributed_tokens': {'task': 0, 'iteration': 0}}
    return {'usage': usage, 'cost': cost}


def test_a_floor_row_reads_a_partir_de_and_the_note_carries_the_floor_reason():
    view = _view(_floor_budget())
    row = view['taskCosts']['rows'][0]
    assert row['state'] == 'ESTIMADO' and row['floor'] is True
    assert 'a partir de USD 0.0160' in row['detail'] and 'estimado' not in row['detail']
    assert 'a partir de USD 0.0160' in view['iterationCosts']['rows'][0]['detail']
    assert 'sem dado por requisição' in view['taskCosts']['reason'] and 'UNVERIFIED' in view['taskCosts']['reason']


def test_an_exact_row_keeps_the_estimado_label_and_no_floor_note():
    view = _view(_floor_budget(floor=False, floor_reason=None, floor_tasks=[], floor_iterations=[]))
    row = view['taskCosts']['rows'][0]
    assert row['floor'] is False and 'USD 0.0160 estimado' in row['detail']
    assert 'requisição' not in view['taskCosts']['reason']


def _rows(view):
    return {row['key']: row for row in view['provenance']['rows']}


def test_the_view_has_no_token_bars_because_extras_draws_the_stacked_ones():
    view = _view(_budget())
    assert set(view) == {'provenance', 'taskCosts', 'iterationCosts'}


def test_provenance_says_how_many_measured_tokens_the_provider_reported():
    view = _view(_budget())
    assert view['provenance']['state'] == 'MEASURED'
    assert '2.500.000 tokens' in view['provenance']['reason'] and '4 eventos' in view['provenance']['reason']
    tokens = _rows(view)['source-tokens']
    assert tokens['label'] == 'Tokens do provedor' and tokens['state'] == 'PASS'
    assert tokens['detail'] == '1.000.000 tokens de 2.500.000 tokens (40%) reportados pelo provedor · 1.500.000 tokens de outras fontes'


def test_provenance_with_every_token_from_the_provider_has_no_other_sources_note():
    usage = dict(_budget()['usage'], by_source={'provider': 2_500_000, 'other': 0})
    tokens = _rows(_view(_budget(usage=usage)))['source-tokens']
    assert tokens['state'] == 'PASS' and 'outras fontes' not in tokens['detail'] and '(100%)' in tokens['detail']


def test_provenance_with_no_provider_token_is_unverified_and_names_where_the_tokens_came_from():
    usage = dict(_budget()['usage'], by_source={'provider': 0, 'other': 2_500_000})
    tokens = _rows(_view(_budget(usage=usage)))['source-tokens']
    assert tokens['state'] == 'UNVERIFIED'
    assert tokens['detail'] == 'nenhum token reportado pelo provedor: 2.500.000 tokens vêm de outras fontes'


def test_provenance_without_the_source_split_is_unverified_with_the_reason():
    usage = dict(_budget()['usage'])
    del usage['by_source']
    tokens = _rows(_view(_budget(usage=usage)))['source-tokens']
    assert tokens['state'] == 'UNVERIFIED' and 'origem dos tokens' in tokens['detail']


def test_provenance_without_measured_tokens_is_unverified_with_a_reason_and_no_row():
    empty = {'tokens': None, 'usd': None, 'samples': 0, 'by_phase': {}, 'by_lane': {}, 'by_model': {}, 'by_task': {},
             'by_iteration': {}, 'unattributed_tokens': {'task': 0, 'iteration': 0}, 'by_source': {'provider': 0, 'other': 0}}
    zero = dict(empty, tokens=0)
    for budget in (None, _budget(usage=empty), _budget(usage=zero)):
        provenance = _view(budget)['provenance']
        assert provenance['state'] == 'UNVERIFIED' and 'token_usage' in provenance['reason']
        assert provenance['rows'] == []


def test_the_usd_of_the_run_is_estimado_with_the_price_table_date():
    usd = _rows(_view(_budget()))['source-usd']
    assert usd['label'] == 'USD do run' and usd['state'] == 'ESTIMADO'
    assert usd['detail'] == 'USD 5.0000 estimado · tabela de preços de 2026-10-08'


def test_the_usd_of_the_run_is_medido_when_the_provider_reported_every_cost():
    cost = dict(_budget()['cost'], proof_kind='medido')
    view = _view(_budget(cost=cost))
    usd = _rows(view)['source-usd']
    assert usd['state'] == 'PASS' and usd['detail'] == 'USD 5.0000 medido (reportado pelo provedor)'
    assert 'estimado' not in usd['detail'] and 'tabela' not in usd['detail']
    for kind in ('taskCosts', 'iterationCosts'):
        assert view[kind]['state'] == 'MEDIDO' and view[kind]['reason'] == 'USD reportado pelo provedor; tokens medidos.'
        assert all(row['state'] == 'PASS' for row in view[kind]['rows'] if row['detail'].count('USD ') and 'não verificado' not in row['detail'])
    row = next(row for row in view['taskCosts']['rows'] if row['key'] == 'task:T1')
    assert row['detail'].endswith('USD 2.0000 medido (reportado pelo provedor)')


def test_a_floor_usd_of_the_run_reads_a_partir_de_and_a_medido_one_never_does():
    floor = _rows(_view(_floor_budget()))['source-usd']
    assert floor['state'] == 'ESTIMADO' and floor['detail'].startswith('a partir de USD 0.0160')
    medido = _rows(_view(_floor_budget(proof_kind='medido', floor=False)))['source-usd']
    assert medido['state'] == 'PASS' and 'a partir de' not in medido['detail']


def test_the_usd_of_the_run_without_a_cost_is_unverified_with_the_cost_reason():
    cost = {'usd': None, 'state': 'UNVERIFIED', 'reason': 'tabela de preços indisponível'}
    usd = _rows(_view(_budget(cost=cost)))['source-usd']
    assert usd['state'] == 'UNVERIFIED' and 'tabela de preços indisponível' in usd['detail']
    bare = _rows(_view(_budget(cost={'usd': None, 'state': 'UNVERIFIED'})))['source-usd']
    assert bare['state'] == 'UNVERIFIED' and 'custo do run não estimado' in bare['detail']


def test_provenance_counts_that_are_not_finite_numbers_are_not_a_split():
    usage = dict(_budget()['usage'], by_source={'provider': '__INF__', 'other': True})
    assert _rows(_view(_budget(usage=usage)))['source-tokens']['state'] == 'UNVERIFIED'
