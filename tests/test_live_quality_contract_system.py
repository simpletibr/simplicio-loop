'''UI contract test for the Simplicio Live quality panel over a 5-iteration run.

The events are built and validated with scripts/dashboard_events.py and run through reducer.js in node by
tests/fixtures/live_pipeline/driver.mjs. The reducer output is checked against values computed here from the
event inputs (TESTS, LINT, COVERAGE, DIFFS), never copied from the reducer. Iteration 3's lint_result carries no
iteration: it must be attributed to the current iteration.
'''
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import dashboard_events as de
import pytest

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / 'tests' / 'fixtures' / 'live_pipeline' / 'driver.mjs'
RUN_ID = 'run-quality-contract'
BASE_MS = int(datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC).timestamp() * 1000)
NO_PRODUCER = 'sem produtor no fluxo atual'
NO_IDS = 'sem ids por teste: o produtor emite contagens, não identidade de teste'
COVERAGE_TARGET = 85
ITERATIONS = (1, 2, 3, 4, 5)
LINT_WITHOUT_ITERATION = 3

TESTS = {
    1: {'passed': 8, 'failed': 4, 'errors': 0, 'skipped': 1, 'total': 13, 'duration_s': 4.2},
    2: {'passed': 7, 'failed': 3, 'errors': 1, 'skipped': 1, 'total': 12, 'duration_s': 4.0},
    3: {'passed': 9, 'failed': 3, 'errors': 0, 'skipped': 0, 'total': 12, 'duration_s': 3.8},
    4: {'passed': 11, 'failed': 1, 'errors': 0, 'skipped': 1, 'total': 13, 'duration_s': 3.1},
    5: {'passed': 13, 'failed': 0, 'errors': 0, 'skipped': 1, 'total': 14, 'duration_s': 2.9},
}
LINT = {
    1: {'errors': 5, 'warnings': 2, 'by_rule': {'E501': 3, 'F401': 2}},
    2: {'errors': 4, 'warnings': 1, 'by_rule': {'E501': 2, 'F401': 1, 'B008': 1}},
    3: {'errors': 2, 'warnings': 1, 'by_rule': {'E501': 1, 'B008': 1}},
    4: {'errors': 2, 'warnings': 0, 'by_rule': {'B008': 1, 'S101': 1}},
    5: {'errors': 0, 'warnings': 0, 'by_rule': {}},
}
COVERAGE = {1: 78.0, 2: 80.5, 3: 83.0, 4: 86.2, 5: 90.1}
DIFFS = {
    1: [{'files': ['a.py', 'b.py', 'c.py'], 'files_total': 3, 'added': 40, 'deleted': 5}],
    2: [{'files': ['b.py', 'd.py'], 'files_total': 2, 'added': 25, 'deleted': 10}],
    3: [{'files': [], 'files_total': 0, 'added': 0, 'deleted': 0}],
    4: [{'files': ['a.py'], 'files_total': 1, 'added': 7, 'deleted': 30}],
    5: [{'files': ['g.py', 'h.py', 'a.py'], 'files_total': 3, 'added': 9, 'deleted': 2}],
}
# Failing test ids per iteration. FLIP fails in 2 and 4 and passes in 1, 3 and 5. Only iteration 3 has no code
# change, so only the 2->3 flip is flaky. The 3->4 and 4->5 flips land on iterations that changed code.
FLIP = 'tests/test_flow.py::test_flip'
FAILED_IDS = {1: [], 2: [FLIP], 3: [], 4: [FLIP], 5: []}
# An apply_result that is not a diff: it must not reach quality.diff.
NOT_A_DIFF = {'step': 'edit', 'files': ['zz.py'], 'files_total': 99, 'added': 1000, 'deleted': 1000}


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


def _run_node(args, stdin_text=''):
    proc = subprocess.run([_node()] + args, input=stdin_text, capture_output=True, text=True, timeout=120,
                          check=False)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _drive(steps):
    return _run_node([str(DRIVER)], json.dumps({'steps': steps}))


def _ts(offset_ms):
    moment = datetime.fromtimestamp((BASE_MS + offset_ms) / 1000, tz=UTC)
    return f"{moment.strftime('%Y-%m-%dT%H:%M:%S')}.{moment.microsecond // 1000:03d}Z"


def _event(seq, kind, iteration=None, payload=None):
    offset = seq * 1000
    evt = de.build_envelope(run_id=RUN_ID, kind=kind, source='hook', seq=seq, ts=_ts(offset),
                            iteration=iteration, payload=payload or {})
    assert de.validate_envelope(evt) == [], (kind, seq)
    return evt


def _now_of(evt):
    parsed = datetime.fromisoformat(evt['ts'].removesuffix('Z')).replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def _steps(events):
    return [{'action': {'type': 'event', 'event': evt}, 'now': _now_of(evt)} for evt in events]


def _run_events():
    events = []

    def add(kind, iteration=None, payload=None):
        events.append(_event(len(events) + 1, kind, iteration=iteration, payload=payload))

    for n in ITERATIONS:
        add('iteration_started', n, {'trigger': 'refeed'})
        add('test_result', n, dict(TESTS[n], failed_ids=FAILED_IDS[n]))
        add('lint_result', None if n == LINT_WITHOUT_ITERATION else n, dict(LINT[n]))
        add('coverage_result', n, {'percent': COVERAGE[n], 'scope': 'dashboard'})
        for diff in DIFFS[n]:
            add('apply_result', n, dict(diff, step='diff'))
        if n == ITERATIONS[-1]:
            add('apply_result', n, dict(NOT_A_DIFF))
        add('iteration_finished', n, {'outcome': 'pass' if n == ITERATIONS[-1] else 'refeed'})
    return events


@pytest.fixture(scope='module')
def run():
    events = _run_events()
    views = _drive(_steps(events))
    finish = {evt['iteration']: index for index, evt in enumerate(events) if evt['kind'] == 'iteration_finished'}
    return {'views': views, 'finish': finish}


def _quality_at(run_data, n):
    return run_data['views'][run_data['finish'][n]]['quality']


# ---- expected values, computed from the event inputs above

def _failing(n):
    return TESTS[n]['failed'] + TESTS[n]['errors']


def _lint_deltas(n):
    if n == 1:
        return None, None
    before, after = LINT[n - 1]['by_rule'], LINT[n]['by_rule']
    rules = set(before) | set(after)
    new = sum(max(0, after.get(rule, 0) - before.get(rule, 0)) for rule in rules)
    resolved = sum(max(0, before.get(rule, 0) - after.get(rule, 0)) for rule in rules)
    return new, resolved


def _diff_of(n):
    names, reported, added, deleted = set(), 0, 0, 0
    for entry in DIFFS[n]:
        names.update(entry['files'])
        reported = max(reported, entry['files_total'])
        added += entry['added']
        deleted += entry['deleted']
    # The file count of an iteration is the listed names, or the largest files_total when that is higher.
    return {'files': sorted(names), 'filesTotal': max(len(names), reported), 'added': added, 'deleted': deleted}


# ---- the panel at each iteration finish

def test_the_iterations_panel_keeps_five_rows(run):
    rows = run['views'][-1]['iterations']
    assert [row['iteration'] for row in rows] == list(ITERATIONS)


@pytest.mark.parametrize('n', ITERATIONS)
def test_tests_are_fail_until_the_last_iteration_then_pass(run, n):
    tests = _quality_at(run, n)['tests']
    expected_state = 'FAIL' if _failing(n) > 0 else 'PASS'
    assert tests['state'] == expected_state
    assert tests['iteration'] == n
    assert tests['counts'] == {key: TESTS[n][key] for key in ('passed', 'failed', 'skipped', 'errors', 'total')}
    assert tests['durationS'] == TESTS[n]['duration_s']
    expected_delta = None if n == 1 else _failing(n) - _failing(n - 1)
    assert tests['deltaFailed'] == expected_delta
    assert tests['series'] == [{'iteration': k, 'failed': TESTS[k]['failed']} for k in range(1, n + 1)]


@pytest.mark.parametrize('n', ITERATIONS)
def test_lint_counts_new_and_resolved_rules_from_by_rule(run, n):
    lint = _quality_at(run, n)['lint']
    new, resolved = _lint_deltas(n)
    assert lint['state'] == ('FAIL' if LINT[n]['errors'] > 0 else 'PASS')
    assert lint['iteration'] == n
    assert (lint['errors'], lint['warnings']) == (LINT[n]['errors'], LINT[n]['warnings'])
    assert lint['byRule'] == LINT[n]['by_rule']
    assert (lint['newCount'], lint['resolvedCount']) == (new, resolved)
    assert lint['series'] == [{'iteration': k, 'errors': LINT[k]['errors'], 'warnings': LINT[k]['warnings']}
                              for k in range(1, n + 1)]


@pytest.mark.parametrize('n', ITERATIONS)
def test_coverage_trend_passes_from_the_target_on(run, n):
    trend = _quality_at(run, n)['coverageTrend']
    assert trend['state'] == ('PASS' if COVERAGE[n] >= COVERAGE_TARGET else 'FAIL')
    assert (trend['percent'], trend['target'], trend['iteration']) == (COVERAGE[n], COVERAGE_TARGET, n)
    assert trend['series'] == [{'iteration': k, 'percent': COVERAGE[k]} for k in range(1, n + 1)]


@pytest.mark.parametrize('n', ITERATIONS)
def test_diff_accumulates_per_iteration_and_compares_with_the_previous(run, n):
    diff = _quality_at(run, n)['diff']
    current = _diff_of(n)
    assert diff['state'] == 'PASS'
    assert diff['iteration'] == n
    assert sorted(diff['files']) == current['files']
    assert diff['filesTotal'] == current['filesTotal']
    assert (diff['added'], diff['deleted']) == (current['added'], current['deleted'])
    through = [_diff_of(k) for k in range(1, n + 1)]
    assert diff['cumulative'] == {
        'added': sum(item['added'] for item in through),
        'deleted': sum(item['deleted'] for item in through),
        'files': sum(item['filesTotal'] for item in through),
    }
    if n == 1:
        assert diff['vsPrevious'] is None
    else:
        before = _diff_of(n - 1)
        assert diff['vsPrevious'] == {'added': current['added'] - before['added'],
                                      'deleted': current['deleted'] - before['deleted']}


# ---- flaky: a flip between two iterations that reported ids, with no code change in the later one

def _quiet(n):
    diff = _diff_of(n)
    return diff['added'] == 0 and diff['deleted'] == 0


def _flips_through(n):
    counts = {}
    for before, after in zip(range(1, n), range(2, n + 1)):
        if not _quiet(after):
            continue
        for test in set(FAILED_IDS[before]) ^ set(FAILED_IDS[after]):
            counts[test] = counts.get(test, 0) + 1
    return counts


def _expected_flaky(n):
    if n < 2:
        return {'state': 'UNVERIFIED', 'reason': NO_IDS}
    counts = _flips_through(n)
    if not counts:
        return {'state': 'PASS', 'reason': f'nenhum teste instável (ids observados em {n} iterações)', 'ids': []}
    ids = [{'id': test, 'flips': flips} for test, flips in counts.items()]
    names = ', '.join(f"{item['id']} ({item['flips']} {'virada' if item['flips'] == 1 else 'viradas'})"
                      for item in ids)
    label = '1 teste instável' if len(ids) == 1 else f'{len(ids)} testes instáveis'
    return {'state': 'FAIL', 'reason': f'{label}: {names}', 'ids': ids}


@pytest.mark.parametrize('n', ITERATIONS)
def test_flaky_follows_the_flip_rule_at_every_finish(run, n):
    flaky = _quality_at(run, n)['flaky']
    expected = _expected_flaky(n)
    assert flaky['state'] == expected['state']
    assert flaky['reason'] == expected['reason']
    if 'ids' in expected:
        assert flaky['ids'] == expected['ids']


def test_the_flip_is_flagged_from_the_quiet_iteration_three_on(run):
    assert [_quality_at(run, n)['flaky']['state'] for n in ITERATIONS] == [
        'UNVERIFIED', 'PASS', 'FAIL', 'FAIL', 'FAIL']
    assert _quality_at(run, 5)['flaky']['ids'] == [{'id': FLIP, 'flips': 1}]


def test_without_quality_events_the_panel_stays_unverified():
    events = [evt for evt in _run_events() if evt['kind'] in ('iteration_started', 'iteration_finished')]
    final = _drive(_steps(events))[-1]
    quality = final['quality']
    unverified = {'state': 'UNVERIFIED', 'reason': NO_PRODUCER}
    assert quality['tests'] == {'state': 'UNVERIFIED', 'reason': 'quality-matrix.json ainda nao gerado'}
    assert quality['lint'] == unverified
    assert quality['coverageTrend'] == unverified
    assert quality['diff'] == unverified
    assert quality['flaky']['state'] == 'UNVERIFIED'
    assert quality['flaky']['reason'] != NO_PRODUCER
