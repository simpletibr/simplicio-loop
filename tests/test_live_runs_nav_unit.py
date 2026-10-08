'''Pure unit tests for the Simplicio Live run navigation model (runs-nav.js), issue #1402 slice 4b-3.

runs-nav.js turns the run summaries of GET /api/runs into palette commands ("go to run"), picks the next run for the
TV rotation and builds the URL of a run keeping the other parameters. It runs in node: no DOM, no clock.
'''
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'live' / 'runs-nav.js'

SCRIPT = '''
import fs from 'node:fs';
import * as nav from %s;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
let out;
if (input.op === 'runCommands') out = nav.runCommands(input.runs, input.current);
else if (input.op === 'nextRunId') out = nav.nextRunId(input.runs, input.current);
else if (input.op === 'runUrl') out = nav.runUrl(input.pathname, input.search, input.runId);
else if (input.op === 'rotationMs') out = nav.rotationMs(input.search, input.reducedMotion);
else out = { TV_ROTATE_MS: nav.TV_ROTATE_MS };
process.stdout.write(JSON.stringify(out));
'''


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed')


def _call(payload):
    script = SCRIPT % json.dumps(MODULE.as_uri())
    proc = subprocess.run([_node(), '--input-type=module', '-e', script], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _runs(*ids):
    return [{'run_id': run_id, 'phase': 'executing'} for run_id in ids]


def test_run_commands_list_every_run_except_the_open_one():
    commands = _call({'op': 'runCommands', 'runs': _runs('a', 'b', 'c'), 'current': 'b'})
    assert [c['id'] for c in commands] == ['run:a', 'run:c']
    assert all(c['group'] == 'Runs' and c['label'].startswith('Run ') for c in commands)


def test_run_commands_drop_ids_that_are_not_plain_identifiers_and_non_lists():
    runs = _runs('ok', '../x', 'a b', '.hidden')
    assert [c['id'] for c in _call({'op': 'runCommands', 'runs': runs, 'current': ''})] == ['run:ok']
    assert _call({'op': 'runCommands', 'runs': None, 'current': ''}) == []


def test_next_run_wraps_around_and_falls_back_to_the_first():
    runs = _runs('a', 'b', 'c')
    assert _call({'op': 'nextRunId', 'runs': runs, 'current': 'a'}) == 'b'
    assert _call({'op': 'nextRunId', 'runs': runs, 'current': 'c'}) == 'a'
    assert _call({'op': 'nextRunId', 'runs': runs, 'current': 'gone'}) == 'a'


def test_next_run_is_null_with_fewer_than_two_runs():
    assert _call({'op': 'nextRunId', 'runs': _runs('a'), 'current': 'a'}) is None
    assert _call({'op': 'nextRunId', 'runs': [], 'current': 'a'}) is None


def test_run_url_changes_only_the_run_parameter():
    url = _call({'op': 'runUrl', 'pathname': '/', 'search': '?t=tok&theme=light&tv=1&run=a', 'runId': 'b'})
    assert url == '/?t=tok&theme=light&tv=1&run=b'


def test_rotation_runs_only_in_tv_mode_without_reduced_motion():
    default = _call({'op': 'constants'})['TV_ROTATE_MS']
    assert default == 20000
    assert _call({'op': 'rotationMs', 'search': '?tv=1', 'reducedMotion': False}) == default
    assert _call({'op': 'rotationMs', 'search': '', 'reducedMotion': False}) is None
    assert _call({'op': 'rotationMs', 'search': '?tv=1', 'reducedMotion': True}) is None


def test_rotation_interval_can_be_set_in_seconds_and_bad_values_fall_back():
    assert _call({'op': 'rotationMs', 'search': '?tv=1&rotate=2', 'reducedMotion': False}) == 2000
    for bad in ('0', '-3', 'x', '99999'):
        assert _call({'op': 'rotationMs', 'search': '?tv=1&rotate=' + bad, 'reducedMotion': False}) == 20000
