'''Unit tests for simplicio_loop.dashboard.trends: comparison, trends, heatmap and export (#1408).

The 30-run fixture is synthetic and deterministic; every expected number below is recomputed here
by a plain loop that shares no code with the module.
'''
import csv
import io
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

START = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)  # a Monday
VERDICTS = ['COMPLETE', 'COMPLETE', 'BLOCKED', 'PARTIAL', 'COMPLETE']
CAUSES = ['gate-fail', 'no-evidence', 'gate-fail']


def _trends():
    from simplicio_loop.dashboard import trends
    return trends


def _fixture(n=30):
    rows = []
    for i in range(n):
        started = START + timedelta(days=i, hours=i % 7)
        verdict = VERDICTS[i % 5]
        rows.append({
            'schema': 'simplicio.dashboard-history/v1', 'run_id': 'run-%02d' % i, 'repo': '/r', 'verdict': verdict,
            'status': 'done', 'phase': 'done', 'started_at': started.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'finished_at': None, 'duration_s': 300 + 10 * i, 'iterations': 1 + i % 4, 'stalls': i % 3,
            'stall_causes': [CAUSES[i % 3]] if i % 3 else [], 'tests': {'passed': 10 + i, 'failed': i % 2},
            'tasks_verified': 1 + i % 3 if verdict == 'COMPLETE' else 0,
            'tokens': 1000 * (i + 1), 'cost_usd': None if i % 10 == 9 else 0.5 + i / 10,
            'phase_durations_s': {'mapping': 60, 'executing': 200 + i} if verdict != 'BLOCKED' else {'mapping': 60},
        })
    return rows


def _week_start(ts):
    day = datetime.strptime(ts, '%Y-%m-%dT%H:%M:%SZ')
    return (day - timedelta(days=day.weekday())).strftime('%Y-%m-%d')


def test_weekly_trends_match_reference_calculation():
    rows = _fixture()
    got = {b['bucket']: b for b in _trends().trends(rows, 'week')}
    groups = {}
    for r in rows:
        groups.setdefault(_week_start(r['started_at']), []).append(r)
    assert set(got) == set(groups)
    for key, grp in groups.items():
        b = got[key]
        done = [r for r in grp if r['verdict'] == 'COMPLETE']
        assert b['runs'] == len(grp)
        assert b['complete_rate'] == pytest.approx(len(done) / len(grp))
        assert b['not_complete_rate'] == pytest.approx(1 - len(done) / len(grp))
        for phase in ('mapping', 'executing'):
            vals = [r['phase_durations_s'][phase] for r in grp if phase in r['phase_durations_s']]
            assert b['avg_phase_s'][phase] == pytest.approx(sum(vals) / len(vals))
        tasks = sum(r['tasks_verified'] for r in grp)
        iters = sum(r['iterations'] for r in grp if r['tasks_verified'])
        assert b['iterations_per_task'] == (pytest.approx(iters / tasks) if tasks else None)
        cost = sum(r['cost_usd'] for r in done if r['cost_usd'] is not None)
        measured = any(r['cost_usd'] is not None for r in done)
        assert b['cost_per_task_usd'] == (pytest.approx(cost / tasks) if tasks and measured else None)
        causes = Counter(c for r in grp for c in r['stall_causes'])
        assert b['top_stall_causes'] == [[c, n] for c, n in sorted(causes.items(), key=lambda kv: (-kv[1], kv[0]))][:5]


def test_monthly_buckets_and_bad_bucket():
    t = _trends()
    months = {b['bucket']: b['runs'] for b in t.trends(_fixture(), 'month')}
    assert months == {'2026-09': 24, '2026-10': 6}
    with pytest.raises(ValueError):
        t.trends(_fixture(), 'year')


def test_heatmap_counts_weekday_by_hour():
    rows = _fixture()
    grid = _trends().heatmap(rows)
    assert len(grid) == 7 and all(len(day) == 24 for day in grid)
    expected = Counter()
    for r in rows:
        d = datetime.strptime(r['started_at'], '%Y-%m-%dT%H:%M:%SZ')
        expected[(d.weekday(), d.hour)] += 1
    for day in range(7):
        for hour in range(24):
            assert grid[day][hour] == expected[(day, hour)]
    assert sum(map(sum, grid)) == 30


def test_compare_blocked_against_done_with_different_phases():
    rows = {r['run_id']: r for r in _fixture()}
    done, blocked = rows['run-00'], rows['run-02']
    cmp = _trends().compare(done, blocked)
    assert cmp['verdicts'] == {'a': 'COMPLETE', 'b': 'BLOCKED'}
    assert cmp['phases']['mapping'] == {'a_s': 60, 'b_s': 60, 'delta_s': 0}
    assert cmp['phases']['executing'] == {'a_s': 200, 'b_s': None, 'delta_s': None}
    assert cmp['only_in'] == {'a': ['executing'], 'b': []}
    assert cmp['metrics']['iterations'] == {'a': 1, 'b': 3, 'delta': 2}
    assert cmp['metrics']['tests_passed'] == {'a': 10, 'b': 12, 'delta': 2}
    assert cmp['metrics']['tokens'] == {'a': 1000, 'b': 3000, 'delta': 2000}
    assert cmp['metrics']['cost_usd']['delta'] == pytest.approx(0.2)
    assert cmp['comparable'] is False


def test_compare_unmeasured_values_stay_none():
    rows = {r['run_id']: r for r in _fixture()}
    cmp = _trends().compare(rows['run-09'], rows['run-00'])
    assert cmp['metrics']['cost_usd'] == {'a': None, 'b': 0.5, 'delta': None}
    assert cmp['comparable'] is True


def test_csv_export_round_trips_and_neutralises_formulas():
    rows = _fixture(3)
    rows[0]['repo'] = '=cmd|calc'
    text = _trends().to_csv(rows)
    parsed = list(csv.DictReader(io.StringIO(text)))
    assert [r['run_id'] for r in parsed] == ['run-00', 'run-01', 'run-02']
    assert parsed[0]['repo'] == "'=cmd|calc"
    assert parsed[0]['cost_usd'] == '0.5' and json.loads(parsed[0]['phase_durations_s']) == rows[0]['phase_durations_s']
