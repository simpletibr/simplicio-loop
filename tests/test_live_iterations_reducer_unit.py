'''Pure reducer unit tests for the Simplicio Live iteration timeline (issue #1403, slice 1403a, TDD red).

reducer.js does not import ./iterations.js yet and selectView has no iterations key, so these tests fail on
a missing key, a missing module or a wrong value. The reducer runs in node through
tests/fixtures/live_pipeline/driver.mjs; the events are built and validated with scripts/dashboard_events.py.
'''
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

import dashboard_events as de

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / 'tests' / 'fixtures' / 'live_pipeline' / 'driver.mjs'
REDUCER = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'live' / 'reducer.js'
RUN_ID = 'run-iterations-fixture'
BASE_MS = int(datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
OLD_EXPORTS = ['GATES', 'READY_VERDICTS', 'STALE_AFTER_MS', 'initialState', 'reduce', 'selectView',
               'selectDrill', 'selectCommands']
EXPORT_NAMES_SCRIPT = '''const reducer = await import(process.argv[1]);
process.stdout.write(JSON.stringify(Object.keys(reducer)));
'''
ROW_KEYS = ['iteration', 'state', 'startedAt', 'endedAt', 'durationMs', 'verdict', 'streak', 'fingerprint',
            'retries', 'gatesFailing', 'gatesUnverified']
RETRY = {'step': 'rollback', 'blocker': 'teste de regressao falhou'}


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


def _run_node(args, stdin_text=''):
    proc = subprocess.run([_node()] + args, input=stdin_text, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _drive(steps):
    return _run_node([str(DRIVER)], json.dumps({'steps': steps}))


def _epoch(offset_ms):
    return BASE_MS + offset_ms


def _ts(offset_ms):
    moment = datetime.fromtimestamp(_epoch(offset_ms) / 1000, tz=timezone.utc)
    return moment.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (moment.microsecond // 1000)


def _event(seq, offset_ms, kind, iteration=None, payload=None, severity='info', run_id=RUN_ID):
    evt = de.build_envelope(run_id=run_id, kind=kind, source='hook', seq=seq, ts=_ts(offset_ms),
                            iteration=iteration, payload=payload or {}, severity=severity)
    assert de.validate_envelope(evt) == [], (kind, seq)
    return evt


def _now_of(evt):
    parsed = datetime.strptime(evt['ts'], '%Y-%m-%dT%H:%M:%S.%fZ')
    return int(parsed.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _steps(events):
    return [{'action': {'type': 'event', 'event': evt}, 'now': _now_of(evt)} for evt in events]


def _fixture():
    return [
        _event(1, 0, 'iteration_started', payload={'trigger': 'user_prompt'}),
        _event(2, 1000, 'iteration_started', iteration=1, payload={'trigger': 'refeed'}),
        _event(3, 8000, 'gate_evaluated', iteration=1,
               payload={'gate': 'evidence', 'verdict': 'pass', 'message': 'evidencia verificada'}),
        _event(4, 10000, 'iteration_finished', iteration=1, payload={'outcome': 'pass'}),
        _event(5, 11000, 'iteration_started', iteration=2, payload={'trigger': 'refeed'}),
        _event(6, 15000, 'gate_evaluated', iteration=2, severity='warning',
               payload={'gate': 'dod', 'verdict': 'fail', 'message': 'dod incompleto'}),
        _event(7, 16000, 'retry_scheduled', iteration=2, severity='warning',
               payload={'step': 'rollback', 'blocker': 'teste de regressao falhou'}),
        _event(8, 18000, 'iteration_finished', iteration=2, payload={'outcome': 'refeed'}),
        _event(9, 19000, 'iteration_started', iteration=3, payload={'trigger': 'refeed'}),
        _event(10, 22000, 'gate_evaluated', iteration=3,
               payload={'gate': 'dod', 'verdict': 'pass', 'message': 'dod completo'}),
        _event(11, 24000, 'iteration_finished', iteration=3, payload={'outcome': 'pass'}),
        _event(12, 25000, 'iteration_started', iteration=4, payload={'trigger': 'refeed'}),
        _event(13, 30000, 'stall_detected', iteration=4, severity='warning',
               payload={'fingerprint': 'abc123', 'streak': 3}),
        _event(14, 31000, 'gate_evaluated', iteration=4,
               payload={'gate': 'action', 'verdict': 'blocked', 'message': 'push bloqueado'}),
        _event(15, 32000, 'iteration_finished', iteration=4, payload={'outcome': 'blocked'}),
        _event(16, 33000, 'iteration_started', iteration=5, payload={'trigger': 'refeed'}),
        _event(17, 34000, 'gate_evaluated', iteration=5,
               payload={'gate': 'action', 'verdict': 'pass', 'message': 'push liberado'}),
        _event(18, 40000, 'iteration_finished', iteration=5, payload={'outcome': 'pass'}),
    ]


def _row(iteration, state, started, ended, duration, verdict, streak=None, fingerprint=None,
         retries=(), failing=(), unverified=()):
    return {'iteration': iteration, 'state': state, 'startedAt': started, 'endedAt': ended,
            'durationMs': duration, 'verdict': verdict, 'streak': streak, 'fingerprint': fingerprint,
            'retries': list(retries), 'gatesFailing': sorted(failing), 'gatesUnverified': sorted(unverified)}


EXPECTED = [
    _row(1, 'PASS', _epoch(0), _epoch(10000), 10000, 'PROGRESS',
         unverified=['action', 'dod', 'oracle', 'quality', 'watcher']),
    _row(2, 'UNVERIFIED', _epoch(11000), _epoch(18000), 7000, 'PROGRESS', retries=[RETRY],
         failing=['dod'], unverified=['action', 'oracle', 'quality', 'watcher']),
    _row(3, 'PASS', _epoch(19000), _epoch(24000), 5000, 'PROGRESS',
         unverified=['action', 'oracle', 'quality', 'watcher']),
    _row(4, 'BLOCKED', _epoch(25000), _epoch(32000), 7000, 'STALLED', streak=3, fingerprint='abc123',
         failing=['action'], unverified=['oracle', 'quality', 'watcher']),
    _row(5, 'PASS', _epoch(33000), _epoch(40000), 7000, 'PROGRESS',
         unverified=['oracle', 'quality', 'watcher']),
]


def _iterations(views):
    return views[-1]['iterations']


def _projected(items):
    rows = []
    for item in items:
        row = {key: item[key] for key in ROW_KEYS}
        row['gatesFailing'] = sorted(row['gatesFailing'])
        row['gatesUnverified'] = sorted(row['gatesUnverified'])
        rows.append(row)
    return rows


def test_iterations_match_the_contract_rows():
    assert _projected(_iterations(_drive(_steps(_fixture())))) == EXPECTED


def test_iterations_are_listed_ascending_one_row_per_iteration():
    assert [item['iteration'] for item in _iterations(_drive(_steps(_fixture())))] == [1, 2, 3, 4, 5]


def test_r2_a_null_iteration_start_becomes_the_start_of_the_first_iteration():
    first = _iterations(_drive(_steps(_fixture())))[0]
    assert first['startedAt'] == _epoch(0)
    assert first['durationMs'] == 10000


def test_r2_a_repeated_start_keeps_the_earliest_start_time():
    events = [
        _event(1, 2000, 'iteration_started', iteration=1),
        _event(2, 4000, 'iteration_started', iteration=1),
        _event(3, 6000, 'iteration_finished', iteration=1, payload={'outcome': 'pass'}),
    ]
    item = _iterations(_drive(_steps(events)))[0]
    assert item['startedAt'] == _epoch(2000)
    assert item['durationMs'] == 4000


def test_r1_events_without_an_iteration_follow_the_last_integer_and_early_ones_are_ignored():
    events = [
        _event(1, 0, 'retry_scheduled', payload={'step': 'early', 'blocker': 'antes do primeiro'}),
        _event(2, 1000, 'iteration_started', iteration=1),
        _event(3, 2000, 'iteration_started', iteration=2),
        _event(4, 3000, 'retry_scheduled', payload={'step': 'a', 'blocker': 'b1'}),
        _event(5, 4000, 'retry_scheduled', iteration=1, payload={'step': 'c', 'blocker': 'b2'}),
    ]
    items = _iterations(_drive(_steps(events)))
    assert [item['iteration'] for item in items] == [1, 2]
    assert items[0]['retries'] == [{'step': 'c', 'blocker': 'b2'}]
    assert items[1]['retries'] == [{'step': 'a', 'blocker': 'b1'}]


@pytest.mark.parametrize('index, state, ended', [(0, 'PASS', 10000), (1, 'UNVERIFIED', 18000),
                                                 (3, 'BLOCKED', 32000), (4, 'PASS', 40000)])
def test_r3_finish_sets_the_end_time_and_maps_the_outcome_to_the_state(index, state, ended):
    item = _iterations(_drive(_steps(_fixture())))[index]
    assert (item['state'], item['endedAt']) == (state, _epoch(ended))


def test_r3_an_open_iteration_is_running_and_has_no_end():
    current = _iterations(_drive(_steps(_fixture()[:12])))[-1]
    assert (current['iteration'], current['state'], current['endedAt']) == (4, 'RUNNING', None)


def test_r4_a_stall_sets_verdict_streak_and_fingerprint_on_its_iteration():
    items = _iterations(_drive(_steps(_fixture())))
    assert [(item['verdict'], item['streak'], item['fingerprint']) for item in items] == [
        ('PROGRESS', None, None), ('PROGRESS', None, None), ('PROGRESS', None, None),
        ('STALLED', 3, 'abc123'), ('PROGRESS', None, None)]


def test_r4_a_stalled_open_iteration_shows_the_stall_while_running():
    current = _iterations(_drive(_steps(_fixture()[:13])))[-1]
    assert (current['verdict'], current['state'], current['streak'], current['endedAt']) == (
        'STALLED', 'RUNNING', 3, None)


def test_r5_a_retry_is_listed_on_its_own_iteration_only():
    items = _iterations(_drive(_steps(_fixture())))
    assert [item['retries'] for item in items] == [[], [RETRY], [], [], []]


def test_r6_finished_without_stall_is_progress_and_an_open_iteration_has_no_verdict():
    items = _iterations(_drive(_steps(_fixture()[:12])))
    assert [item['verdict'] for item in items] == ['PROGRESS', 'PROGRESS', 'PROGRESS', None]


def test_r7_gates_are_a_snapshot_taken_at_finish():
    items = _iterations(_drive(_steps(_fixture())))
    assert items[1]['gatesFailing'] == ['dod']
    assert items[2]['gatesFailing'] == []
    assert sorted(items[0]['gatesUnverified']) == ['action', 'dod', 'oracle', 'quality', 'watcher']


def test_r7_an_open_iteration_reports_its_gates_live():
    current = _iterations(_drive(_steps(_fixture()[:6])))[-1]
    assert (current['state'], current['gatesFailing']) == ('RUNNING', ['dod'])


def test_r8_duration_is_end_minus_start():
    items = _iterations(_drive(_steps(_fixture())))
    assert [item['durationMs'] for item in items] == [10000, 7000, 5000, 7000, 7000]


def test_r8_an_open_iteration_lasts_until_now():
    steps = _steps(_fixture()[:12]) + [{'action': None, 'now': _epoch(32000)}]
    assert _iterations(_drive(steps))[-1]['durationMs'] == 7000


def test_r8_an_iteration_without_a_known_start_has_no_duration():
    events = [_event(1, 5000, 'iteration_finished', iteration=9, payload={'outcome': 'pass'})]
    items = _iterations(_drive(_steps(events)))
    assert [(item['iteration'], item['startedAt'], item['durationMs']) for item in items] == [(9, None, None)]


def test_duplicate_seq_and_foreign_run_events_are_ignored():
    events = _fixture()
    stale = dict(events[7], payload={'outcome': 'blocked'})
    foreign = dict(events[3], run_id='run-other', seq=19, payload={'outcome': 'blocked'})
    views = _drive(_steps(events + [stale, foreign]))
    assert views[-1]['lastSeq'] == 18
    assert _projected(_iterations(views)) == EXPECTED


def test_iterations_are_capped_at_200_keeping_the_newest():
    events = [_event(n, n * 1000, 'iteration_started', iteration=n) for n in range(1, 206)]
    numbers = [item['iteration'] for item in _iterations(_drive(_steps(events)))]
    assert len(numbers) == 200
    assert numbers == list(range(6, 206))


def test_reducer_imports_the_iterations_module():
    text = REDUCER.read_text(encoding='utf-8')
    assert re.search(r'import\s[^;]*from\s+\S*iterations\.js', text), 'reducer.js does not import ./iterations.js'


def test_reducer_keeps_its_old_exports():
    exported = _run_node(['--input-type=module', '-e', EXPORT_NAMES_SCRIPT, REDUCER.as_uri()])
    assert [name for name in OLD_EXPORTS if name not in exported] == []
