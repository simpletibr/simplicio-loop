'''Unit tests for the opt-in alert webhook (issue #1406). Off unless a URL is set; a failure never reaches the stream.'''
import http.server
import json
import threading

from simplicio_loop.dashboard import webhook

ALERT = {'id': 'run-stalled', 'rule': 'run-stalled', 'severity': 'critical', 'heading': 'Run sem avanço',
         'why': 'parado', 'ref': {'type': 'logs'}}


class _Sink(http.server.BaseHTTPRequestHandler):
    bodies: list = []

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        _Sink.bodies.append((self.headers.get('Content-Type'), self.rfile.read(length)))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


def _sink():
    _Sink.bodies = []
    srv = http.server.HTTPServer(('127.0.0.1', 0), _Sink)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_without_url_nothing_is_sent():
    sender = webhook.Sender(None)
    assert sender.send('run-1', ALERT) is False


def test_sends_once_per_run_and_alert_id():
    srv = _sink()
    try:
        sender = webhook.Sender('http://127.0.0.1:%d/hook' % srv.server_port, background=False)
        assert sender.send('run-1', ALERT) is True
        assert sender.send('run-1', ALERT) is False
        assert sender.send('run-2', ALERT) is True
        sender.clear('run-1', 'run-stalled')
        assert sender.send('run-1', ALERT) is True
    finally:
        srv.shutdown()
    assert len(_Sink.bodies) == 3
    ctype, raw = _Sink.bodies[0]
    assert ctype == 'application/json'
    body = json.loads(raw)
    assert body['run_id'] == 'run-1' and body['alert']['id'] == 'run-stalled'


def test_unreachable_url_is_swallowed():
    sender = webhook.Sender('http://127.0.0.1:1/hook', background=False)
    assert sender.send('run-1', ALERT) is True  # attempted; failure only recorded
    assert sender.failures == 1
