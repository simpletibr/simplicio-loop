'''Pure unit tests for the Simplicio Live alert rules (issue #1406, slice 1406a, TDD red).

alerts.js turns one selectView model into the alerts it implies, with a stable id per rule instance. It also diffs two
id lists into raised and cleared ids, and filters alerts the reader silenced. The module reads no DOM and no clock:
the model already carries the silence age. It runs in node.
'''
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'live' / 'alerts.js'
SILENCE_MS = 5 * 60 * 1000


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


SCRIPT = '''
import fs from 'node:fs';
import { alertsOf, diffAlerts, activeAlerts } from %s;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
let out;
if (input.op === 'alerts') out = alertsOf(input.model, input.options);
else if (input.op === 'diff') out = diffAlerts(input.previous, input.current);
else out = activeAlerts(input.alerts, input.silenced, input.now);
process.stdout.write(JSON.stringify(out));
'''


def _call(payload):
    script = SCRIPT % json.dumps(MODULE.as_uri())
    proc = subprocess.run([_node(), '--input-type=module', '-e', script], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _model(**overrides):
    model = {
        'connection': 'live', 'phase': 'executing',
        'rail': {'phase': 'executing', 'status': 'RUNNING', 'receiptReady': False},
        'gates': [{'gate': name, 'state': 'UNVERIFIED', 'reason': 'x', 'ref': None, 'at': None}
                  for name in ('evidence', 'watcher', 'oracle', 'dod', 'quality', 'action')],
        'health': {'eventsPerMinute': 3, 'heartbeatAgeMs': None,
                   'stall': {'detected': False, 'streak': 0, 'silenceMs': 1000}},
    }
    model.update(overrides)
    return model


def _alerts(model, silence_ms=SILENCE_MS):
    return _call({'op': 'alerts', 'model': model, 'options': {'silenceMs': silence_ms}})


def _ids(model, silence_ms=SILENCE_MS):
    return [alert['id'] for alert in _alerts(model, silence_ms)]


def test_a_healthy_run_raises_no_alert():
    assert _alerts(_model()) == []


def test_a_stall_detected_by_the_journal_is_critical_and_says_the_streak():
    model = _model(health={'eventsPerMinute': 0, 'heartbeatAgeMs': None, 'stall': {'detected': True, 'streak': 3, 'silenceMs': 1000}})
    alert = next(a for a in _alerts(model) if a['rule'] == 'run-stalled')
    assert alert['severity'] == 'critical'
    assert '3' in alert['why']


def test_a_failing_gate_raises_a_warning_named_by_the_gate():
    model = _model()
    model['gates'][1] = {'gate': 'watcher', 'state': 'FAIL', 'reason': 'verificação falhou', 'ref': 'evidence/w.json', 'at': None}
    alert = next(a for a in _alerts(model) if a['rule'] == 'gate-failing')
    assert alert['id'] == 'gate-failing:watcher'
    assert alert['severity'] == 'warning'
    assert alert['why'] == 'verificação falhou'


def test_a_silent_phase_past_the_threshold_links_to_its_phase_drill():
    model = _model(health={'eventsPerMinute': 0, 'heartbeatAgeMs': None, 'stall': {'detected': False, 'streak': 0, 'silenceMs': SILENCE_MS + 1}})
    alert = next(a for a in _alerts(model) if a['rule'] == 'phase-silent')
    assert alert['id'] == 'phase-silent:executing'
    assert alert['ref'] == {'type': 'phase', 'phase': 'executing'}


def test_a_silent_phase_below_the_threshold_raises_nothing():
    model = _model(health={'eventsPerMinute': 0, 'heartbeatAgeMs': None, 'stall': {'detected': False, 'streak': 0, 'silenceMs': SILENCE_MS - 1}})
    assert 'phase-silent:executing' not in _ids(model)


def test_no_silence_age_yet_is_not_an_alert():
    model = _model(health={'eventsPerMinute': 0, 'heartbeatAgeMs': None, 'stall': {'detected': False, 'streak': 0, 'silenceMs': None}})
    assert _ids(model) == []


def test_a_lost_stream_raises_a_warning():
    for state in ('stale', 'offline'):
        assert 'stream-lost' in _ids(_model(connection=state)), state


def test_an_unverified_oracle_at_the_end_of_the_run_raises_a_warning():
    model = _model(rail={'phase': 'done', 'status': 'RUNNING', 'receiptReady': True})
    model['gates'][2] = {'gate': 'oracle', 'state': 'UNVERIFIED', 'reason': 'sem recibo', 'ref': None, 'at': None}
    assert 'oracle-unverified' in _ids(model)


def test_an_oracle_that_is_still_running_is_not_an_alert():
    assert 'oracle-unverified' not in _ids(_model())


def test_alerts_are_critical_first_and_each_id_appears_once():
    model = _model(
        connection='stale',
        health={'eventsPerMinute': 0, 'heartbeatAgeMs': None, 'stall': {'detected': True, 'streak': 2, 'silenceMs': 1000}},
    )
    model['gates'][0] = {'gate': 'evidence', 'state': 'FAIL', 'reason': 'x', 'ref': None, 'at': None}
    alerts = _alerts(model)
    assert alerts[0]['severity'] == 'critical'
    ids = [alert['id'] for alert in alerts]
    assert len(ids) == len(set(ids))


def test_diff_names_the_raised_and_the_cleared_ids():
    assert _call({'op': 'diff', 'previous': ['a', 'b'], 'current': ['b', 'c']}) == {'raised': ['c'], 'cleared': ['a']}


def test_diff_of_nothing_raises_and_clears_nothing():
    assert _call({'op': 'diff', 'previous': [], 'current': []}) == {'raised': [], 'cleared': []}


def test_a_silenced_alert_is_hidden_until_its_time_passes():
    alerts = [{'id': 'stream-lost'}, {'id': 'run-stalled'}]
    silenced = {'stream-lost': 2000}
    assert [a['id'] for a in _call({'op': 'active', 'alerts': alerts, 'silenced': silenced, 'now': 1000})] == ['run-stalled']
    assert [a['id'] for a in _call({'op': 'active', 'alerts': alerts, 'silenced': silenced, 'now': 2000})] == ['stream-lost', 'run-stalled']


def test_the_module_passes_the_page_source_guards():
    import re
    text = MODULE.read_text(encoding='utf-8')
    for pattern in (r'\binnerHTML\b', r'\beval\s*\(', r'https?://', r'\bdocument\b', r'\bwindow\b', r'Date\.now'):
        assert re.search(pattern, text) is None, pattern


# Slice 1406a page wiring: the alert center is in the page and the app drives it from the pure rules.
LIVE = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'live'


def test_the_page_has_the_alert_center_with_its_toggle_list_and_status():
    html = (LIVE / 'index.html').read_text(encoding='utf-8')
    for needle in ('id="alerts-toggle"', 'aria-controls="alerts-panel"', 'id="alerts-panel"', 'id="alerts-list"', 'id="alerts-status"'):
        assert needle in html, needle


def test_the_app_drives_the_alert_center_from_the_pure_rules():
    text = (LIVE / 'app.js').read_text(encoding='utf-8')
    for needle in ('alertsOf', 'diffAlerts', 'activeAlerts', 'createAlertList', '/static/live/alerts.js', '/static/live/alerts-view.js'):
        assert needle in text, needle


def test_the_alert_list_renders_with_textcontent_only_and_passes_the_page_guards():
    import re
    assert (LIVE / 'alerts-view.js').is_file()
    text = (LIVE / 'alerts-view.js').read_text(encoding='utf-8')
    for pattern in (r'\binnerHTML\b', r'\beval\s*\(', r'https?://'):
        assert re.search(pattern, text) is None, pattern


# No false positives on a healthy stream: real events through the reducer, one alert check per tick.
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(REPO / 'scripts'))
import dashboard_events as de  # noqa: E402

DRIVER = REPO / 'tests' / 'fixtures' / 'live_pipeline' / 'driver.mjs'
RUN_ID = 'run-healthy'
BASE = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)


def _stamp(offset_s):
    moment = BASE + timedelta(seconds=offset_s)
    return moment.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (moment.microsecond // 1000)


def _healthy_steps():
    offsets = [0, 1] + [position * 30 for position in range(3, 15)]
    events = [de.build_envelope(run_id=RUN_ID, kind='phase_entered', source='runner', seq=1, ts=_stamp(offsets[0]),
                                iteration=None, payload={}, severity='info'),
              de.build_envelope(run_id=RUN_ID, kind='iteration_started', source='hook', seq=2, ts=_stamp(offsets[1]),
                                iteration=1, payload={'trigger': 'user_prompt'}, severity='info')]
    for position in range(3, 15):
        events.append(de.build_envelope(run_id=RUN_ID, kind='gate_evaluated', source='hook', seq=position,
                                        ts=_stamp(position * 30), iteration=1,
                                        payload={'gate': 'evidence', 'verdict': 'pass', 'message': 'ok'}, severity='info'))
    steps = []
    for evt, offset in zip(events, offsets):
        assert de.validate_envelope(evt) == [], evt['kind']
        steps.append({'action': {'type': 'event', 'event': evt}, 'now': int((BASE + timedelta(seconds=offset + 1)).timestamp() * 1000)})
    return steps


def test_a_healthy_six_minute_stream_raises_no_alert_at_any_tick():
    steps = _healthy_steps()
    proc = subprocess.run([_node(), str(DRIVER)], input=json.dumps({'steps': steps, 'runId': RUN_ID}),
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    views = json.loads(proc.stdout)
    assert len(views) == len(steps)
    for position, view in enumerate(views):
        assert _alerts(view) == [], (position, view['health'])
