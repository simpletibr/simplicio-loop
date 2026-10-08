'''Pure unit tests for the Simplicio Live board model (board.js).

board.js groups the run summaries of GET /api/runs into the nine board columns: the eight phases in order, then
the off-track column. It runs in node (no DOM, no clock: the caller passes nowMs). These tests fail until board.js exists.
'''
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'live' / 'board.js'

PHASES = ['intake', 'mapping', 'planning', 'executing', 'validating', 'watching', 'delivering', 'done']
COLUMN_KEYS = PHASES + ['off']
LABELS = {'intake': 'Contrato', 'mapping': 'Mapeamento', 'planning': 'Plano', 'executing': 'Execução',
          'validating': 'Validação', 'watching': 'Watcher', 'delivering': 'Entrega', 'done': 'Concluído',
          'off': 'Fora do trilho'}
NOW = int(datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


SCRIPT = '''
import fs from 'node:fs';
import * as board from %s;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
let out;
if (input.op === 'columnOf') out = board.columnOf(input.phase);
else if (input.op === 'boardOf') out = board.boardOf(input.runs, input.nowMs);
else if (input.op === 'runHref') out = board.runHref(input.runId, input.token, input.pathname);
else out = { BOARD_PHASES: board.BOARD_PHASES, OFF_TRACK: board.OFF_TRACK, COLUMN_LABELS: board.COLUMN_LABELS };
process.stdout.write(JSON.stringify(out));
'''


def _call(payload):
    script = SCRIPT % json.dumps(MODULE.as_uri())
    proc = subprocess.run([_node(), '--input-type=module', '-e', script], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _row(run_id, phase, **changes):
    row = {'run_id': run_id, 'phase': phase, 'progress_status': 'RUNNING', 'percent': 40,
           'current_action': 'mapeando', 'repo': '/repo/a', 'updated_at': _iso(NOW - 60000), 'status': 'running'}
    row.update(changes)
    return row


def _board(runs, now=NOW):
    return _call({'op': 'boardOf', 'runs': runs, 'nowMs': now})


def _column(board, key):
    return next(column for column in board['columns'] if column['key'] == key)


def _card(run_row):
    return _column(_board([run_row]), run_row['phase'] if run_row['phase'] in PHASES else 'off')['cards'][0]


def test_the_phase_list_the_off_track_key_and_the_labels_are_the_contract():
    out = _call({'op': 'constants'})
    assert out['BOARD_PHASES'] == PHASES
    assert out['OFF_TRACK'] == 'off'
    assert out['COLUMN_LABELS'] == LABELS


@pytest.mark.parametrize('phase', PHASES)
def test_column_of_maps_each_phase_to_itself(phase):
    assert _call({'op': 'columnOf', 'phase': phase}) == phase


@pytest.mark.parametrize('phase', ['blocked', 'awaiting_decision', 'cancelled', 'unknown', '', None])
def test_column_of_sends_every_other_phase_to_off(phase):
    assert _call({'op': 'columnOf', 'phase': phase}) == 'off'


def test_the_board_has_the_nine_columns_in_contract_order_with_their_labels():
    out = _board([], now=0)
    assert [(column['key'], column['label']) for column in out['columns']] == [(key, LABELS[key]) for key in COLUMN_KEYS]


@pytest.mark.parametrize('runs', [None, [], {'run_id': 'x'}, 'abc'])
def test_an_empty_or_non_array_input_gives_nine_empty_columns(runs):
    out = _board(runs, now=0)
    assert out['total'] == 0
    assert [column['key'] for column in out['columns']] == COLUMN_KEYS
    assert all(column['count'] == 0 and column['cards'] == [] for column in out['columns'])


def test_a_run_lands_in_the_column_of_its_phase_and_an_off_track_run_in_off():
    runs = [_row('r1', 'executing'), _row('r2', 'blocked'), _row('r3', 'done'),
            _row('r4', 'awaiting_decision'), _row('r5', 'intake')]
    out = _board(runs)
    assert out['total'] == 5
    assert {column['key']: column['count'] for column in out['columns']} == {
        'intake': 1, 'mapping': 0, 'planning': 0, 'executing': 1, 'validating': 0,
        'watching': 0, 'delivering': 0, 'done': 1, 'off': 2}
    assert [card['runId'] for card in _column(out, 'off')['cards']] == ['r2', 'r4']
    assert [card['runId'] for card in _column(out, 'executing')['cards']] == ['r1']


def test_cards_in_a_column_keep_the_input_order():
    runs = [_row('c', 'executing'), _row('a', 'mapping'), _row('b', 'executing')]
    assert [card['runId'] for card in _column(_board(runs), 'executing')['cards']] == ['c', 'b']


def test_a_card_carries_the_run_summary_fields_and_the_raw_phase():
    row = _row('run-1', 'blocked', progress_status='BLOCKED', percent=35, current_action='aguardando',
               repo='/repo/a', updated_at=_iso(NOW - 5000))
    assert _card(row) == {'runId': 'run-1', 'phase': 'blocked', 'state': 'BLOCKED', 'percent': 35,
                          'currentAction': 'aguardando', 'repo': '/repo/a', 'updatedAt': _iso(NOW - 5000),
                          'ageMs': 5000}


def test_state_falls_back_to_unverified_when_progress_status_is_missing():
    row = _row('run-1', 'executing')
    del row['progress_status']
    assert _card(row)['state'] == 'UNVERIFIED'


def test_age_is_now_minus_updated_at():
    assert _card(_row('run-1', 'executing', updated_at=_iso(NOW - 90000)))['ageMs'] == 90000


@pytest.mark.parametrize('value', [None, 'not a date', ''])
def test_age_is_null_when_updated_at_is_invalid(value):
    assert _card(_row('run-1', 'executing', updated_at=value))['ageMs'] is None


def test_age_is_null_when_updated_at_is_missing():
    row = _row('run-1', 'executing')
    del row['updated_at']
    assert _card(row)['ageMs'] is None


def test_a_future_updated_at_clamps_the_age_to_zero():
    assert _card(_row('run-1', 'executing', updated_at=_iso(NOW + 60000)))['ageMs'] == 0


def test_the_board_module_reads_no_dom_and_no_clock():
    text = MODULE.read_text(encoding='utf-8')
    for pattern in (r'\bdocument\b', r'\bwindow\b', r'\bDate\.now\b', r'new Date\(', r'\bperformance\.now\b',
                    r'\binnerHTML\b', r'\beval\s*\(', r'https?://'):
        assert re.search(pattern, text) is None, pattern


def test_run_href_builds_the_query_with_the_encoded_run_and_token():
    assert _call({'op': 'runHref', 'runId': 'run-1', 'token': 'a b/c+d', 'pathname': '/live'}) == '/live?run=run-1&t=a%20b%2Fc%2Bd'
    assert _call({'op': 'runHref', 'runId': 'run_1.a-2', 'token': 't', 'pathname': '/live'}) == '/live?run=run_1.a-2&t=t'


@pytest.mark.parametrize('run_id', ['../x', 'a b', '', '-lead', '.hidden', 'a/b', 'a?b', None])
def test_run_href_is_null_for_an_unsafe_run_id(run_id):
    assert _call({'op': 'runHref', 'runId': run_id, 'token': 't', 'pathname': '/live'}) is None
