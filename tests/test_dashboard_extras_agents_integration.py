'''GET /api/runs/<id>/extras carries the measured agent map and the token series (issue #1550), over a real socket.

The agent map is read from the Mapper operations store of the run's repo; the series comes from the run's token_usage events
written by the real emitter. A run with neither answers 200 with both fields UNVERIFIED or empty, never an error.
'''
import http.client
import json

import pytest

from simplicio_loop.agent_slots import AgentSlotRegistry
from simplicio_loop.dashboard import server
from simplicio_loop.dashboard_events import load

TOKEN = 'extras-agents-token-0123'
RUN_ID = 'run-agents'
TIMEOUT = 5


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch):
    monkeypatch.delenv('SIMPLICIO_MAPPER_OPERATIONS_DB', raising=False)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    run_dir = root / '.simplicio-loop' / 'loop-runs' / RUN_ID
    run_dir.mkdir(parents=True)
    state = {'run_id': RUN_ID, 'status': 'running', 'phase': 'executing', 'percent': 50, 'repo': str(root),
             'started_at': '2026-10-08T10:00:00Z', 'updated_at': '2026-10-08T10:00:00Z'}
    (run_dir / 'state.json').write_text(json.dumps(state), encoding='utf-8')
    return root


@pytest.fixture
def handle(repo):
    started = server.start(repo_root=repo, host='127.0.0.1', port=0, token=TOKEN)
    yield started
    started.stop()


def _extras(handle):
    conn = http.client.HTTPConnection('127.0.0.1', handle.port, timeout=TIMEOUT)
    try:
        conn.request('GET', '/api/runs/%s/extras' % RUN_ID, headers={'Authorization': 'Bearer ' + TOKEN})
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read())
    finally:
        conn.close()


def _emit_tokens(repo, *amounts):
    emitter = load()
    run_dir = repo / '.simplicio-loop' / 'loop-runs' / RUN_ID
    for tokens_in, tokens_out in amounts:
        emitter.emit(run_dir, 'token_usage', source='runner', strict=True, phase='executing',
                     payload={'input_tokens': tokens_in, 'output_tokens': tokens_out, 'model': 'claude-haiku-5-5'})


def test_a_run_with_no_store_and_no_usage_answers_200_with_unverified_agents_and_an_empty_series(handle):
    status, body = _extras(handle)
    assert status == 200
    assert body['agents']['state'] == 'UNVERIFIED' and body['agents']['reason'] == 'operations.sqlite ausente'
    assert body['agents']['instances'] == [] and body['agents']['slots']['state'] == 'UNVERIFIED'
    assert body['tokens_series'] == []


def test_the_reply_carries_the_instances_of_the_store_and_the_cumulative_token_series(repo, handle):
    database = repo / '.simplicio-loop' / 'data' / 'operations.sqlite'
    database.parent.mkdir()
    registry = AgentSlotRegistry(database, capacity=3)
    registry.initialize()
    registry.acquire('agent-a', worktree='/w/a', lease_id='lease-a')
    registry.start('agent-a')
    _emit_tokens(repo, (100, 20), (30, 0), (0, 50))
    status, body = _extras(handle)
    assert status == 200
    agents = body['agents']
    assert agents['state'] == 'MEASURED' and agents['slots'] == {'state': 'MEASURED', 'capacity': 3, 'used': 1, 'free': 2, 'reason': None}
    assert [(row['agent_id'], row['status'], row['lease_id']) for row in agents['instances']] == [('agent-a', 'running', 'lease-a')]
    assert agents['instances'][0]['heartbeat']['state'] == 'UNVERIFIED'
    assert [point['tokens'] for point in body['tokens_series']] == [120, 150, 200]
    assert all(isinstance(point['ts'], str) for point in body['tokens_series'])
