'''System test: an expired lease in the backlog raises lease-expired on a real stream and renewal clears it (#1406).'''
import http.client
import json
import tempfile
import time
from pathlib import Path

import pytest

from simplicio_loop.dashboard import server
from simplicio_loop.dashboard_events import load

TOKEN = 'tok'
RUN = 'run-lease'


def _backlog(path, expires):
    lease = {'worker': 'w-1', 'heartbeat_at': '2026-01-01T00:00:00Z', 'expires_at': expires, 'ttl_seconds': 900}
    lines = [{'kind': 'master', 'revision': 1}, {'kind': 'item', 'id': 'T-1', 'status': 'running', 'lease': lease}]
    path.write_text('\n'.join(json.dumps(line) for line in lines), encoding='utf-8')


@pytest.fixture
def running(tmp_path, monkeypatch):
    root = Path(tempfile.mkdtemp(dir=tmp_path)) / 'repo'
    run_dir = root / '.simplicio-loop' / 'loop-runs' / RUN
    run_dir.mkdir(parents=True)
    (run_dir / 'state.json').write_text(json.dumps({'run_id': RUN, 'status': 'running', 'phase': 'executing',
                                                   'repo': str(root)}), encoding='utf-8')
    load().emit(run_dir, 'phase_entered', source='runner', phase='executing', strict=True)
    backlog = tmp_path / 'backlog.jsonl'
    _backlog(backlog, '2026-01-01T00:15:00Z')  # long past
    monkeypatch.setenv('SIMPLICIO_BACKLOG_FILE', str(backlog))
    handle = server.start(repo_root=str(root), host='127.0.0.1', port=0, token=TOKEN)
    try:
        yield handle, backlog
    finally:
        handle.stop()


def _frames(resp, want):
    name, data, seen = None, [], []
    while len(seen) < want:
        raw = resp.readline()
        assert raw, 'the stream closed early'
        line = raw.rstrip(b'\r\n').decode('utf-8')
        if line == '':
            if name and name.startswith('alert_'):
                seen.append((name, json.loads('\n'.join(data))))
            name, data = None, []
        elif line.startswith('event: '):
            name = line[7:]
        elif line.startswith('data: '):
            data.append(line[6:])
    return seen


def test_an_expired_lease_is_in_the_snapshot_and_renewing_it_clears_the_alert(running):
    handle, backlog = running
    conn = http.client.HTTPConnection('127.0.0.1', handle.port, timeout=10)
    conn.request('GET', '/api/runs/%s/events' % RUN, headers={'Authorization': 'Bearer ' + TOKEN})
    resp = conn.getresponse()
    try:
        (name, payload), = _frames(resp, 1)
        assert name == 'alert_snapshot'
        assert [a['id'] for a in payload['alerts']] == ['lease-expired:T-1']
        _backlog(backlog, '2999-01-01T00:00:00Z')
        started = time.monotonic()
        (name, payload), = _frames(resp, 1)
        assert (name, payload) == ('alert_cleared', {'id': 'lease-expired:T-1'})
        assert time.monotonic() - started < 2.5
    finally:
        conn.close()
