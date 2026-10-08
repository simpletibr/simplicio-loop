'''Comparison, trends, heatmap and CSV export over history records (#1408).

Pure functions over the records ``history.read_history`` returns. A value the records do not carry
is None, never 0; an average skips the runs that lack the value.
'''
from __future__ import annotations

import csv
import io
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Any

from simplicio_loop.dashboard import runs

BUCKETS = ('week', 'month')
TOP_CAUSES = 5
CSV_COLUMNS = ('run_id', 'repo', 'verdict', 'status', 'phase', 'started_at', 'finished_at', 'duration_s',
               'iterations', 'stalls', 'tasks_verified', 'tests_passed', 'tests_failed', 'tokens', 'cost_usd',
               'phase_durations_s', 'stall_causes')


def _bucket(started_at: Any, kind: str) -> str | None:
    ts = runs._parse_ts(started_at)
    if ts is None:
        return None
    if kind == 'month':
        return ts.strftime('%Y-%m')
    return (ts - timedelta(days=ts.weekday())).strftime('%Y-%m-%d')  # Monday of the ISO week, UTC


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _summarise(group: list[Mapping[str, Any]], bucket: str) -> dict[str, Any]:
    complete = [r for r in group if r.get('verdict') == 'COMPLETE']
    phases: dict[str, list[float]] = {}
    for rec in group:
        for phase, seconds in (rec.get('phase_durations_s') or {}).items():
            phases.setdefault(phase, []).append(seconds)
    tasks = sum(r.get('tasks_verified') or 0 for r in group)
    iterations = [r['iterations'] for r in group if r.get('tasks_verified') and r.get('iterations') is not None]
    costs = [r['cost_usd'] for r in complete if r.get('cost_usd') is not None]
    causes = Counter(c for r in group for c in (r.get('stall_causes') or []))
    return {
        'bucket': bucket, 'runs': len(group),
        'complete_rate': len(complete) / len(group),
        'not_complete_rate': 1 - len(complete) / len(group),
        'avg_phase_s': {p: _mean(v) for p, v in sorted(phases.items())},
        'iterations_per_task': sum(iterations) / tasks if tasks and iterations else None,
        'cost_per_task_usd': sum(costs) / tasks if tasks and costs else None,
        'top_stall_causes': [[c, n] for c, n in sorted(causes.items(), key=lambda kv: (-kv[1], kv[0]))][:TOP_CAUSES],
    }


def trends(records: Iterable[Mapping[str, Any]], bucket: str = 'week') -> list[dict[str, Any]]:
    '''One summary per week or month of ``started_at``, oldest first. ValueError on another bucket.

    ``complete_rate`` is the share of ``COMPLETE`` verdicts; ``iterations_per_task`` is iterations
    over verified tasks among runs that verified any; ``cost_per_task_usd`` is the measured cost of
    ``COMPLETE`` runs over all verified tasks in the bucket.
    '''
    if bucket not in BUCKETS:
        raise ValueError('bucket must be one of %s' % ', '.join(BUCKETS))
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for rec in records:
        key = _bucket(rec.get('started_at'), bucket)
        if key is not None:
            groups.setdefault(key, []).append(rec)
    return [_summarise(groups[key], key) for key in sorted(groups)]


def heatmap(records: Iterable[Mapping[str, Any]]) -> list[list[int]]:
    '''Run starts as a 7 x 24 grid: weekday (Monday = 0) by hour, UTC.'''
    grid = [[0] * 24 for _ in range(7)]
    for rec in records:
        ts = runs._parse_ts(rec.get('started_at'))
        if ts is not None:
            grid[ts.weekday()][ts.hour] += 1
    return grid


def _delta(a: Any, b: Any) -> Any:
    return b - a if a is not None and b is not None else None


def _metric(a: Any, b: Any) -> dict[str, Any]:
    return {'a': a, 'b': b, 'delta': _delta(a, b)}


def _test_count(rec: Mapping[str, Any], key: str) -> int | None:
    tests = rec.get('tests')
    return tests.get(key) if isinstance(tests, Mapping) else None


def compare(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    '''Side-by-side of two history records; ``delta`` is b minus a.

    Runs may stop in different phases (a blocked run has no later phases): a phase present in one
    run only has None for the other and is listed under ``only_in``; ``comparable`` is False then.
    '''
    pa, pb = a.get('phase_durations_s') or {}, b.get('phase_durations_s') or {}
    names = list(pa) + [p for p in pb if p not in pa]
    phases = {p: {'a_s': pa.get(p), 'b_s': pb.get(p), 'delta_s': _delta(pa.get(p), pb.get(p))} for p in names}
    metrics = {
        'duration_s': _metric(a.get('duration_s'), b.get('duration_s')),
        'iterations': _metric(a.get('iterations'), b.get('iterations')),
        'stalls': _metric(a.get('stalls'), b.get('stalls')),
        'tests_passed': _metric(_test_count(a, 'passed'), _test_count(b, 'passed')),
        'tests_failed': _metric(_test_count(a, 'failed'), _test_count(b, 'failed')),
        'tokens': _metric(a.get('tokens'), b.get('tokens')),
        'cost_usd': _metric(a.get('cost_usd'), b.get('cost_usd')),
    }
    only_a, only_b = [p for p in pa if p not in pb], [p for p in pb if p not in pa]
    return {'a': a.get('run_id'), 'b': b.get('run_id'),
            'verdicts': {'a': a.get('verdict'), 'b': b.get('verdict')},
            'phases': phases, 'metrics': metrics, 'only_in': {'a': only_a, 'b': only_b},
            'comparable': not only_a and not only_b}


def _cell(value: Any) -> Any:
    '''CSV cell: a text starting with a formula character gets a leading quote; structures become JSON.'''
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, str) and value[:1] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + value
    return '' if value is None else value


def to_csv(records: Iterable[Mapping[str, Any]]) -> str:
    '''History records as CSV (header row first); spreadsheet formula injection is neutralised.'''
    out = io.StringIO()
    writer = csv.writer(out, lineterminator='\n')
    writer.writerow(CSV_COLUMNS)
    for rec in records:
        flat = dict(rec)
        flat['tests_passed'], flat['tests_failed'] = _test_count(rec, 'passed'), _test_count(rec, 'failed')
        writer.writerow([_cell(flat.get(col)) for col in CSV_COLUMNS])
    return out.getvalue()
