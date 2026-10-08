'''Unit tests for simplicio_loop.dashboard.history, the past-run reader (#1408).'''
import json

import pytest


def _history():
    from simplicio_loop.dashboard import history
    return history


def _ev(seq, kind, ts, phase=None, iteration=None, **payload):
    return {'seq': seq, 'kind': kind, 'ts': ts, 'phase': phase, 'iteration': iteration, 'payload': payload}


def _run(root, run_id, status='done', started='2026-10-01T10:00:00Z', finished='2026-10-01T10:10:00Z',
         outcome=None, events=(), repo=None):
    run_dir = root / '.simplicio-loop' / 'loop-runs' / run_id
    run_dir.mkdir(parents=True)
    state = {'run_id': run_id, 'status': status, 'phase': status, 'repo': repo or str(root),
             'started_at': started, 'updated_at': finished}
    if finished and status != 'running':
        state['finished_at'] = finished
    (run_dir / 'state.json').write_text(json.dumps(state), encoding='utf-8')
    if outcome:
        (run_dir / 'run-outcome.json').write_text(json.dumps({'schema': 'simplicio.run-outcome/v1', 'outcome': outcome}), encoding='utf-8')
    if events:
        (run_dir / 'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events) + '\n', encoding='utf-8')
    return run_dir


def test_record_carries_outcome_timing_and_event_aggregates(tmp_path):
    _run(tmp_path, 'r1', outcome='COMPLETE', events=[
        _ev(1, 'phase_entered', '2026-10-01T10:00:00.000Z', phase='mapping'),
        _ev(2, 'phase_entered', '2026-10-01T10:02:00.000Z', phase='executing'),
        _ev(3, 'iteration_started', '2026-10-01T10:02:00.000Z', iteration=1),
        _ev(4, 'stall_detected', '2026-10-01T10:03:00.000Z', iteration=1, streak=2),
        _ev(5, 'iteration_started', '2026-10-01T10:04:00.000Z', iteration=2),
        _ev(6, 'token_usage', '2026-10-01T10:05:00.000Z', model='m', input_tokens=100, output_tokens=40),
        _ev(7, 'token_usage', '2026-10-01T10:06:00.000Z', model='m', input_tokens=10, output_tokens=5),
        _ev(8, 'cost_sample', '2026-10-01T10:06:00.000Z', model='m', usd=0.25),
        _ev(9, 'cost_sample', '2026-10-01T10:07:00.000Z', model='m', usd=0.5),
        _ev(10, 'phase_entered', '2026-10-01T10:08:00.000Z', phase='validating'),
    ])
    [rec] = _history().read_history(tmp_path)
    assert rec['schema'] == 'simplicio.dashboard-history/v1'
    assert rec['run_id'] == 'r1' and rec['verdict'] == 'COMPLETE'
    assert rec['duration_s'] == 600 and rec['iterations'] == 2 and rec['stalls'] == 1
    assert rec['tokens'] == 155 and rec['cost_usd'] == pytest.approx(0.75)
    assert rec['phase_durations_s'] == {'mapping': 120, 'executing': 360, 'validating': 120}


def test_missing_events_and_outcome_degrade_to_none_never_zero(tmp_path):
    _run(tmp_path, 'bare', status='blocked')
    _run(tmp_path, 'live', status='running', finished=None)
    by_id = {r['run_id']: r for r in _history().read_history(tmp_path)}
    assert by_id['bare']['verdict'] == 'UNKNOWN' and by_id['live']['verdict'] == 'RUNNING'
    for rec in by_id.values():
        assert rec['iterations'] is None and rec['tokens'] is None and rec['cost_usd'] is None
        assert rec['phase_durations_s'] == {}


def test_filters_and_order(tmp_path):
    _run(tmp_path, 'a', outcome='COMPLETE', started='2026-09-01T10:00:00Z', finished='2026-09-01T10:01:00Z',
         events=[_ev(1, 'iteration_started', '2026-09-01T10:00:01.000Z', iteration=1),
                 _ev(2, 'cost_sample', '2026-09-01T10:00:02.000Z', usd=1.0)])
    _run(tmp_path, 'b', outcome='BLOCKED', started='2026-10-01T10:00:00Z', finished='2026-10-01T11:00:00Z',
         events=[_ev(1, 'iteration_started', '2026-10-01T10:00:01.000Z', iteration=1),
                 _ev(2, 'iteration_started', '2026-10-01T10:30:00.000Z', iteration=2),
                 _ev(3, 'iteration_started', '2026-10-01T10:40:00.000Z', iteration=3),
                 _ev(4, 'cost_sample', '2026-10-01T10:40:01.000Z', usd=5.0)], repo='/other')
    h = _history()

    def ids(**kw):
        return [r['run_id'] for r in h.read_history(tmp_path, **kw)]

    assert ids() == ['b', 'a']
    assert ids(verdict='COMPLETE') == ['a']
    assert ids(min_duration_s=120) == ['b'] and ids(max_duration_s=120) == ['a']
    assert ids(min_iterations=2) == ['b'] and ids(max_iterations=1) == ['a']
    assert ids(min_cost_usd=2) == ['b'] and ids(max_cost_usd=2) == ['a']
    assert ids(repo='/other') == ['b']
    assert ids(since='2026-09-15T00:00:00Z') == ['b'] and ids(until='2026-09-15T00:00:00Z') == ['a']
    assert ids(limit=1) == ['b']


def test_bad_filter_values_raise(tmp_path):
    h = _history()
    with pytest.raises(ValueError):
        h.read_history(tmp_path, since='yesterday')
    with pytest.raises(ValueError):
        h.read_history(tmp_path, verdict='NOPE')


def test_record_carries_tests_stall_causes_and_verified_tasks(tmp_path):
    run_dir = _run(tmp_path, 'r2', outcome='COMPLETE', events=[
        _ev(1, 'test_result', '2026-10-01T10:01:00.000Z', passed=8, failed=1, skipped=0, command='pytest'),
        _ev(2, 'test_result', '2026-10-01T10:02:00.000Z', passed=9, failed=0, skipped=0, command='pytest'),
        _ev(3, 'stall_detected', '2026-10-01T10:03:00.000Z', blocker='gate-fail', streak=1),
        _ev(4, 'stall_detected', '2026-10-01T10:04:00.000Z', fingerprint='abc', streak=2),
        _ev(5, 'stall_detected', '2026-10-01T10:05:00.000Z', streak=3),
    ])
    [rec] = _history().read_history(tmp_path)
    assert rec['tests'] == {'passed': 17, 'failed': 1}
    assert rec['stall_causes'] == ['gate-fail', 'abc', 'unknown'] and rec['stalls'] == 3
    assert rec['tasks_verified'] == 0
    bare = _run(tmp_path, 'r3')
    assert next(r for r in _history().read_history(tmp_path) if r['run_id'] == 'r3')['tests'] is None


def test_thirty_run_directories_feed_trends_end_to_end(tmp_path):
    from simplicio_loop.dashboard import trends
    verdicts = ['COMPLETE', 'BLOCKED', 'COMPLETE', 'PARTIAL', 'COMPLETE']
    for i in range(30):
        day = 1 + i
        _run(tmp_path, 'r%02d' % i, outcome=verdicts[i % 5], started='2026-09-%02dT10:00:00Z' % day,
             finished='2026-09-%02dT10:30:00Z' % day,
             events=[_ev(1, 'iteration_started', '2026-09-%02dT10:00:01.000Z' % day, iteration=1)])
    records = _history().read_history(tmp_path)
    assert len(records) == 30
    [month] = trends.trends(records, 'month')
    assert month['runs'] == 30 and month['complete_rate'] == pytest.approx(18 / 30)
    assert sum(map(sum, trends.heatmap(records))) == 30
