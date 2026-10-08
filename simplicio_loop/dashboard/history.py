'''Past-run reader for the Simplicio Live dashboard (#1408).

Read-only. One record per run under the watched repos: the ``run-outcome/v1`` verdict plus timing and
the aggregates the history list, comparison and trends need (iterations, stalls, tokens, cost,
per-phase seconds). The aggregates come from one streamed pass over ``events.jsonl``; a value no
producer has measured is None, never 0.
'''
from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from simplicio_loop.dashboard import runs

SCHEMA = 'simplicio.dashboard-history/v1'
VERDICTS = frozenset({'COMPLETE', 'BLOCKED', 'CANCELLED', 'PARTIAL', 'INVALID_RECEIPT',
                      'INFRASTRUCTURE_FAILURE', 'RUNNING', 'UNKNOWN'})
_TERMINAL = frozenset({'done', 'partial', 'blocked', 'cancelled', 'failed'})


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _verdict(run_dir: Path, status: str) -> str:
    data = runs._read_json(run_dir / 'run-outcome.json')
    outcome = data.get('outcome') if isinstance(data, dict) else None
    if isinstance(outcome, str) and outcome in VERDICTS:
        return outcome
    return 'UNKNOWN' if status in _TERMINAL else 'RUNNING'


def _scan_events(run_dir: Path, end: Any) -> dict[str, Any]:
    '''Aggregates from events.jsonl, streamed line by line. ``end`` closes the last open phase.'''
    iterations: set[int] = set()
    stalls = 0
    causes: list[str] = []
    tests: dict[str, int] | None = None
    tokens: int | None = None
    cost: float | None = None
    spans: list[tuple[str, Any]] = []
    try:
        with (run_dir / 'events.jsonl').open('r', encoding='utf-8', errors='replace') as fh:
            for line in fh:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                kind = event.get('kind')
                payload = event.get('payload') if isinstance(event.get('payload'), dict) else {}
                n = event.get('iteration')
                if kind == 'iteration_started' and isinstance(n, int) and not isinstance(n, bool):
                    iterations.add(n)
                elif kind == 'stall_detected':
                    stalls += 1
                    causes.append(str(payload.get('blocker') or payload.get('fingerprint') or 'unknown'))
                elif kind == 'test_result':
                    tests = tests or {'passed': 0, 'failed': 0}
                    for key in ('passed', 'failed'):
                        tests[key] += int(_num(payload.get(key)) or 0)
                elif kind == 'token_usage':
                    parts = [_num(payload.get('input_tokens')), _num(payload.get('output_tokens'))]
                    tokens = (tokens or 0) + int(sum(p for p in parts if p is not None))
                elif kind == 'cost_sample' and _num(payload.get('usd')) is not None:
                    cost = (cost or 0.0) + float(payload['usd'])
                elif kind == 'phase_entered' and isinstance(event.get('phase'), str):
                    ts = runs._parse_ts(event.get('ts'))
                    if ts is not None:
                        spans.append((event['phase'], ts))
    except OSError:
        pass
    durations: dict[str, int] = {}
    closing = runs._parse_ts(end)
    for i, (phase, start) in enumerate(spans):
        stop = spans[i + 1][1] if i + 1 < len(spans) else closing
        if stop is not None and stop >= start:
            durations[phase] = durations.get(phase, 0) + int((stop - start).total_seconds())
    return {'iterations': len(iterations) or None, 'stalls': stalls, 'stall_causes': causes,
            'tests': tests, 'tokens': tokens,
            'cost_usd': cost, 'phase_durations_s': durations}


def history_record(ref: runs.RunRef) -> dict[str, Any]:
    '''The history record of one run.'''
    run_dir = Path(ref['run_dir'])
    summary = runs.run_summary(ref)
    scanned = _scan_events(run_dir, summary.get('finished_at') or summary.get('updated_at'))
    return {
        'schema': SCHEMA, 'run_id': summary['run_id'], 'repo': summary['repo'],
        'verdict': _verdict(run_dir, summary['status']), 'status': summary['status'],
        'phase': summary.get('phase'), 'started_at': summary.get('started_at'),
        'finished_at': summary.get('finished_at'), 'duration_s': summary.get('duration_s'),
        'tasks_verified': (summary.get('tasks') or {}).get('verified', 0),
        **scanned,
    }


def _within(value: float | None, low: float | None, high: float | None) -> bool:
    if low is None and high is None:
        return True
    if value is None:
        return False
    return (low is None or value >= low) and (high is None or value <= high)


def read_history(repos: str | os.PathLike | Iterable[str | os.PathLike], *, verdict: str | None = None,
                 repo: str | None = None, since: str | None = None, until: str | None = None,
                 min_duration_s: float | None = None, max_duration_s: float | None = None,
                 min_iterations: float | None = None, max_iterations: float | None = None,
                 min_cost_usd: float | None = None, max_cost_usd: float | None = None,
                 limit: int | None = None) -> list[dict[str, Any]]:
    '''Records of the past runs, newest ``started_at`` first. Every filter is optional.

    A run with no measured value for a filtered field (duration, iterations, cost) is excluded by
    that filter. ``since``/``until`` bound ``started_at`` (inclusive). ValueError on a bad filter.
    '''
    if verdict is not None and verdict not in VERDICTS:
        raise ValueError('verdict must be one of %s' % ', '.join(sorted(VERDICTS)))
    bounds = []
    for name, value in (('since', since), ('until', until)):
        parsed = runs._parse_ts(value) if value is not None else None
        if value is not None and parsed is None:
            raise ValueError('%s must be an ISO-8601 timestamp' % name)
        bounds.append(parsed)
    low_ts, high_ts = bounds
    rows = []
    for ref in runs.discover_runs(repos):
        rec = history_record(ref)
        started = runs._parse_ts(rec['started_at'])
        if verdict is not None and rec['verdict'] != verdict:
            continue
        if repo is not None and rec['repo'] != repo:
            continue
        if (low_ts or high_ts) and started is None:
            continue
        if (low_ts and started < low_ts) or (high_ts and started > high_ts):
            continue
        if not (_within(rec['duration_s'], min_duration_s, max_duration_s)
                and _within(rec['iterations'], min_iterations, max_iterations)
                and _within(rec['cost_usd'], min_cost_usd, max_cost_usd)):
            continue
        rows.append(rec)
    rows.sort(key=lambda r: (runs._parse_ts(r['started_at']) or runs._EPOCH, r['run_id']), reverse=True)
    return rows[:limit] if limit is not None else rows
