'''Pure unit tests for the Simplicio Live history model (history-model.js).

history-model.js turns the simplicio.dashboard-history/v1 records, the trend buckets, the heatmap grid and the run
comparison into what the history view draws: a query string, row texts, heat levels, trend series, delta texts and
phase bars. It runs in node (no DOM, no network, no clock). Every call runs with Date.now, Math.random, fetch and
setTimeout stubbed to throw, so a clock or network use fails the test. These tests fail until history-model.js exists.
'''
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'history' / 'history-model.js'

EXPORTS = ['deltaText', 'heatLevels', 'historyQuery', 'phaseBars', 'rowsOf', 'trendSeries']
TREND_KEYS = ['complete_rate', 'iterations_per_task', 'cost_per_task_usd']
DASH = '—'
MINUS = '−'
SCHEMA = 'simplicio.dashboard-history/v1'
ROW_KEYS = {'runId', 'repo', 'verdict', 'durationText', 'iterations', 'costText', 'startedAt', 'tone'}


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


SCRIPT = '''
import fs from 'node:fs';
import * as model from %s;
const boom = () => { throw new Error('forbidden global: clock, random, network or timer'); };
Date.now = boom;
Math.random = boom;
globalThis.fetch = boom;
globalThis.setTimeout = boom;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const OPS = {
  historyQuery: () => model.historyQuery(input.filters),
  rowsOf: () => model.rowsOf(input.records),
  heatLevels: () => model.heatLevels(input.grid),
  trendSeries: () => model.trendSeries(input.trends, input.key),
  deltaText: () => model.deltaText(input.metric, input.kind),
  phaseBars: () => model.phaseBars(input.compare),
  exports: () => Object.keys(model).sort(),
};
let out;
try {
  out = { value: OPS[input.op]() };
} catch (error) {
  out = { error: error.name + ': ' + error.message };
}
process.stdout.write(JSON.stringify(out));
'''


def _run(op, **payload):
    script = SCRIPT % json.dumps(MODULE.as_uri())
    body = json.dumps(dict(payload, op=op))
    proc = subprocess.run([_node(), '--input-type=module', '-e', script], input=body,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _value(op, **payload):
    out = _run(op, **payload)
    assert 'error' not in out, out.get('error')
    return out['value']


def _error(op, **payload):
    out = _run(op, **payload)
    assert 'error' in out, out
    return out['error']


def _record(run_id='r1', **changes):
    rec = {'schema': SCHEMA, 'run_id': run_id, 'repo': '/repo/a', 'verdict': 'COMPLETE', 'duration_s': 754,
           'iterations': 3, 'cost_usd': 0.75, 'started_at': '2026-10-07T10:00:00Z'}
    rec.update(changes)
    return rec


def _grid(cells=None):
    grid = [[0] * 24 for _ in range(7)]
    for (day, hour), count in (cells or {}).items():
        grid[day][hour] = count
    return grid


def _expected_levels(grid):
    top = max(max(row) for row in grid)
    return [[0 if c == 0 or top == 0 else -(-4 * c // top) for c in row] for row in grid]


def _code():
    text = MODULE.read_text(encoding='utf-8')
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'//[^\n]*', '', text)


# ---------- module surface and purity ----------

def test_the_module_exports_exactly_the_six_functions():
    assert _value('exports') == EXPORTS


@pytest.mark.parametrize('pattern', [r'\bdocument\b', r'\bwindow\b', r'\bfetch\s*\(', r'XMLHttpRequest',
                                     r'\bWebSocket\b', r'\bDate\b', r'\bperformance\b', r'setTimeout',
                                     r'setInterval', r'localStorage', r'sessionStorage', r'Math\.random',
                                     r'\bimport\b', r'\brequire\b', r'\bprocess\b'])
def test_the_module_source_has_no_dom_network_clock_timer_or_host_use(pattern):
    assert not re.search(pattern, _code()), pattern


# ---------- historyQuery ----------

@pytest.mark.parametrize('filters', [None, {}, {'verdict': None, 'repo': '', 'limit': None},
                                     {'verdict': '   ', 'minCost': None, 'since': ''}])
def test_no_usable_filter_gives_an_empty_query_string(filters):
    assert _value('historyQuery', filters=filters) == ''


ALL_FILTERS = {'limit': 50, 'maxCost': 2, 'minCost': 0.5, 'maxIterations': 9, 'minIterations': 1,
               'maxDuration': 3600, 'minDuration': 60, 'until': '2026-10-08', 'since': '2026-10-01',
               'repo': '/r/a', 'verdict': 'COMPLETE'}
ALL_FILTERS_QUERY = ('?verdict=COMPLETE&repo=%2Fr%2Fa&since=2026-10-01&until=2026-10-08&min_duration_s=60'
                     '&max_duration_s=3600&min_iterations=1&max_iterations=9&min_cost_usd=0.5&max_cost_usd=2'
                     '&limit=50')


def test_every_filter_maps_to_its_api_name_in_the_fixed_order_whatever_the_input_order():
    assert _value('historyQuery', filters=ALL_FILTERS) == ALL_FILTERS_QUERY
    reversed_input = dict(reversed(list(ALL_FILTERS.items())))
    assert _value('historyQuery', filters=reversed_input) == ALL_FILTERS_QUERY


@pytest.mark.parametrize('key, api_name, value, encoded', [
    ('verdict', 'verdict', 'BLOCKED', 'BLOCKED'),
    ('repo', 'repo', '/home/u/repo', '%2Fhome%2Fu%2Frepo'),
    ('since', 'since', '2026-10-01', '2026-10-01'),
    ('until', 'until', '2026-10-08', '2026-10-08'),
    ('minDuration', 'min_duration_s', 90, '90'),
    ('maxDuration', 'max_duration_s', 7200, '7200'),
    ('minIterations', 'min_iterations', 2, '2'),
    ('maxIterations', 'max_iterations', 12, '12'),
    ('minCost', 'min_cost_usd', 0.25, '0.25'),
    ('maxCost', 'max_cost_usd', 5, '5'),
    ('limit', 'limit', 25, '25'),
])
def test_each_filter_key_maps_to_its_own_api_name(key, api_name, value, encoded):
    assert _value('historyQuery', filters={key: value}) == '?%s=%s' % (api_name, encoded)


def test_zero_is_a_real_value_and_is_kept():
    assert _value('historyQuery', filters={'minDuration': 0, 'minCost': 0, 'limit': 0}) == \
        '?min_duration_s=0&min_cost_usd=0&limit=0'


def test_values_are_percent_encoded():
    filters = {'repo': '/home/u/my repo&x=1', 'since': '2026-10-01T00:00:00Z'}
    assert _value('historyQuery', filters=filters) == \
        '?repo=%2Fhome%2Fu%2Fmy%20repo%26x%3D1&since=2026-10-01T00%3A00%3A00Z'


def test_empty_values_are_skipped_and_the_others_kept():
    assert _value('historyQuery', filters={'verdict': '', 'repo': '/r', 'limit': None}) == '?repo=%2Fr'


def test_unknown_keys_are_ignored():
    assert _value('historyQuery', filters={'foo': 'bar', 'limit': 5, 'Verdict': 'X'}) == '?limit=5'


# ---------- rowsOf ----------

@pytest.mark.parametrize('records', [None, [], {}, 'abc', 7])
def test_no_usable_records_give_no_rows(records):
    assert _value('rowsOf', records=records) == []


def test_a_complete_record_maps_to_the_row_fields():
    rows = _value('rowsOf', records=[_record('r1', extra='ignored')])
    assert rows == [{'runId': 'r1', 'repo': '/repo/a', 'verdict': 'COMPLETE', 'durationText': '12m 34s',
                     'iterations': 3, 'costText': 'US$ 0.75', 'startedAt': '2026-10-07T10:00:00Z',
                     'tone': 'pass'}]


def test_a_row_carries_exactly_the_documented_keys():
    assert set(_value('rowsOf', records=[_record()])[0]) == ROW_KEYS


def test_null_measures_show_a_dash_and_the_rest_is_kept():
    rows = _value('rowsOf', records=[_record(duration_s=None, iterations=None, cost_usd=None)])
    assert rows[0]['durationText'] == DASH
    assert rows[0]['iterations'] == DASH
    assert rows[0]['costText'] == DASH
    assert rows[0]['verdict'] == 'COMPLETE'


def test_missing_optional_fields_become_null_not_a_crash():
    rows = _value('rowsOf', records=[{'run_id': 'r9', 'verdict': 'RUNNING'}])
    assert rows == [{'runId': 'r9', 'repo': None, 'verdict': 'RUNNING', 'durationText': DASH, 'iterations': DASH,
                     'costText': DASH, 'startedAt': None, 'tone': 'run'}]


@pytest.mark.parametrize('seconds, text', [
    (0, '0s'), (5, '5s'), (59, '59s'), (59.4, '59s'), (60, '1m 0s'), (125, '2m 5s'), (125.6, '2m 6s'),
    (3599, '59m 59s'), (3600, '1h 0m'), (3725, '1h 2m'), (7322.4, '2h 2m'), (59.6, '1m 0s'),
])
def test_duration_text_uses_seconds_minutes_or_hours(seconds, text):
    assert _value('rowsOf', records=[_record(duration_s=seconds)])[0]['durationText'] == text


@pytest.mark.parametrize('seconds', [-1, '60', True])
def test_a_negative_or_non_numeric_duration_is_unmeasured(seconds):
    assert _value('rowsOf', records=[_record(duration_s=seconds)])[0]['durationText'] == DASH


@pytest.mark.parametrize('usd, text', [(0, 'US$ 0.00'), (0.75, 'US$ 0.75'), (2, 'US$ 2.00'),
                                       (12.3456, 'US$ 12.35'), (0.1, 'US$ 0.10')])
def test_cost_text_has_two_decimals_with_a_dot(usd, text):
    assert _value('rowsOf', records=[_record(cost_usd=usd)])[0]['costText'] == text


@pytest.mark.parametrize('verdict, tone', [
    ('COMPLETE', 'pass'),
    ('BLOCKED', 'fail'), ('INFRASTRUCTURE_FAILURE', 'fail'), ('INVALID_RECEIPT', 'fail'),
    ('PARTIAL', 'warn'), ('CANCELLED', 'warn'),
    ('RUNNING', 'run'),
    ('UNKNOWN', 'idle'), (None, 'idle'), ('SOMETHING_NEW', 'idle'), ('constructor', 'idle'),
])
def test_the_verdict_maps_to_its_tone(verdict, tone):
    assert _value('rowsOf', records=[_record(verdict=verdict)])[0]['tone'] == tone


def test_rows_keep_the_input_order():
    rows = _value('rowsOf', records=[_record('c'), _record('a'), _record('b')])
    assert [row['runId'] for row in rows] == ['c', 'a', 'b']


def test_entries_that_are_not_records_are_skipped():
    rows = _value('rowsOf', records=[None, 5, 'x', [1, 2], _record('ok')])
    assert [row['runId'] for row in rows] == ['ok']


# ---------- heatLevels ----------

def test_an_all_zero_grid_gives_seven_by_twenty_four_zeros():
    assert _value('heatLevels', grid=_grid()) == _grid()


def test_levels_are_zero_or_the_ceiling_of_four_times_count_over_the_max():
    grid = _grid({(0, 0): 8, (0, 1): 1, (0, 2): 2, (0, 3): 3, (0, 4): 5, (0, 5): 7, (0, 6): 8, (0, 7): 0})
    assert _value('heatLevels', grid=grid)[0][:8] == [4, 1, 1, 2, 3, 4, 4, 0]


def test_the_maximum_cell_is_level_four_and_a_single_run_is_level_four():
    assert _value('heatLevels', grid=_grid({(3, 9): 1}))[3][9] == 4
    assert _value('heatLevels', grid=_grid({(6, 23): 40}))[6][23] == 4


def test_a_zero_cell_stays_zero_even_when_the_others_are_large():
    levels = _value('heatLevels', grid=_grid({(1, 1): 100, (1, 2): 0}))
    assert levels[1][1] == 4 and levels[1][2] == 0


def test_the_output_is_seven_rows_of_twenty_four_ints_in_zero_to_four():
    grid = [[(day * 24 + hour) % 13 for hour in range(24)] for day in range(7)]
    levels = _value('heatLevels', grid=grid)
    assert len(levels) == 7 and all(len(row) == 24 for row in levels)
    assert all(isinstance(v, int) and 0 <= v <= 4 for row in levels for v in row)


def test_the_levels_match_the_formula_over_a_mixed_grid():
    grid = [[(day * 5 + hour * 3) % 11 for hour in range(24)] for day in range(7)]
    assert _value('heatLevels', grid=grid) == _expected_levels(grid)


@pytest.mark.parametrize('grid', [None, 'abc', []])
def test_a_missing_grid_is_read_as_zeros_and_keeps_the_shape(grid):
    levels = _value('heatLevels', grid=grid)
    assert len(levels) == 7 and all(len(row) == 24 for row in levels)
    assert all(v == 0 for row in levels for v in row)


def test_a_short_grid_pads_the_missing_rows_and_cells_with_zero():
    levels = _value('heatLevels', grid=[[0] * 24, [0] * 24, [0] * 23 + [2]])
    assert len(levels) == 7 and levels[2][23] == 4 and levels[6] == [0] * 24


def test_a_non_numeric_cell_counts_as_zero():
    grid = _grid({(0, 0): 4})
    grid[0][1] = 'x'
    levels = _value('heatLevels', grid=grid)
    assert levels[0][0] == 4 and levels[0][1] == 0


# ---------- trendSeries ----------

TRENDS = [
    {'bucket': '2026-09-07', 'runs': 4, 'complete_rate': 0.5, 'iterations_per_task': 2.5, 'cost_per_task_usd': 0.1},
    {'bucket': '2026-09-14', 'runs': 2, 'complete_rate': 1.0, 'iterations_per_task': None, 'cost_per_task_usd': 0.25},
]


@pytest.mark.parametrize('key, values', [
    ('complete_rate', [0.5, 1.0]),
    ('iterations_per_task', [2.5, None]),
    ('cost_per_task_usd', [0.1, 0.25]),
])
def test_a_trend_series_has_the_buckets_as_labels_and_the_values_in_order(key, values):
    assert _value('trendSeries', trends=TRENDS, key=key) == {'labels': ['2026-09-07', '2026-09-14'],
                                                             'values': values}


def test_a_missing_or_non_numeric_value_is_null():
    trends = [{'bucket': 'b1'}, {'bucket': 'b2', 'complete_rate': '0.5'}]
    assert _value('trendSeries', trends=trends, key='complete_rate') == {'labels': ['b1', 'b2'],
                                                                         'values': [None, None]}


@pytest.mark.parametrize('trends', [None, [], 'abc', {}])
def test_no_usable_trends_give_empty_labels_and_values(trends):
    assert _value('trendSeries', trends=trends, key='complete_rate') == {'labels': [], 'values': []}


@pytest.mark.parametrize('key', ['runs', 'bucket', 'not_complete_rate', '', 'constructor', None])
def test_a_key_outside_the_three_trend_keys_is_rejected(key):
    assert _error('trendSeries', trends=TRENDS, key=key).startswith('RangeError')


def test_the_three_trend_keys_are_accepted():
    for key in TREND_KEYS:
        assert 'error' not in _run('trendSeries', trends=TRENDS, key=key)


# ---------- deltaText ----------

@pytest.mark.parametrize('delta, text', [
    (-30, MINUS + '30 s'), (2, '+2 s'), (0, '0 s'), (0.4, '0 s'), (-0.4, '0 s'), (2.6, '+3 s'), (-2.4, MINUS + '2 s'),
    (120, '+120 s'),
])
def test_seconds_deltas_are_signed_with_the_unit(delta, text):
    assert _value('deltaText', metric={'a': 10, 'b': 10 + delta, 'delta': delta}, kind='seconds') == text


@pytest.mark.parametrize('delta, text', [(2, '+2'), (-1, MINUS + '1'), (0, '0'), (10, '+10')])
def test_count_deltas_are_signed_without_a_unit(delta, text):
    assert _value('deltaText', metric={'delta': delta}, kind='count') == text


@pytest.mark.parametrize('delta, text', [
    (0.2, '+US$ 0.20'), (-0.3, MINUS + 'US$ 0.30'), (0, 'US$ 0.00'), (0.004, 'US$ 0.00'),
    (-0.004, 'US$ 0.00'), (1.5, '+US$ 1.50'),
])
def test_usd_deltas_are_signed_with_two_decimals(delta, text):
    assert _value('deltaText', metric={'delta': delta}, kind='usd') == text


@pytest.mark.parametrize('kind', ['seconds', 'count', 'usd'])
def test_a_null_or_missing_delta_is_a_dash(kind):
    assert _value('deltaText', metric={'a': None, 'b': 3, 'delta': None}, kind=kind) == DASH
    assert _value('deltaText', metric={'a': 1, 'b': 2}, kind=kind) == DASH
    assert _value('deltaText', metric=None, kind=kind) == DASH


def test_a_non_numeric_delta_is_a_dash():
    assert _value('deltaText', metric={'delta': 'x'}, kind='count') == DASH


def test_a_negative_delta_uses_the_real_minus_sign_and_no_hyphen():
    for kind in ('seconds', 'count', 'usd'):
        text = _value('deltaText', metric={'delta': -5}, kind=kind)
        assert MINUS in text and '-' not in text


@pytest.mark.parametrize('kind', ['minutes', '', None, 'SECONDS'])
def test_an_unknown_kind_is_rejected(kind):
    assert _error('deltaText', metric={'delta': 1}, kind=kind).startswith('RangeError')


# ---------- phaseBars ----------

COMPARE = {'phases': {'intake': {'a_s': 10, 'b_s': 20, 'delta_s': 10},
                      'executing': {'a_s': 40, 'b_s': 30, 'delta_s': -10}}}


def test_phase_bars_are_percent_of_the_largest_value_in_order():
    assert _value('phaseBars', compare=COMPARE) == [
        {'phase': 'intake', 'aPct': 25, 'bPct': 50, 'aS': 10, 'bS': 20},
        {'phase': 'executing', 'aPct': 100, 'bPct': 75, 'aS': 40, 'bS': 30},
    ]


def test_the_delta_is_not_used_for_the_bars():
    compare = {'phases': {'intake': {'a_s': 10, 'b_s': 20, 'delta_s': 999}}}
    assert _value('phaseBars', compare=compare) == [
        {'phase': 'intake', 'aPct': 50, 'bPct': 100, 'aS': 10, 'bS': 20}]


def test_a_phase_missing_in_one_run_has_a_null_percent_on_that_side():
    compare = {'phases': {'plan': {'a_s': None, 'b_s': 30, 'delta_s': None},
                          'exec': {'a_s': 60, 'b_s': 15, 'delta_s': -45}}}
    assert _value('phaseBars', compare=compare) == [
        {'phase': 'plan', 'aPct': None, 'bPct': 50, 'aS': None, 'bS': 30},
        {'phase': 'exec', 'aPct': 100, 'bPct': 25, 'aS': 60, 'bS': 15},
    ]


def test_a_zero_maximum_gives_zero_percents_and_null_stays_null():
    assert _value('phaseBars', compare={'phases': {'x': {'a_s': 0, 'b_s': 0}}}) == [
        {'phase': 'x', 'aPct': 0, 'bPct': 0, 'aS': 0, 'bS': 0}]
    assert _value('phaseBars', compare={'phases': {'x': {'a_s': None, 'b_s': 0}}}) == [
        {'phase': 'x', 'aPct': None, 'bPct': 0, 'aS': None, 'bS': 0}]


def test_a_phase_with_no_measure_on_either_side_is_all_null():
    assert _value('phaseBars', compare={'phases': {'x': {'a_s': None, 'b_s': None}}}) == [
        {'phase': 'x', 'aPct': None, 'bPct': None, 'aS': None, 'bS': None}]


def test_a_negative_seconds_value_is_unmeasured():
    assert _value('phaseBars', compare={'phases': {'x': {'a_s': -5, 'b_s': 10}}}) == [
        {'phase': 'x', 'aPct': None, 'bPct': 100, 'aS': None, 'bS': 10}]


@pytest.mark.parametrize('compare', [None, {}, {'phases': {}}, {'phases': None}, {'phases': []}, 'abc'])
def test_no_phases_gives_no_bars(compare):
    assert _value('phaseBars', compare=compare) == []


def test_the_bars_keep_the_phase_order_and_carry_exactly_the_documented_keys():
    names = ['z_plan', 'a_exec', 'm_done']
    compare = {'phases': {name: {'a_s': index + 1, 'b_s': 2} for index, name in enumerate(names)}}
    bars = _value('phaseBars', compare=compare)
    assert [bar['phase'] for bar in bars] == names
    assert all(set(bar) == {'phase', 'aPct', 'bPct', 'aS', 'bS'} for bar in bars)


def test_every_percent_is_within_zero_and_one_hundred_and_the_maximum_is_one_hundred():
    compare = {'phases': {'p%d' % i: {'a_s': (i * 7) % 13 + 0.5, 'b_s': (i * 5) % 9} for i in range(10)}}
    bars = _value('phaseBars', compare=compare)
    pcts = [v for bar in bars for v in (bar['aPct'], bar['bPct']) if v is not None]
    assert all(0 <= v <= 100 for v in pcts)
    assert max(pcts) == 100
