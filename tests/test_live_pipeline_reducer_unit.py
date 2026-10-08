'''Pure reducer unit tests for the Simplicio Live pipeline (issue #1402, slice 4b-1, TDD red).

reducer.js and sse.js live in simplicio_loop/dashboard/static/live/ and do not exist yet, so these tests fail
with a node error about the missing module or with an assertion mismatch. The reducer runs in node through
tests/fixtures/live_pipeline/driver.mjs; the SSE parser runs through node -e.
'''
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from simplicio_loop.progress import PHASES, _phase_percent

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / 'contracts' / 'dashboard-event' / 'v1' / 'fixtures' / 'runner-lifecycle.jsonl'
DRIVER = REPO / 'tests' / 'fixtures' / 'live_pipeline' / 'driver.mjs'
SSE_FILE = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'live' / 'sse.js'
RUN_ID = 'run-fixture-lifecycle'
RAIL_ORDER = ['intake', 'mapping', 'planning', 'executing', 'validating', 'delivering', 'done']
T0 = 1800000000000
SSE_SCRIPT = '''const { createSseParser } = await import(process.argv[1]);
const chunks = [];
for await (const c of process.stdin) chunks.push(c);
const { chunks: inputs } = JSON.parse(Buffer.concat(chunks).toString('utf8'));
const parser = createSseParser();
process.stdout.write(JSON.stringify(inputs.map((text) => parser.push(text))));
'''


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


def _run_node(args, stdin_text):
    proc = subprocess.run([_node()] + args, input=stdin_text, capture_output=True, text=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _drive(steps, run_id=None):
    payload = {'steps': steps}
    if run_id is not None:
        payload['runId'] = run_id
    return _run_node([str(DRIVER)], json.dumps(payload))


def _ms(ts):
    return int(datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc).timestamp() * 1000)


def _fixture():
    return [json.loads(line) for line in FIXTURE.read_text(encoding='utf-8').splitlines() if line.strip()]


def _event_steps(events):
    return [{'action': {'type': 'event', 'event': ev}, 'now': _ms(ev['ts'])} for ev in events]


def _last_ms(events):
    return _ms(events[-1]['ts'])


def _gate(view, name):
    matches = [gate for gate in view['gates'] if gate['gate'] == name]
    assert matches, 'no gate named %s in the view' % name
    return matches[0]


def test_rail_walks_the_pipeline_phases_in_order():
    views = _drive(_event_steps(_fixture()))
    seen = []
    for view in views:
        phase = view['rail']['phase']
        if phase is not None and (not seen or seen[-1] != phase):
            seen.append(phase)
    assert seen == RAIL_ORDER


def test_phases_list_has_eight_items_with_entries_per_on_rail_phase():
    views = _drive(_event_steps(_fixture()))
    phases = views[-1]['phases']
    assert [item['phase'] for item in phases] == list(PHASES)
    entries = {item['phase']: item['entries'] for item in phases}
    assert entries == {'intake': 1, 'mapping': 1, 'planning': 1, 'executing': 1,
                       'validating': 1, 'watching': 0, 'delivering': 1, 'done': 1}


def test_watcher_then_evidence_then_oracle_gates_follow_the_events():
    views = _drive(_event_steps(_fixture()))
    assert _gate(views[3], 'watcher')['state'] == 'UNVERIFIED'
    assert _gate(views[17], 'evidence')['state'] == 'PASS'
    assert _gate(views[17], 'evidence')['ref'] == 'evidence-receipt.json'
    assert _gate(views[17], 'watcher')['state'] == 'UNVERIFIED'
    assert _gate(views[24], 'oracle')['state'] == 'UNVERIFIED'


def test_gate_without_an_event_is_unverified_with_a_reason():
    views = _drive(_event_steps(_fixture()[:1]))
    dod = _gate(views[0], 'dod')
    assert dod['state'] == 'UNVERIFIED'
    assert dod['reason'] == 'nenhum evento recebido'


def test_percent_follows_the_python_phase_mapping_and_caps_at_99_without_a_receipt():
    views = _drive(_event_steps(_fixture()))
    checked = 0
    for view in views:
        phase = view['rail']['phase']
        if phase in PHASES:
            assert view['percent'] == min(99, _phase_percent(phase)), (view['lastSeq'], phase)
            checked += 1
    assert checked >= 20
    assert views[-1]['rail']['phase'] == 'done'
    assert views[-1]['percent'] == 99


@pytest.mark.parametrize('summary, expected', [
    ({'verdict': 'COMPLETE', 'completion': {'ready': True}}, 100),
    ({'verdict': 'COMPLETE', 'completion': {'ready': False}}, 99),
    ({'verdict': 'FAILED', 'completion': {'ready': True}}, 99),
    ({'verdict': 'NOT_READY', 'completion': {'ready': True}}, 99),
])
def test_percent_is_100_only_after_a_ready_complete_summary(summary, expected):
    events = _fixture()
    steps = _event_steps(events) + [{'action': {'type': 'summary', 'summary': summary}, 'now': _last_ms(events)}]
    views = _drive(steps)
    before, after = views[len(events) - 1], views[-1]
    assert before['percent'] == 99
    assert after['percent'] == expected
    assert after['rail']['receiptReady'] is (expected == 100)
    assert _gate(after, 'oracle')['state'] == ('PASS' if expected == 100 else 'UNVERIFIED')


def test_duplicate_and_older_seq_events_are_ignored():
    events = _fixture()
    first_five = events[:5]
    base = _drive(_event_steps(first_five))
    views = _drive(_event_steps(first_five + [events[2], events[1]]))
    assert views[-1]['lastSeq'] == 5
    assert views[-1]['phases'] == base[-1]['phases']
    assert views[-1]['gates'] == base[-1]['gates']
    assert views[-1]['rail'] == base[-1]['rail']


def test_events_of_another_run_or_schema_are_ignored():
    events = _fixture()
    foreign_run = dict(events[5], run_id='run-other', seq=6)
    foreign_schema = dict(events[5], schema='simplicio.dashboard-event/v0', seq=7)
    views = _drive(_event_steps(events[:5] + [foreign_run, foreign_schema]))
    assert views[-1]['lastSeq'] == 5
    assert views[-1]['runId'] == RUN_ID


def test_stall_detected_is_shown_and_a_phase_change_clears_it():
    events = _fixture()
    last = events[-1]
    stall = dict(last, seq=29, kind='stall_detected', phase='done', payload={'streak': 3},
                 event_id='01STALLDETECTED0000000000')
    entered = dict(last, seq=30, kind='phase_entered', phase='validating',
                   payload={'from': 'done', 'reason': 'resumed'}, event_id='01STALLCLEARED00000000000')
    views = _drive(_event_steps(events + [stall, entered]))
    stalled = views[len(events)]['health']['stall']
    assert stalled['detected'] is True
    assert stalled['streak'] == 3
    assert views[-1]['health']['stall']['detected'] is False


def test_action_gate_blocked_is_shown_as_blocked():
    events = _fixture()
    blocked = dict(events[-1], seq=29, kind='gate_evaluated', phase='done',
                   payload={'step': 'action_gate', 'message': 'push bloqueado', 'gate': 'action', 'verdict': 'blocked'},
                   event_id='01ACTIONBLOCKED000000000000')
    views = _drive(_event_steps(events + [blocked]))
    assert _gate(views[-1], 'action')['state'] == 'BLOCKED'


def test_heartbeat_age_is_now_minus_the_last_heartbeat():
    views = _drive([{'action': None, 'now': T0}, {'action': {'type': 'heartbeat', 'at': T0}, 'now': T0 + 5000}])
    assert views[0]['health']['heartbeatAgeMs'] is None
    assert views[1]['health']['heartbeatAgeMs'] == 5000


def test_connection_goes_stale_only_after_45_seconds_without_activity():
    views = _drive([
        {'action': {'type': 'connection', 'status': 'live', 'at': T0}, 'now': T0},
        {'action': None, 'now': T0 + 45000},
        {'action': None, 'now': T0 + 45001},
    ])
    assert [view['connection'] for view in views] == ['live', 'live', 'stale']


def test_events_per_minute_counts_the_last_60_seconds():
    events = _fixture()
    steps = _event_steps(events) + [{'action': None, 'now': _last_ms(events) + 61000}]
    views = _drive(steps)
    assert views[len(events) - 1]['health']['eventsPerMinute'] == len(events)
    assert views[-1]['health']['eventsPerMinute'] == 0


def _sse(chunks):
    per_push = _run_node(['--input-type=module', '-e', SSE_SCRIPT, SSE_FILE.as_uri()],
                         json.dumps({'chunks': chunks}))
    return [event for batch in per_push for event in batch]


def test_sse_parser_joins_a_line_split_across_chunks():
    assert _sse(['id: 7\ndata: {"a"', ':1}\n\n']) == [{'type': 'event', 'id': '7', 'data': '{"a":1}'}]


def test_sse_parser_accepts_crlf_line_endings():
    assert _sse(['id: 8\r\ndata: x\r\n\r\n']) == [{'type': 'event', 'id': '8', 'data': 'x'}]


def test_sse_parser_joins_a_cr_at_a_chunk_end_with_an_lf_at_the_next_start():
    assert _sse(['id: 9\r\ndata: y\r', '\n\r\n']) == [{'type': 'event', 'id': '9', 'data': 'y'}]


def test_sse_parser_joins_multi_line_data_with_newlines():
    assert _sse(['id: 10\ndata: line1\ndata: line2\n\n']) == [
        {'type': 'event', 'id': '10', 'data': 'line1\nline2'}]


def test_sse_parser_returns_comment_lines_as_comments():
    events = _sse([': heartbeat\n\n'])
    assert [event['type'] for event in events] == ['comment']
    assert events[0]['text'].strip() == 'heartbeat'
