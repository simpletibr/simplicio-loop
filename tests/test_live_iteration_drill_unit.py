'''Unit tests for the Simplicio Live iteration drill (TDD red, issue #1403 follow-up).

selectDrill(state, {type: 'iteration', iteration: n}, now) must describe one iteration row from
state.iterations plus every lane line that belongs to a lane block of that iteration. The reducer runs in
node through tests/fixtures/live_pipeline/driver.mjs. This file imports from no other test file.
'''
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / 'tests' / 'fixtures' / 'live_pipeline' / 'driver.mjs'
REDUCER = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'live' / 'reducer.js'
SCHEMA = 'simplicio.dashboard-event/v1'
RUN_ID = 'run-iteration-drill'
T0 = 1800000000000
EMPTY = {'title': 'Sem dados disponíveis', 'facts': [], 'lines': []}
LANE_B = 'feat/beta'
LANE_A = 'feat/alpha'


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


def _run_node(args, stdin_text):
    proc = subprocess.run([_node()] + args, input=stdin_text, capture_output=True, text=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _drive(steps):
    return _run_node([str(DRIVER)], json.dumps({'steps': steps}))


def _event(seq, offset, kind, *, task_id=None, lane=None, iteration=None, payload=None, severity='info'):
    return {'schema': SCHEMA, 'seq': seq, 'ts': _iso(T0 + offset), 'run_id': RUN_ID, 'task_id': task_id,
            'scope': 'task' if task_id else 'collection', 'source': 'worker', 'kind': kind, 'phase': 'executing',
            'lane': lane, 'iteration': iteration, 'severity': severity, 'payload': payload or {}, 'refs': []}


def _iso(ms):
    return datetime.fromtimestamp(ms // 1000, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + '.%03dZ' % (ms % 1000)


def _ms(ts):
    stamp = datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)
    return round(stamp.timestamp() * 1000)


def _steps(events):
    return [{'action': {'type': 'event', 'event': ev}, 'now': _ms(ev['ts'])} for ev in events]


def _fixture():
    '''Two lanes, iterations 1 and 2. lane-b is seen first, so it is listed first.

    Iteration 1: lane-b holds two blocks (seq 1 and 4), lane-a holds one (seq 2, 5, 7). Seq 6 is a gate with no lane.
    Iteration 2: lane-b holds one block (seq 3), lane-a holds one (seq 8, 9). A stall on iteration 2 makes its row STALLED.
    '''
    return [
        _event(1, 0, 'lane_progress', task_id='TB', lane=LANE_B, iteration=1,
               payload={'message': 'lane-b inicia a iteração 1'}),
        _event(2, 1000, 'iteration_started', task_id='TA', lane=LANE_A, iteration=1,
               payload={'message': 'lane-a inicia a iteração 1'}),
        _event(3, 2000, 'lane_progress', task_id='TB', lane=LANE_B, iteration=2,
               payload={'message': 'lane-b avança para a iteração 2'}),
        _event(4, 3000, 'lane_progress', task_id='TB', lane=LANE_B, iteration=1,
               payload={'message': 'lane-b volta à iteração 1'}),
        _event(5, 4000, 'gate_evaluated', task_id='TA', lane=LANE_A, iteration=1,
               payload={'gate': 'evidence', 'verdict': 'pass', 'message': 'evidência verificada'}),
        _event(6, 6000, 'gate_evaluated', iteration=1, severity='warning',
               payload={'gate': 'dod', 'verdict': 'fail', 'message': 'dod incompleto'}),
        _event(7, 7000, 'iteration_finished', task_id='TA', lane=LANE_A, iteration=1,
               payload={'outcome': 'pass', 'message': 'iteração 1 concluída'}),
        _event(8, 8000, 'lane_progress', task_id='TA', lane=LANE_A, iteration=2,
               payload={'message': 'lane-a continua na iteração 2'}),
        _event(9, 8500, 'stall_detected', task_id='TA', lane=LANE_A, iteration=2, severity='warning',
               payload={'streak': 3, 'fingerprint': 'abc123', 'message': 'sem avanço na iteração 2'}),
    ]


FINAL_NOW = T0 + 9000


def _drill_at_end(target, events=None):
    steps = _steps(events or _fixture()) + [{'action': None, 'now': FINAL_NOW, 'drill': target}]
    return _drive(steps)[-1]['drill']


def _line_pairs(drill):
    return [(line['at'], line['text']) for line in drill['lines']]


def test_known_finished_iteration_has_its_facts_and_its_lane_lines_in_lane_then_block_order():
    drill = _drill_at_end({'type': 'iteration', 'iteration': 1})
    assert drill['title'] == 'Iteração 1'
    assert drill['facts'] == [
        {'label': 'Situação', 'value': 'PASS'},
        {'label': 'Duração', 'value': '6 s'},
        {'label': 'Gates falhando', 'value': '1'},
        {'label': 'Gates não verificados', 'value': '4'},
        {'label': 'Parada', 'value': 'não'},
    ]
    assert _line_pairs(drill) == [
        (T0 + 0, 'lane-b inicia a iteração 1'),
        (T0 + 3000, 'lane-b volta à iteração 1'),
        (T0 + 1000, 'lane-a inicia a iteração 1'),
        (T0 + 4000, 'evidência verificada'),
        (T0 + 7000, 'iteração 1 concluída'),
    ]
    assert all(set(line) == {'at', 'level', 'source', 'text'} for line in drill['lines'])


def test_open_stalled_iteration_without_a_start_reports_no_duration_and_the_stall_streak():
    drill = _drill_at_end({'type': 'iteration', 'iteration': 2})
    assert drill['title'] == 'Iteração 2'
    assert drill['facts'] == [
        {'label': 'Situação', 'value': 'RUNNING'},
        {'label': 'Duração', 'value': 'não informada'},
        {'label': 'Gates falhando', 'value': '1'},
        {'label': 'Gates não verificados', 'value': '4'},
        {'label': 'Parada', 'value': 'sim, repetição 3'},
    ]
    assert _line_pairs(drill) == [
        (T0 + 2000, 'lane-b avança para a iteração 2'),
        (T0 + 8000, 'lane-a continua na iteração 2'),
        (T0 + 8500, 'sem avanço na iteração 2'),
    ]


def test_phase_on_an_iteration_target_is_ignored():
    with_phase = _drill_at_end({'type': 'iteration', 'iteration': 2, 'phase': 'executing'})
    without_phase = _drill_at_end({'type': 'iteration', 'iteration': 2})
    assert with_phase == without_phase


def test_unknown_iteration_has_no_data():
    assert _drill_at_end({'type': 'iteration', 'iteration': 9}) == EMPTY


def test_iteration_without_a_row_has_no_data_even_when_it_is_absent_from_the_lanes():
    assert _drill_at_end({'type': 'iteration', 'iteration': 0}) == EMPTY


DRILL_SCRIPT = '''const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
const mod = await import(process.argv[1]);
let state = mod.initialState(input.runId);
for (const action of input.actions) state = mod.reduce(state, action);
const drills = input.iterations.map((value) => {
  const iteration = value === '__NaN__' ? Number.NaN : value;
  return mod.selectDrill(state, { type: 'iteration', iteration }, input.now);
});
process.stdout.write(JSON.stringify(drills));
'''


@pytest.mark.parametrize('iteration', ['1', '2', -1, -2, '__NaN__', 1.5])
def test_iteration_given_as_string_negative_nan_or_fraction_has_no_data(iteration):
    events = _fixture()
    payload = {'runId': RUN_ID, 'actions': [{'type': 'event', 'event': ev} for ev in events],
               'now': FINAL_NOW, 'iterations': [iteration]}
    drills = _run_node(['--input-type=module', '-e', DRILL_SCRIPT, REDUCER.as_uri()], json.dumps(payload))
    assert drills == [EMPTY]
