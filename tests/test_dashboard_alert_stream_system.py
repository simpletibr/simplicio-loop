'''System tests for the alert frames of the Simplicio Live stream (issue #1406, slice 1406b, TDD red).

A real dashboard server runs on loopback. The client reads the raw SSE frames of /api/runs/<run>/events. Each connection
starts with an alert_snapshot of the alerts active at that moment. A later change arrives as alert_raised or
alert_cleared, once per alert, and a reconnect replays the alerts that are still active.
'''
import http.client
import json
import tempfile
from pathlib import Path

import pytest

from simplicio_loop.dashboard import server
from simplicio_loop.dashboard_events import load

TOKEN = 'tok'
RUN = 'run-s1'
ALERT_FRAMES = ('alert_snapshot', 'alert_raised', 'alert_cleared')


@pytest.fixture
def running(tmp_path):
    root = Path(tempfile.mkdtemp(dir=tmp_path)) / 'repo'
    run_dir = root / '.simplicio-loop' / 'loop-runs' / RUN
    run_dir.mkdir(parents=True)
    (run_dir / 'state.json').write_text(json.dumps({'run_id': RUN, 'status': 'running', 'phase': 'executing',
                                                   'repo': str(root)}), encoding='utf-8')
    emitter = load()
    emitter.emit(run_dir, 'phase_entered', source='runner', phase='executing', strict=True)
    handle = server.start(repo_root=str(root), host='127.0.0.1', port=0, token=TOKEN)
    try:
        yield handle, run_dir, emitter
    finally:
        handle.stop()


def _open(port, cursor=None):
    headers = {'Authorization': 'Bearer ' + TOKEN}
    if cursor is not None:
        headers['Last-Event-ID'] = str(cursor)
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    conn.request('GET', '/api/runs/%s/events' % RUN, headers=headers)
    resp = conn.getresponse()
    assert resp.status == 200, resp.status
    return conn, resp


def _alert_frame(resp):
    '''The next alert frame on the stream: (event name, decoded data).'''
    while True:
        name, data = None, []
        while True:
            raw = resp.readline()
            assert raw, 'the stream closed before an alert frame arrived'
            line = raw.rstrip(b'\r\n').decode('utf-8')
            if line == '':
                break
            if line.startswith(':') or line.startswith('retry:') or line.startswith('id:'):
                continue
            if line.startswith('event: '):
                name = line[len('event: '):]
            elif line.startswith('data: '):
                data.append(line[len('data: '):])
        if name in ALERT_FRAMES:
            return name, json.loads('\n'.join(data))


def _gate(emitter, run_dir, gate, verdict, message=''):
    emitter.emit(run_dir, 'gate_evaluated', source='hook', phase='executing', iteration=1,
                 payload={'gate': gate, 'verdict': verdict, 'message': message}, strict=True)


def test_a_new_connection_starts_with_the_active_alerts_and_none_when_healthy(running):
    handle, _, _ = running
    conn, resp = _open(handle.port)
    try:
        name, payload = _alert_frame(resp)
    finally:
        conn.close()
    assert name == 'alert_snapshot'
    assert payload == {'alerts': []}


def test_a_failing_gate_is_raised_once_and_cleared_by_a_pass(running):
    handle, run_dir, emitter = running
    conn, resp = _open(handle.port)
    try:
        assert _alert_frame(resp)[0] == 'alert_snapshot'
        _gate(emitter, run_dir, 'evidence', 'fail', 'teste falhou')
        name, payload = _alert_frame(resp)
        assert name == 'alert_raised'
        assert payload['id'] == 'gate-failing:evidence'
        assert payload['severity'] == 'warning'
        assert payload['why'] == 'teste falhou'
        _gate(emitter, run_dir, 'evidence', 'fail', 'teste falhou de novo')
        _gate(emitter, run_dir, 'evidence', 'pass')
        name, payload = _alert_frame(resp)
        assert (name, payload) == ('alert_cleared', {'id': 'gate-failing:evidence'}), 'the repeat must not raise twice'
    finally:
        conn.close()


def test_a_reconnect_replays_the_alerts_that_are_still_active(running):
    handle, run_dir, emitter = running
    _gate(emitter, run_dir, 'evidence', 'fail', 'teste falhou')
    conn, resp = _open(handle.port)
    try:
        name, payload = _alert_frame(resp)
    finally:
        conn.close()
    assert name == 'alert_snapshot'
    assert [alert['id'] for alert in payload['alerts']] == ['gate-failing:evidence']


# Latency (issue #1406, the 2-second target): the time from the event being written to its alert frame arriving.
LATENCY_LIMIT_S = 2.0
CYCLES = 5


def _latency_run(tmp_path, status):
    root = Path(tempfile.mkdtemp(dir=tmp_path)) / 'repo'
    run_dir = root / '.simplicio-loop' / 'loop-runs' / RUN
    run_dir.mkdir(parents=True)
    (run_dir / 'state.json').write_text(json.dumps({'run_id': RUN, 'status': status, 'phase': 'executing',
                                                   'repo': str(root)}), encoding='utf-8')
    emitter = load()
    emitter.emit(run_dir, 'phase_entered', source='runner', phase='executing', strict=True)
    return root, run_dir, emitter


@pytest.mark.parametrize('status', ['running', 'done'])
def test_an_alert_frame_arrives_within_two_seconds_after_the_event(tmp_path, status):
    import time
    _, run_dir, emitter = _latency_run(tmp_path, status)
    handle = server.start(repo_root=str(run_dir.parents[2]), host='127.0.0.1', port=0, token=TOKEN)
    latencies = []
    try:
        conn, resp = _open(handle.port)
        try:
            assert _alert_frame(resp)[0] == 'alert_snapshot'
            for _ in range(CYCLES):
                started = time.monotonic()
                _gate(emitter, run_dir, 'evidence', 'fail', 'teste falhou')
                assert _alert_frame(resp)[0] == 'alert_raised'
                latencies.append(time.monotonic() - started)
                started = time.monotonic()
                _gate(emitter, run_dir, 'evidence', 'pass')
                assert _alert_frame(resp)[0] == 'alert_cleared'
                latencies.append(time.monotonic() - started)
        finally:
            conn.close()
    finally:
        handle.stop()
    assert max(latencies) < LATENCY_LIMIT_S, ('status=%s latencies=%s' % (status, [round(v, 3) for v in latencies]))


def _toml(root, text):
    path = root / '.simplicio-loop' / 'dashboard.toml'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def test_configured_silence_threshold_raises_the_silent_phase_alert(tmp_path):
    root, run_dir, _ = _latency_run(tmp_path, 'running')
    _toml(root, '[alerts]\nphase_silence_minutes = 0.01\n')
    handle = server.start(repo_root=str(root), host='127.0.0.1', port=0, token=TOKEN)
    try:
        conn, resp = _open(handle.port)
        try:
            assert _alert_frame(resp)[0] == 'alert_snapshot'
            name, alert = _alert_frame(resp)
            assert name == 'alert_raised' and alert['rule'] == 'phase-silent'
        finally:
            conn.close()
    finally:
        handle.stop()


def test_api_config_reports_flags_without_the_webhook_url(tmp_path):
    root, _, _ = _latency_run(tmp_path, 'running')
    _toml(root, '[notifications]\nbrowser = true\n\n[webhook]\nurl = "http://127.0.0.1:1/secret-path"\n')
    handle = server.start(repo_root=str(root), host='127.0.0.1', port=0, token=TOKEN)
    try:
        conn = http.client.HTTPConnection('127.0.0.1', handle.port, timeout=5)
        conn.request('GET', '/api/runs/%s/config' % RUN, headers={'Authorization': 'Bearer ' + TOKEN})
        resp = conn.getresponse()
        raw = resp.read()
        assert resp.status == 200
        assert json.loads(raw) == {'browser_notifications': True, 'webhook': True}
        assert b'secret-path' not in raw
    finally:
        handle.stop()


def test_webhook_receives_a_raised_alert_once(tmp_path):
    import http.server
    import threading
    got = []

    class Sink(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            got.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    sink = http.server.HTTPServer(('127.0.0.1', 0), Sink)
    threading.Thread(target=sink.serve_forever, daemon=True).start()
    root, run_dir, emitter = _latency_run(tmp_path, 'running')
    _toml(root, '[webhook]\nurl = "http://127.0.0.1:%d/h"\n' % sink.server_port)
    handle = server.start(repo_root=str(root), host='127.0.0.1', port=0, token=TOKEN)
    try:
        conn, resp = _open(handle.port)
        try:
            assert _alert_frame(resp)[0] == 'alert_snapshot'
            _gate(emitter, run_dir, 'evidence', 'fail', 'teste falhou')
            assert _alert_frame(resp)[0] == 'alert_raised'
            import time
            deadline = time.monotonic() + 3
            while not got and time.monotonic() < deadline:
                time.sleep(0.05)
        finally:
            conn.close()
    finally:
        handle.stop()
        sink.shutdown()
    assert len(got) == 1 and got[0]['alert']['id'] == 'gate-failing:evidence' and got[0]['run_id'] == RUN
