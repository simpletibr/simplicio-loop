'''Lane heartbeat from the Mapper OperationsStore (issue #1546).

The runner's worker_claimed lease_id is an ``ops_leases`` id of the Mapper store at ``<repo>/.simplicio-loop/data/
operations.sqlite``, a namespace the backlog leases never use. These tests build a REAL OperationsStore with the mapper's
own API (claim, heartbeat) and a run directory under the same ``.simplicio-loop``, then read the lane heartbeat through
``lane_extras.extras``. Every UNVERIFIED case keeps its reason; the store is only ever opened read-only.
'''
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from simplicio_mapper.store import OperationsStore

from simplicio_loop.dashboard import lane_extras

EVENT_SCHEMA = 'simplicio.dashboard-event/v1'


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv('SIMPLICIO_MAPPER_OPERATIONS_DB', raising=False)
    monkeypatch.delenv('SIMPLICIO_BACKLOG_FILE', raising=False)


@pytest.fixture
def loop_home(tmp_path):
    home = tmp_path / 'repo' / '.simplicio-loop'
    (home / 'data').mkdir(parents=True)
    run_dir = home / 'loop-runs' / 'run-1'
    run_dir.mkdir(parents=True)
    return home, run_dir


def _claim(home, task_id='T1', worker='w1', lease_seconds=30.0):
    '''A real claim through the mapper API; returns the store, the claim and the db path.'''
    store = OperationsStore(home / 'data' / 'operations.sqlite')
    store.initialize()
    store.register_slot('default', 8)
    store.enqueue(task_id, {'goal': task_id}, idempotency_key=f'key-{task_id}')
    claim = store.claim(worker, task_id=task_id, lease_seconds=lease_seconds)
    assert claim and len(claim['lease_id']) == 32
    return store, claim


def _heartbeat_of(home, lease_id):
    with sqlite3.connect(home / 'data' / 'operations.sqlite') as con:
        return con.execute('SELECT heartbeat_at FROM ops_leases WHERE lease_id=?', (lease_id,)).fetchone()[0]


def _claimed(seq, lane, lease_id, task_id='T1'):
    return {'schema': EVENT_SCHEMA, 'seq': seq, 'kind': 'worker_claimed', 'lane': lane, 'task_id': task_id,
            'ts': f'2026-10-08T10:00:{seq:02d}Z', 'payload': {'lease_id': lease_id}}


def _lanes(run_dir, events, now):
    return lane_extras.extras(run_dir, events, now=now)['heartbeat']


def _row(run_dir, lease_id, now):
    return _lanes(run_dir, [_claimed(1, 'lane-a', lease_id)], now)['lanes'][0]


def test_a_real_store_lease_gives_a_measured_heartbeat_with_its_age(loop_home):
    home, run_dir = loop_home
    _, claim = _claim(home)
    beat = _heartbeat_of(home, claim['lease_id'])
    got = _lanes(run_dir, [_claimed(1, 'lane-a', claim['lease_id'])], beat + 12.9)
    row = got['lanes'][0]
    assert got['state'] == 'PASS'
    assert (row['state'], row['age_s'], row['stale'], row['reason']) == ('MEASURED', 12, False, None)
    assert row['lease_id'] == claim['lease_id']
    assert row['heartbeat_at'] == time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(beat))


def test_each_lane_reads_its_own_lease_and_a_heartbeat_moves_the_age(loop_home):
    home, run_dir = loop_home
    store, first = _claim(home, 'T1')
    _, second = _claim(home, 'T2', worker='w2')
    assert second['lease_id'] != first['lease_id']
    events = [_claimed(1, 'lane-a', first['lease_id'], 'T1'), _claimed(2, 'lane-b', second['lease_id'], 'T2')]
    now = max(_heartbeat_of(home, first['lease_id']), _heartbeat_of(home, second['lease_id'])) + 5
    before = {r['lane']: r['age_s'] for r in _lanes(run_dir, events, now)['lanes']}
    time.sleep(1.1)
    store.heartbeat(first['attempt_id'], first['fence_token'], lease_seconds=30.0)
    beat = _heartbeat_of(home, first['lease_id'])
    after = {r['lane']: r['age_s'] for r in _lanes(run_dir, events, beat + 2)['lanes']}
    assert before['lane-a'] >= 5 and after['lane-a'] == 2
    assert after['lane-b'] > after['lane-a']


def test_the_store_path_can_come_from_the_runner_env_variable(loop_home, tmp_path, monkeypatch):
    home, _ = loop_home
    _, claim = _claim(home)
    elsewhere = tmp_path / 'elsewhere' / 'run-9'
    elsewhere.mkdir(parents=True)
    monkeypatch.setenv('SIMPLICIO_MAPPER_OPERATIONS_DB', str(home / 'data' / 'operations.sqlite'))
    beat = _heartbeat_of(home, claim['lease_id'])
    assert _row(elsewhere, claim['lease_id'], beat + 7)['age_s'] == 7


def test_a_beaten_lease_goes_stale_at_half_its_ttl_and_a_released_one_is_measured_stale(loop_home):
    home, run_dir = loop_home
    store, claim = _claim(home, lease_seconds=30.0)
    time.sleep(1.1)
    store.heartbeat(claim['attempt_id'], claim['fence_token'], lease_seconds=30.0)
    beat = _heartbeat_of(home, claim['lease_id'])
    assert _row(run_dir, claim['lease_id'], beat + 10)['stale'] is False
    late = _row(run_dir, claim['lease_id'], beat + 20)   # past half the 30 s ttl
    assert (late['stale'], late['beat']) == (True, True)
    assert _lanes(run_dir, [_claimed(1, 'lane-a', claim['lease_id'])], beat + 20)['reason'] == (
        'lane-a: último batimento há 20 s (obsoleto)')
    store.release(claim['attempt_id'], claim['fence_token'])
    row = _row(run_dir, claim['lease_id'], beat + 1)
    assert (row['state'], row['age_s'], row['stale']) == ('MEASURED', 1, True)


def test_a_claim_nobody_beats_says_so_and_is_not_called_stale_at_half_its_ttl(loop_home):
    """The runner claims once and never heartbeats (issue #1546 review): a healthy worker must not read as an alarm."""
    home, run_dir = loop_home
    _, claim = _claim(home, lease_seconds=60.0)
    beat = _heartbeat_of(home, claim['lease_id'])
    got = _lanes(run_dir, [_claimed(1, 'lane-a', claim['lease_id'])], beat + 45)
    row = got['lanes'][0]
    assert (row['state'], row['age_s'], row['beat'], row['stale']) == ('MEASURED', 45, False, False)
    assert got['reason'] == 'lane-a: sem batimento registrado desde o claim (claim há 45 s)'
    expired = _lanes(run_dir, [_claimed(1, 'lane-a', claim['lease_id'])], beat + 61)
    assert expired['lanes'][0]['stale'] is True
    assert expired['reason'] == 'lane-a: sem batimento registrado desde o claim (claim há 61 s) (lease expirado)'


def test_no_store_file_is_unverified_with_the_reason(loop_home):
    _, run_dir = loop_home
    row = _row(run_dir, 'a' * 32, time.time())
    assert (row['state'], row['age_s'], row['heartbeat_at']) == ('UNVERIFIED', None, None)
    assert 'operations.sqlite ausente' in row['reason']


def test_a_run_dir_outside_any_loop_home_has_no_store_and_keeps_the_backlog_reason(tmp_path):
    row = _row(tmp_path, 'a' * 32, time.time())
    assert row['state'] == 'UNVERIFIED' and 'backlog não lido' in row['reason']
    assert 'operations.sqlite' not in row['reason']


def test_a_lease_id_absent_from_the_store_is_unverified(loop_home):
    home, run_dir = loop_home
    _claim(home)
    row = _row(run_dir, 'f' * 32, time.time())
    assert (row['state'], row['age_s']) == ('UNVERIFIED', None)
    assert f"lease {'f' * 32} não está no store de operações" in row['reason']


def test_a_lane_with_no_lease_id_stays_unverified_without_touching_the_store(loop_home):
    _, run_dir = loop_home
    row = _row(run_dir, '', time.time())
    assert (row['state'], row['reason']) == ('UNVERIFIED', 'lane sem lease_id registrado')


def test_a_locked_store_is_unverified_with_a_reason_not_a_crash(loop_home):
    home, run_dir = loop_home
    _, claim = _claim(home)
    db = home / 'data' / 'operations.sqlite'
    with sqlite3.connect(db) as con:
        con.execute('PRAGMA journal_mode=DELETE')
    holder = sqlite3.connect(db, isolation_level=None)
    holder.execute('BEGIN EXCLUSIVE')
    try:
        row = _row(run_dir, claim['lease_id'], time.time())
    finally:
        holder.execute('ROLLBACK')
        holder.close()
    assert (row['state'], row['age_s']) == ('UNVERIFIED', None)
    assert 'locked' in row['reason']
    assert _row(run_dir, claim['lease_id'], time.time())['state'] == 'MEASURED'   # readable again once released


def test_a_corrupt_store_is_unverified_with_a_reason_not_a_crash(loop_home):
    home, run_dir = loop_home
    (home / 'data' / 'operations.sqlite').write_bytes(b'this is not a sqlite database' * 50)
    row = _row(run_dir, 'a' * 32, time.time())
    assert (row['state'], row['age_s']) == ('UNVERIFIED', None)
    assert 'store não lido' in row['reason']


def test_a_store_without_the_leases_table_is_unverified(loop_home):
    home, run_dir = loop_home
    sqlite3.connect(home / 'data' / 'operations.sqlite').close()
    row = _row(run_dir, 'a' * 32, time.time())
    assert row['state'] == 'UNVERIFIED' and 'ops_leases' in row['reason']


def test_a_future_store_heartbeat_is_unverified(loop_home):
    home, run_dir = loop_home
    _, claim = _claim(home)
    beat = _heartbeat_of(home, claim['lease_id'])
    row = _row(run_dir, claim['lease_id'], beat - 500)
    assert (row['state'], row['age_s'], row['reason']) == ('UNVERIFIED', None, 'heartbeat_at no futuro do relógio')


def test_a_lease_id_held_by_two_backlog_items_stays_ambiguous_even_if_the_store_has_it(loop_home):
    home, run_dir = loop_home
    _, claim = _claim(home)
    lease = {'worker': 'w', 'lease_id': claim['lease_id'], 'heartbeat_at': '2026-10-08T10:00:00Z',
             'expires_at': '2099-01-01T00:00:00Z', 'ttl_seconds': 900}
    lines = [json.dumps({'kind': 'master', 'revision': 1})] + [
        json.dumps({'kind': 'item', 'id': i, 'status': 'running', 'lease': lease}) for i in ('T1', 'T2')]
    backlog = run_dir / 'backlog.jsonl'
    backlog.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    got = lane_extras.extras(run_dir, [_claimed(1, 'lane-a', claim['lease_id'])], backlog_path=backlog,
                             now=time.time())['heartbeat']['lanes'][0]
    assert got['state'] == 'UNVERIFIED' and 'mais de um item do backlog' in got['reason']


@pytest.mark.parametrize('hostile', ["x' OR '1'='1", "'; DROP TABLE ops_leases; --", '../../../etc/passwd',
                                     'a%00b', '%', 'é' * 40])
def test_an_untrusted_lease_id_is_only_ever_a_bound_parameter(loop_home, hostile):
    home, run_dir = loop_home
    _, claim = _claim(home)
    row = _row(run_dir, hostile, time.time())
    assert (row['state'], row['age_s']) == ('UNVERIFIED', None)
    beat = _heartbeat_of(home, claim['lease_id'])   # table still there, the real lease untouched
    assert _row(run_dir, claim['lease_id'], beat + 3)['age_s'] == 3


def test_reading_never_writes_the_store(loop_home):
    home, run_dir = loop_home
    _, claim = _claim(home)
    db = home / 'data' / 'operations.sqlite'
    with sqlite3.connect(db) as con:
        con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    before = (hashlib.sha256(db.read_bytes()).hexdigest(), db.stat().st_mtime_ns)
    for _ in range(3):
        assert _row(run_dir, claim['lease_id'], time.time())['state'] == 'MEASURED'
    assert (hashlib.sha256(db.read_bytes()).hexdigest(), db.stat().st_mtime_ns) == before


def test_a_missing_store_is_never_created_by_the_dashboard(loop_home):
    home, run_dir = loop_home
    _row(run_dir, 'a' * 32, time.time())
    assert not (home / 'data' / 'operations.sqlite').exists()


def _files(directory):
    return {p.name: (p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(directory.iterdir())}


def test_reading_an_idle_wal_store_creates_no_wal_or_shm_sidecar(loop_home):
    """The Mapper store is WAL and closes between operations, so it sits with no sidecars; mode=ro alone would create them."""
    home, run_dir = loop_home
    _, claim = _claim(home)
    data = home / 'data'
    assert sorted(p.name for p in data.iterdir() if p.name.endswith(('-wal', '-shm'))) == []
    before = _files(data)
    for _ in range(3):
        assert _row(run_dir, claim['lease_id'], time.time())['state'] == 'MEASURED'
    assert _files(data) == before


def test_reading_a_wal_store_a_writer_holds_open_leaves_its_db_and_wal_untouched(loop_home):
    home, run_dir = loop_home
    _, claim = _claim(home)
    db = home / 'data' / 'operations.sqlite'
    writer = sqlite3.connect(db, isolation_level=None)
    try:
        assert writer.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        writer.execute('BEGIN IMMEDIATE')
        writer.execute('UPDATE ops_leases SET heartbeat_at = heartbeat_at + 1 WHERE lease_id = ?', (claim['lease_id'],))
        writer.execute('COMMIT')   # the new beat lives in the -wal only
        names = {p.name for p in (home / 'data').iterdir()}
        assert {'operations.sqlite-wal', 'operations.sqlite-shm'} <= names
        before = _files(home / 'data')
        beat = writer.execute('SELECT heartbeat_at FROM ops_leases').fetchone()[0]
        row = _row(run_dir, claim['lease_id'], beat + 4)
        assert (row['state'], row['age_s']) == ('MEASURED', 4)   # the reader sees the committed -wal frame
        after = _files(home / 'data')
        # -shm is the WAL's shared coordination memory: a live reader must register in it, so its bytes may move.
        assert {n: v for n, v in after.items() if not n.endswith('-shm')} == {
            n: v for n, v in before.items() if not n.endswith('-shm')}
        assert after['operations.sqlite-shm'][0] == before['operations.sqlite-shm'][0]
    finally:
        writer.close()


def test_a_store_that_is_not_openable_costs_one_timeout_for_all_lanes_not_one_each(loop_home):
    home, run_dir = loop_home
    (home / 'data' / 'operations.sqlite').write_bytes(b'this is not a sqlite database' * 50)
    events = [_claimed(i, f'lane-{i:02d}', f'{i:032x}') for i in range(1, 41)]
    started = time.monotonic()
    got = _lanes(run_dir, events, time.time())
    assert time.monotonic() - started < 2.0
    assert len(got['lanes']) == 40 and {r['state'] for r in got['lanes']} == {'UNVERIFIED'}
    assert all('store não lido' in r['reason'] for r in got['lanes'])


def test_a_lease_id_that_is_not_valid_text_is_unverified_not_a_crash(loop_home):
    home, run_dir = loop_home
    _claim(home)
    row = _row(run_dir, '\ud800', time.time())   # json.loads('"\\ud800"') yields a lone surrogate
    assert row['state'] == 'UNVERIFIED' and row['reason'].endswith('lease_id não é texto válido')


@pytest.mark.parametrize('weird', ['a?b#c', 'p%41 x', 'sp ace', 'çã日本', 'q=1&mode=rw&x'])
def test_a_run_dir_with_uri_special_characters_still_opens_the_right_file_read_only(tmp_path, weird):
    home = tmp_path / weird / '.simplicio-loop'
    (home / 'data').mkdir(parents=True)
    run_dir = home / 'loop-runs' / 'r'
    run_dir.mkdir(parents=True)
    _, claim = _claim(home)
    beat = _heartbeat_of(home, claim['lease_id'])
    assert _row(run_dir, claim['lease_id'], beat + 2)['age_s'] == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == [weird]   # nothing created beside the run dir


def test_the_connection_is_opened_read_only_so_a_write_through_it_fails(loop_home):
    home, _ = loop_home
    _claim(home)
    db = home / 'data' / 'operations.sqlite'
    handle = lane_extras._Store(db)
    try:
        con = handle._connect()
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            con.execute('UPDATE ops_leases SET heartbeat_at = 0')
    finally:
        handle.close()


RUNNER_CLAIM = (
    'import sys; from pathlib import Path; from simplicio_loop import runner\n'
    'repo = Path(sys.argv[1]); runner._ensure_mapper_operations_store(repo, "mapper")\n'
    '_, attempt = runner._claim_mapper_operation_attempt(repo, run_id="r1", task_index=1, task_id="T1",\n'
    '                                                     worker_id="w", targets=["a.py"])\n'
    'print(attempt.lease.lease_id)\n'
)


def test_the_lease_the_real_runner_claims_is_found_at_the_derived_store_path(tmp_path):
    """End to end: the runner's own claim path (repo source of the mapper, as shipped) writes the lease_id that its
    worker_claimed event carries; the dashboard finds it at <repo>/.simplicio-loop/data/operations.sqlite."""
    root = Path(__file__).resolve().parent.parent
    env = {k: v for k, v in os.environ.items() if not k.startswith('SIMPLICIO_')}
    env['PYTHONPATH'] = os.pathsep.join([str(root), str(root / 'packages' / 'mapper')])
    repo = tmp_path / 'repo'
    repo.mkdir()
    done = subprocess.run([sys.executable, '-c', RUNNER_CLAIM, str(repo)], env=env, capture_output=True, text=True,
                          timeout=120, cwd=tmp_path)
    assert done.returncode == 0, done.stderr[-800:]
    lease_id = done.stdout.strip().splitlines()[-1]
    run_dir = repo / '.simplicio-loop' / 'loop-runs' / 'r1'
    run_dir.mkdir(parents=True)
    row = _row(run_dir, lease_id, time.time() + 4)
    assert (row['state'], row['stale'], row['reason']) == ('MEASURED', False, None)
    assert 3 <= row['age_s'] <= 6
