'''Unit tests for the Simplicio Live lanes contract C4 (issue #1402, TDD red).

reducer.js gains lanes, alerts, selectDrill and selectCommands. The reducer runs in node through
tests/fixtures/live_pipeline/driver.mjs, so these tests fail until that contract exists. The helpers are
duplicated from the reducer unit tests on purpose: this file imports from no other test file.
'''
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / 'contracts' / 'dashboard-event' / 'v1' / 'fixtures' / 'runner-lifecycle.jsonl'
DRIVER = REPO / 'tests' / 'fixtures' / 'live_pipeline' / 'driver.mjs'
REDUCER = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'live' / 'reducer.js'
SCHEMA = 'simplicio.dashboard-event/v1'
RUN_ID = 'run-fixture-lifecycle'
LANE = 'feat/fixture'
TASK = 'T1'
T0 = 1800000000000
PHASE_NAMES = ['intake', 'mapping', 'planning', 'executing', 'validating', 'watching', 'delivering', 'done']
ROOT_KEYS = {'runId', 'lastSeq', 'connection', 'phase', 'rail', 'percent', 'phases', 'gates', 'agora', 'health'}
NEW_VIEW_KEYS = {'lanes', 'alerts'}
CLAIM_SEQ = 16
T1_EVENT_SEQS = (16, 17, 18, 19, 24, 25)


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


def _iso(ms):
    return datetime.fromtimestamp(ms // 1000, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + '.%03dZ' % (ms % 1000)


def _ms(ts):
    stamp = datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)
    return round(stamp.timestamp() * 1000)


def _fixture():
    return [json.loads(line) for line in FIXTURE.read_text(encoding='utf-8').splitlines() if line.strip()]


def _fixture_with_lane():
    events = _fixture()
    events[CLAIM_SEQ - 1] = dict(events[CLAIM_SEQ - 1], lane=LANE)
    return events


def _fixture_lane_ms():
    return [_ms(ev['ts']) for ev in _fixture() if ev['seq'] in T1_EVENT_SEQS]


def _event(seq, kind, at, *, task_id=None, lane=None, iteration=None, phase='executing', source='worker',
           refs=None, payload=None):
    return {'schema': SCHEMA, 'seq': seq, 'ts': _iso(at), 'run_id': RUN_ID, 'task_id': task_id,
            'scope': 'task' if task_id else 'collection', 'source': source, 'kind': kind, 'phase': phase,
            'lane': lane, 'iteration': iteration, 'severity': 'info', 'payload': payload or {}, 'refs': refs or []}


def _steps(events):
    return [{'action': {'type': 'event', 'event': ev}, 'now': _ms(ev['ts'])} for ev in events]


def _lane(view, lane_id):
    matches = [lane for lane in view['lanes'] if lane['id'] == lane_id]
    assert matches, 'no lane %s in the view' % lane_id
    return matches[0]


def _blocks(view, lane_id=LANE):
    return _lane(view, lane_id)['blocks']


def _states(view, lane_id=LANE):
    return [block['state'] for block in _blocks(view, lane_id)]


def test_driver_adds_drill_and_commands_only_to_the_steps_that_carry_them():
    views = _drive([
        {'action': None, 'now': T0},
        {'action': None, 'now': T0 + 1, 'drill': {'type': 'logs'}},
        {'action': None, 'now': T0 + 2, 'commands': True},
    ])
    assert 'drill' not in views[0] and 'commands' not in views[0]
    assert 'drill' in views[1] and 'commands' not in views[1]
    assert 'commands' in views[2] and 'drill' not in views[2]


def test_view_keeps_its_old_keys_and_adds_lanes_and_alerts():
    views = _drive(_steps(_fixture_with_lane()))
    assert ROOT_KEYS <= set(views[-1])
    assert NEW_VIEW_KEYS <= set(views[-1])


def test_fixture_lane_is_running_at_seq_16_and_passes_at_seq_18():
    views = _drive(_steps(_fixture_with_lane()))
    assert _states(views[CLAIM_SEQ - 1]) == ['RUNNING']
    assert _blocks(views[CLAIM_SEQ - 1])[0]['events'] == 1
    assert _states(views[16]) == ['RUNNING']
    assert _blocks(views[16])[0]['events'] == 2
    assert _states(views[17]) == ['PASS']
    block = _blocks(views[17])[0]
    assert block['endedAt'] == _ms(_fixture()[17]['ts'])
    assert block['ref'] == 'evidence-receipt.json'
    assert _lane(views[17], LANE)['taskId'] == TASK


def test_event_with_lane_and_task_maps_the_task_to_its_lane():
    events = [
        _event(1, 'worker_claimed', T0, task_id='T9', lane='lane-x'),
        _event(2, 'apply_result', T0 + 100, task_id='T9'),
    ]
    views = _drive(_steps(events))
    assert _lane(views[-1], 'lane-x')['taskId'] == 'T9'
    assert _blocks(views[-1], 'lane-x')[0]['events'] == 2


def test_event_without_lane_or_known_task_is_logged_but_is_not_a_lane_event():
    events = [_event(1, 'gate_evaluated', T0, phase='intake',
                     payload={'gate': 'evidence', 'verdict': 'pass', 'message': 'sem lane'})]
    views = _drive(_steps(events) + [{'action': None, 'now': T0 + 1, 'drill': {'type': 'logs'}}])
    assert views[0]['lanes'] == []
    assert len(views[1]['drill']['lines']) == 1


def test_lanes_are_listed_in_first_seen_order():
    events = [
        _event(1, 'lane_progress', T0, task_id='TB', lane='lane-b'),
        _event(2, 'lane_progress', T0 + 1, task_id='TA', lane='lane-a'),
        _event(3, 'lane_progress', T0 + 2, task_id='TB', lane='lane-b'),
    ]
    views = _drive(_steps(events))
    assert [lane['id'] for lane in views[-1]['lanes']] == ['lane-b', 'lane-a']


def test_worker_claim_opens_a_running_block_and_carries_the_lease_id():
    views = _drive(_steps([_event(1, 'worker_claimed', T0, task_id=TASK, lane=LANE, payload={'lease_id': 'L-7'})]))
    lane = _lane(views[0], LANE)
    assert lane['leaseId'] == 'L-7'
    assert lane['agent']['state'] == 'UNVERIFIED' and lane['agent']['reason']
    assert lane['heartbeat']['state'] == 'UNVERIFIED' and lane['heartbeat']['reason']
    block = lane['blocks'][0]
    assert block['state'] == 'RUNNING'
    assert block['startedAt'] == T0
    assert block['endedAt'] is None


def test_claim_without_a_lease_has_a_null_lease_id():
    views = _drive(_steps([_event(1, 'worker_claimed', T0, task_id=TASK, lane=LANE)]))
    assert _lane(views[0], LANE)['leaseId'] is None


def test_each_worker_claim_starts_a_new_block():
    events = [
        _event(1, 'worker_claimed', T0, task_id=TASK, lane=LANE),
        _event(2, 'worker_claimed', T0 + 1000, task_id=TASK, lane=LANE),
    ]
    views = _drive(_steps(events))
    assert _states(views[-1]) == ['RUNNING', 'RUNNING']
    assert [block['startedAt'] for block in _blocks(views[-1])] == [T0, T0 + 1000]


def test_integer_iteration_change_opens_a_block_and_a_null_iteration_adopts_the_first_integer():
    events = [
        _event(1, 'lane_progress', T0, task_id=TASK, lane=LANE),
        _event(2, 'lane_progress', T0 + 1, task_id=TASK, lane=LANE, iteration=1),
        _event(3, 'lane_progress', T0 + 2, task_id=TASK, lane=LANE),
        _event(4, 'lane_progress', T0 + 3, task_id=TASK, lane=LANE, iteration=1),
        _event(5, 'lane_progress', T0 + 4, task_id=TASK, lane=LANE, iteration=2),
    ]
    blocks = _blocks(_drive(_steps(events))[-1])
    assert [block['iteration'] for block in blocks] == [1, 2]
    assert [block['events'] for block in blocks] == [4, 1]


@pytest.mark.parametrize('gate', ['evidence', 'quality'])
@pytest.mark.parametrize('verdict, expected', [('pass', 'PASS'), ('fail', 'FAIL'), ('blocked', 'BLOCKED'), ('pending', 'RUNNING')])
def test_evidence_and_quality_gates_set_the_block_state_by_verdict(gate, verdict, expected):
    events = [
        _event(1, 'worker_claimed', T0, task_id=TASK, lane=LANE),
        _event(2, 'gate_evaluated', T0 + 700, task_id=TASK, lane=LANE,
               payload={'gate': gate, 'verdict': verdict, 'message': 'veredito'}),
    ]
    block = _blocks(_drive(_steps(events))[-1])[0]
    assert block['state'] == expected
    assert (block['endedAt'] is None) == (expected == 'RUNNING')


def test_apply_result_with_blocked_execution_closes_the_block_as_blocked():
    events = [
        _event(1, 'worker_claimed', T0, task_id=TASK, lane=LANE),
        _event(2, 'apply_result', T0 + 500, task_id=TASK, lane=LANE, payload={'execution_state': 'blocked'}),
    ]
    views = _drive(_steps(events) + [{'action': None, 'now': T0 + 9000}])
    block = _blocks(views[-1])[0]
    assert block['state'] == 'BLOCKED'
    assert block['endedAt'] == T0 + 500
    assert block['elapsedMs'] == 500


@pytest.mark.parametrize('gate', ['watcher', 'oracle', 'dod', 'action'])
def test_watcher_oracle_dod_and_action_gates_never_touch_a_block(gate):
    events = [_event(1, 'worker_claimed', T0, task_id=TASK, lane=LANE)]
    for seq, verdict in ((2, 'pass'), (3, 'fail'), (4, 'blocked')):
        events.append(_event(seq, 'gate_evaluated', T0 + seq * 100, task_id=TASK, lane=LANE,
                             payload={'gate': gate, 'verdict': verdict, 'message': 'sem bloco'}))
    views = _drive(_steps(events))
    assert _states(views[-1]) == ['RUNNING']
    assert _blocks(views[-1])[0]['endedAt'] is None


@pytest.mark.parametrize('outcome, expected', [('pass', 'PASS'), ('blocked', 'BLOCKED'), ('refeed', 'UNVERIFIED')])
def test_iteration_finished_outcome_closes_the_block(outcome, expected):
    events = [
        _event(1, 'iteration_started', T0, task_id=TASK, lane=LANE, iteration=1),
        _event(2, 'iteration_finished', T0 + 800, task_id=TASK, lane=LANE, iteration=1,
               payload={'outcome': outcome}),
    ]
    block = _blocks(_drive(_steps(events))[-1])[0]
    assert block['state'] == expected
    assert block['endedAt'] == T0 + 800


def test_stall_on_a_lane_marks_its_block_stalled_until_the_next_event():
    events = [
        _event(1, 'worker_claimed', T0, task_id=TASK, lane=LANE),
        _event(2, 'stall_detected', T0 + 3000, lane=LANE, payload={'streak': 2}),
        _event(3, 'lane_progress', T0 + 4000, lane=LANE),
    ]
    views = _drive(_steps(events))
    stalled = _blocks(views[1])[0]
    assert stalled['state'] == 'STALLED'
    assert stalled['endedAt'] is None
    assert _states(views[2]) == ['RUNNING']


def test_a_closed_block_stays_closed_through_a_stall_and_later_verdicts():
    events = [
        _event(1, 'worker_claimed', T0, task_id=TASK, lane=LANE),
        _event(2, 'gate_evaluated', T0 + 100, task_id=TASK, lane=LANE,
               payload={'gate': 'evidence', 'verdict': 'pass', 'message': 'ok'}),
        _event(3, 'stall_detected', T0 + 200, lane=LANE, payload={'streak': 1}),
        _event(4, 'lane_progress', T0 + 300, lane=LANE),
        _event(5, 'gate_evaluated', T0 + 400, task_id=TASK, lane=LANE,
               payload={'gate': 'quality', 'verdict': 'fail', 'message': 'tarde'}),
    ]
    views = _drive(_steps(events))
    assert _states(views[-1]) == ['PASS']
    assert _blocks(views[-1])[0]['endedAt'] == T0 + 100


def test_stall_alert_id_comes_from_the_event_seq_and_carries_its_time():
    events = [
        _event(1, 'worker_claimed', T0, task_id=TASK, lane=LANE),
        _event(29, 'stall_detected', T0 + 5000, lane=LANE, payload={'streak': 3}),
    ]
    views = _drive(_steps(events))
    assert views[0]['alerts'] == []
    alert = views[1]['alerts'][0]
    assert alert['id'] == 'stall-29'
    assert alert['state'] == 'STALLED'
    assert alert['at'] == T0 + 5000
    assert isinstance(alert['heading'], str) and alert['heading']
    assert isinstance(alert['message'], str) and alert['message']


def test_each_stall_adds_its_own_alert():
    events = [
        _event(1, 'worker_claimed', T0, task_id=TASK, lane=LANE),
        _event(2, 'stall_detected', T0 + 100, lane=LANE, payload={'streak': 1}),
        _event(3, 'lane_progress', T0 + 200, lane=LANE),
        _event(4, 'stall_detected', T0 + 300, lane=LANE, payload={'streak': 2}),
    ]
    views = _drive(_steps(events))
    assert 'stall-4' in [alert['id'] for alert in views[-1]['alerts']]


def test_block_elapsed_follows_now_while_open_and_stops_at_its_end():
    steps = [
        {'action': {'type': 'event', 'event': _event(1, 'worker_claimed', T0, task_id=TASK, lane=LANE)}, 'now': T0},
        {'action': None, 'now': T0 + 5000},
        {'action': {'type': 'event', 'event': _event(2, 'gate_evaluated', T0 + 2000, task_id=TASK, lane=LANE,
                    payload={'gate': 'evidence', 'verdict': 'pass', 'message': 'ok'})}, 'now': T0 + 2000},
        {'action': None, 'now': T0 + 9000},
    ]
    views = _drive(steps)
    assert _blocks(views[1])[0]['elapsedMs'] == 5000
    assert _blocks(views[3])[0]['elapsedMs'] == 2000


def test_block_ref_and_reason_come_from_the_event_that_set_its_state():
    events = [
        _event(1, 'worker_claimed', T0, task_id=TASK, lane=LANE),
        _event(2, 'gate_evaluated', T0 + 100, task_id=TASK, lane=LANE, refs=['evidence-receipt.json'],
               payload={'gate': 'evidence', 'verdict': 'fail', 'message': 'teste vermelho'}),
    ]
    block = _blocks(_drive(_steps(events))[-1])[0]
    assert block['state'] == 'FAIL'
    assert block['ref'] == 'evidence-receipt.json'
    assert block['reason'] == 'teste vermelho'


def test_a_lane_keeps_at_most_50_blocks_with_the_newest_last():
    events = [_event(seq, 'lane_progress', T0 + seq, task_id=TASK, lane=LANE, iteration=seq) for seq in range(1, 61)]
    blocks = _blocks(_drive(_steps(events))[-1])
    assert len(blocks) == 50
    assert blocks[-1]['iteration'] == 60


def test_the_log_keeps_the_newest_200_events():
    events = [_event(seq, 'contract_frozen', T0 + seq, phase='intake') for seq in range(1, 251)]
    steps = _steps(events) + [{'action': None, 'now': T0 + 251, 'drill': {'type': 'logs'}}]
    lines = _drive(steps)[-1]['drill']['lines']
    assert len(lines) == 200
    assert lines[0]['at'] == T0 + 51
    assert lines[-1]['at'] == T0 + 250


def test_drill_log_lines_carry_at_level_source_and_text():
    events = [_event(1, 'lane_progress', T0, task_id=TASK, lane=LANE)]
    lines = _drive(_steps(events) + [{'action': None, 'now': T0, 'drill': {'type': 'logs'}}])[-1]['drill']['lines']
    assert len(lines) == 1
    assert set(lines[0]) == {'at', 'level', 'source', 'text'}
    assert lines[0]['at'] == T0
    assert lines[0]['source'] == 'worker'
    assert isinstance(lines[0]['text'], str)


def test_phase_drill_has_a_title_facts_and_lines():
    target = {'type': 'phase', 'phase': 'executing'}
    steps = _steps(_fixture_with_lane()) + [{'action': None, 'now': _ms(_fixture()[-1]['ts']), 'drill': target}]
    drill = _drive(steps)[-1]['drill']
    assert isinstance(drill['title'], str) and drill['title']
    assert drill['facts']
    assert all(isinstance(fact['label'], str) and fact['label'] for fact in drill['facts'])
    assert drill['lines']
    assert all(set(line) == {'at', 'level', 'source', 'text'} for line in drill['lines'])


def test_block_drill_shows_the_block_ref_and_the_events_it_holds():
    final_ms = _ms(_fixture()[-1]['ts'])
    index = _blocks(_drive(_steps(_fixture_with_lane()))[-1])[0]['index']
    target = {'type': 'block', 'lane': LANE, 'index': index}
    drill = _drive(_steps(_fixture_with_lane()) + [{'action': None, 'now': final_ms, 'drill': target}])[-1]['drill']
    assert any(fact.get('ref') == 'evidence-receipt.json' for fact in drill['facts'])
    assert [line['at'] for line in drill['lines']] == _fixture_lane_ms()


def test_lane_drill_names_its_task_and_lists_its_lane_events():
    final_ms = _ms(_fixture()[-1]['ts'])
    target = {'type': 'lane', 'lane': LANE}
    drill = _drive(_steps(_fixture_with_lane()) + [{'action': None, 'now': final_ms, 'drill': target}])[-1]['drill']
    assert isinstance(drill['title'], str) and drill['title']
    assert any(TASK in str(fact.get('value', '')) for fact in drill['facts'])
    assert [line['at'] for line in drill['lines']] == _fixture_lane_ms()


def test_commands_list_the_eight_phases_the_task_and_the_distinct_log_refs():
    steps = _steps(_fixture_with_lane()) + [{'action': None, 'now': _ms(_fixture()[-1]['ts']), 'commands': True}]
    commands = _drive(steps)[-1]['commands']
    ids = [command['id'] for command in commands]
    assert [i for i in ids if i.startswith('phase:')] == ['phase:' + name for name in PHASE_NAMES]
    assert 'task:' + TASK in ids
    assert 'file:task-contract.json' in ids
    file_ids = [i for i in ids if i.startswith('file:')]
    assert len(file_ids) == len(set(file_ids))
    assert all(i.split(':')[0] in ('phase', 'task', 'file') for i in ids)
    assert all(set(command) == {'id', 'label', 'group', 'hint'} for command in commands)
    assert all(isinstance(command['label'], str) and command['label'] for command in commands)


def test_file_commands_are_capped_at_50_distinct_refs():
    events = [_event(seq, 'contract_frozen', T0 + seq, phase='intake', refs=['doc-%d.json' % seq, 'doc-shared.json'])
              for seq in range(1, 61)]
    commands = _drive(_steps(events) + [{'action': None, 'now': T0 + 61, 'commands': True}])[-1]['commands']
    file_ids = [command['id'] for command in commands if command['id'].startswith('file:')]
    assert len(file_ids) == 50
    assert len(set(file_ids)) == 50


PURITY_SCRIPT = '''const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
const mod = await import(process.argv[1]);
const before = mod.initialState(input.runId);
const snapshot = JSON.stringify(before);
let state = before;
for (const action of input.actions) state = mod.reduce(state, action);
const reducedUntouched = JSON.stringify(before) === snapshot;
const stateSnapshot = JSON.stringify(state);
const view = mod.selectView(state, input.now);
const viewUntouched = JSON.stringify(state) === stateSnapshot;
let again = mod.initialState(input.runId);
for (const action of input.actions) again = mod.reduce(again, action);
const replay = JSON.stringify(mod.selectView(again, input.now)) === JSON.stringify(view);
process.stdout.write(JSON.stringify({ reducedUntouched, viewUntouched, replay, view }));
'''


def test_reducer_never_mutates_its_input_and_replays_to_the_same_view():
    events = _fixture_with_lane()
    payload = {'runId': RUN_ID, 'actions': [{'type': 'event', 'event': ev} for ev in events],
               'now': _ms(events[-1]['ts'])}
    result = _run_node(['--input-type=module', '-e', PURITY_SCRIPT, REDUCER.as_uri()], json.dumps(payload))
    assert result['reducedUntouched'] is True
    assert result['viewUntouched'] is True
    assert result['replay'] is True
    assert _lane(result['view'], LANE)['taskId'] == TASK

