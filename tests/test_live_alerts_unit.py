'''Pure unit tests for the Simplicio Live page alert logic (issue #1406, slices 1406a and 1406b).

Since slice 1406b the run alerts come from the server as alert_snapshot, alert_raised and alert_cleared frames
(tests/test_dashboard_alerts_unit.py covers the rules). The page keeps only the connection rule (stream-lost),
applies the frames to a map of server alerts, and merges both lists, critical first. alerts.js and sse.js run in node.
'''
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LIVE = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'live'
MODULE = LIVE / 'alerts.js'
SSE = LIVE / 'sse.js'


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


SCRIPT = '''
import fs from 'node:fs';
import { activeAlerts, applyAlertFrame, browserNotice, connectionAlertsOf, diffAlerts, mergeAlerts } from %s;
import { createSseParser } from %s;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
let out;
if (input.op === 'frame') out = applyAlertFrame(input.current, input.name, input.payload);
else if (input.op === 'connection') out = connectionAlertsOf(input.connection);
else if (input.op === 'merge') out = mergeAlerts(input.server, input.connection);
else if (input.op === 'diff') out = diffAlerts(input.previous, input.current);
else if (input.op === 'notice') out = browserNotice(input.alert, input.settings, input.permission, input.silenced, input.now);
else if (input.op === 'active') out = activeAlerts(input.alerts, input.silenced, input.now);
else out = createSseParser().push(input.text);
process.stdout.write(JSON.stringify(out));
'''


def _call(payload):
    script = SCRIPT % (json.dumps(MODULE.as_uri()), json.dumps(SSE.as_uri()))
    proc = subprocess.run([_node(), '--input-type=module', '-e', script], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


GATE = {'id': 'gate-failing:evidence', 'rule': 'gate-failing', 'severity': 'warning', 'heading': 'Gate falhando: evidence',
        'why': 'teste falhou', 'ref': {'type': 'logs'}}
STALL = {'id': 'run-stalled', 'rule': 'run-stalled', 'severity': 'critical', 'heading': 'Run sem avanço',
         'why': 'parado', 'ref': {'type': 'logs'}}


def test_a_snapshot_replaces_every_server_alert():
    current = {'old': GATE}
    assert _call({'op': 'frame', 'current': current, 'name': 'alert_snapshot', 'payload': {'alerts': [STALL]}}) == {'run-stalled': STALL}


def test_a_raised_frame_adds_its_alert_and_a_cleared_frame_removes_it():
    after = _call({'op': 'frame', 'current': {}, 'name': 'alert_raised', 'payload': GATE})
    assert after == {'gate-failing:evidence': GATE}
    assert _call({'op': 'frame', 'current': after, 'name': 'alert_cleared', 'payload': {'id': 'gate-failing:evidence'}}) == {}


@pytest.mark.parametrize('name, payload', [
    ('alert_snapshot', {'alerts': 'not a list'}),
    ('alert_raised', {'why': 'no id'}),
    ('alert_cleared', {}),
    ('alert_unknown', GATE),
])
def test_a_malformed_or_unknown_frame_leaves_the_alerts_unchanged(name, payload):
    assert _call({'op': 'frame', 'current': {'run-stalled': STALL}, 'name': name, 'payload': payload}) == {'run-stalled': STALL}


def test_the_stream_lost_rule_is_the_only_connection_alert():
    assert _call({'op': 'connection', 'connection': 'stale'})[0]['id'] == 'stream-lost'
    assert _call({'op': 'connection', 'connection': 'offline'})[0]['id'] == 'stream-lost'
    assert _call({'op': 'connection', 'connection': 'live'}) == []
    assert _call({'op': 'connection', 'connection': 'connecting'}) == []


def test_the_merge_puts_critical_alerts_first_and_keeps_both_sources():
    merged = _call({'op': 'merge', 'server': {'gate-failing:evidence': GATE, 'run-stalled': STALL}, 'connection': 'stale'})
    assert [alert['id'] for alert in merged] == ['run-stalled', 'gate-failing:evidence', 'stream-lost']


def test_the_merge_of_nothing_is_empty():
    assert _call({'op': 'merge', 'server': {}, 'connection': 'live'}) == []


def test_diff_names_the_raised_and_the_cleared_ids():
    assert _call({'op': 'diff', 'previous': ['a', 'b'], 'current': ['b', 'c']}) == {'raised': ['c'], 'cleared': ['a']}


def test_a_silenced_alert_is_hidden_until_its_time_passes():
    alerts = [{'id': 'stream-lost'}, {'id': 'run-stalled'}]
    silenced = {'stream-lost': 2000}
    assert [a['id'] for a in _call({'op': 'active', 'alerts': alerts, 'silenced': silenced, 'now': 1000})] == ['run-stalled']
    assert [a['id'] for a in _call({'op': 'active', 'alerts': alerts, 'silenced': silenced, 'now': 2000})] == ['stream-lost', 'run-stalled']


def test_the_sse_parser_reports_the_name_of_a_named_frame():
    text = 'event: alert_raised\ndata: {"id":"run-stalled"}\n\n'
    out = _call({'op': 'parse', 'text': text})
    assert [item for item in out if item['type'] == 'event'] == [{'type': 'event', 'id': None, 'data': '{"id":"run-stalled"}', 'name': 'alert_raised'}]


def test_an_unnamed_frame_keeps_the_default_name():
    out = _call({'op': 'parse', 'text': 'data: {"seq":1}\n\n'})
    assert 'name' not in out[0]  # an unnamed frame keeps the item shape it always had


@pytest.mark.parametrize('path', [MODULE, LIVE / 'app.js', LIVE / 'alerts-view.js'])
def test_the_alert_sources_avoid_innerhtml_eval_and_absolute_urls(path):
    text = path.read_text(encoding='utf-8')
    for pattern in (r'\binnerHTML\b', r'\beval\s*\(', r'https?://'):
        assert re.search(pattern, text) is None, (path.name, pattern)


def test_the_app_wires_the_server_alert_frames_and_the_merge():
    text = (LIVE / 'app.js').read_text(encoding='utf-8')
    for needle in ('applyAlertFrame', 'mergeAlerts', 'onAlert', 'alert_snapshot'):
        assert needle in text, needle


def _notice(settings, permission='granted', silenced=None, now=1000):
    return _call({'op': 'notice', 'alert': GATE, 'settings': settings, 'permission': permission,
                  'silenced': silenced or {}, 'now': now})


def test_browser_notice_needs_the_config_flag_and_the_permission():
    on = {'browser_notifications': True, 'webhook': False}
    assert _notice(on) == {'title': GATE['heading'], 'body': GATE['why'], 'tag': GATE['id']}
    assert _notice({'browser_notifications': False}) is None
    assert _notice(None) is None
    assert _notice(on, permission='default') is None
    assert _notice(on, permission='denied') is None


def test_browser_notice_skips_a_silenced_alert():
    on = {'browser_notifications': True}
    assert _notice(on, silenced={GATE['id']: 2000}) is None
    assert _notice(on, silenced={GATE['id']: 500}) is not None
