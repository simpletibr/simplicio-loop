'''Measured agent map of a run (issue #1550): agent instances, slots, leases and heartbeat from the Mapper OperationsStore.

The store is built by the real AgentSlotRegistry (so the DDL is the Mapper's), and the leases are rows of the real tables.
The reader opens the store read-only: nothing is created or written. Everything the store did not record is UNVERIFIED with
the reason.
'''
import os
import sqlite3

import pytest

from simplicio_loop.agent_slots import AgentSlotRegistry
from simplicio_loop.dashboard import agent_map

NOW = 1_800_000_000.0
STAMP = '2026-10-10T00:00:00Z'


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch):
    monkeypatch.delenv('SIMPLICIO_MAPPER_OPERATIONS_DB', raising=False)


@pytest.fixture
def run(tmp_path):
    root = tmp_path / '.simplicio-loop'
    run_dir = root / 'loop-runs' / 'run-1'
    run_dir.mkdir(parents=True)
    (root / 'data').mkdir()
    return run_dir, root / 'data' / 'operations.sqlite'


def _registry(database, capacity=4):
    registry = AgentSlotRegistry(database, capacity=capacity)
    registry.initialize()
    return registry


def _lease(database, lease_id, beat, expires, state='active'):
    con = sqlite3.connect(database)
    try:
        con.execute("INSERT INTO ops_tasks VALUES (?, ?, '{}', 'running', 0, 0, 0, ?, ?)", ('t-' + lease_id, 'k-' + lease_id, STAMP, STAMP))
        con.execute("INSERT INTO ops_attempts VALUES (?, ?, 'w', 'f', 'running', ?, ?)", ('a-' + lease_id, 't-' + lease_id, STAMP, STAMP))
        con.execute("INSERT INTO ops_leases VALUES (?, ?, 'w', 'f', 's', ?, ?, ?)", (lease_id, 'a-' + lease_id, state, beat, expires))
        con.commit()
    finally:
        con.close()


def test_a_run_without_a_store_file_is_unverified_with_the_reason(run):
    run_dir, _ = run
    out = agent_map.view(run_dir, NOW)
    assert out['state'] == 'UNVERIFIED' and out['reason'] == 'operations.sqlite ausente'
    assert out['slots']['state'] == 'UNVERIFIED' and out['slots']['capacity'] is None and out['slots']['used'] is None
    assert out['instances'] == [] and out['instances_total'] == 0 and out['counts'] == {}


def test_a_run_outside_a_simplicio_loop_tree_has_no_store_to_read(tmp_path):
    out = agent_map.view(tmp_path, NOW)
    assert out['state'] == 'UNVERIFIED' and out['reason'] == agent_map.NO_STORE


def test_the_environment_override_points_at_the_store(tmp_path, monkeypatch):
    database = tmp_path / 'elsewhere.sqlite'
    registry = _registry(database)
    registry.acquire('agent-a')
    monkeypatch.setenv('SIMPLICIO_MAPPER_OPERATIONS_DB', str(database))
    out = agent_map.view(tmp_path, NOW)
    assert out['state'] == 'MEASURED' and [row['agent_id'] for row in out['instances']] == ['agent-a']


def test_a_file_that_is_not_a_store_is_unverified_with_the_sqlite_reason(run):
    run_dir, database = run
    database.write_bytes(b'this is not sqlite' * 100)
    out = agent_map.view(run_dir, NOW)
    assert out['state'] == 'UNVERIFIED' and out['reason'].startswith('store não lido')


def test_a_store_with_no_agent_table_is_unverified_with_the_reason(run):
    run_dir, database = run
    sqlite3.connect(database).close()
    out = agent_map.view(run_dir, NOW)
    assert out['state'] == 'UNVERIFIED' and 'ops_agent_slots' in out['reason']


def test_a_store_with_no_agent_is_unverified_and_says_so(run):
    run_dir, database = run
    _registry(database)
    out = agent_map.view(run_dir, NOW)
    assert out['state'] == 'UNVERIFIED' and out['reason'] == agent_map.NO_AGENTS
    assert out['slots']['state'] == 'UNVERIFIED'


def test_instances_slots_and_counts_come_from_the_store(run):
    run_dir, database = run
    registry = _registry(database, capacity=4)
    registry.acquire('agent-a', worktree='/w/a', lease_id='lease-a')
    registry.start('agent-a')
    registry.acquire('agent-b')
    registry.acquire('agent-c')
    registry.start('agent-c')
    registry.close_agent('agent-c')
    out = agent_map.view(run_dir, NOW)
    assert out['state'] == 'MEASURED' and out['reason'] is None
    assert out['counts'] == {'pending': 1, 'running': 1, 'completed': 1, 'shutdown': 0, 'reclaimable': 0}
    assert out['slots'] == {'state': 'MEASURED', 'capacity': 4, 'used': 2, 'free': 2, 'reason': None}
    assert [(row['agent_id'], row['status'], row['attempt']) for row in out['instances']] == [
        ('agent-a', 'running', 1), ('agent-b', 'pending', 1), ('agent-c', 'completed', 1)]
    first = out['instances'][0]
    assert first['worktree'] == '/w/a' and first['lease_id'] == 'lease-a'
    assert out['instances_total'] == 3


def test_a_store_without_the_capacity_row_still_lists_the_instances_and_flags_the_slots(run):
    run_dir, database = run
    _registry(database).acquire('agent-a')
    con = sqlite3.connect(database)
    con.execute("DELETE FROM operations_meta WHERE key = 'agent_slot_capacity'")
    con.commit()
    con.close()
    out = agent_map.view(run_dir, NOW)
    assert out['state'] == 'MEASURED' and len(out['instances']) == 1
    assert out['slots'] == {'state': 'UNVERIFIED', 'capacity': None, 'used': None, 'free': None, 'reason': agent_map.NO_CAPACITY}


def test_a_full_house_has_no_free_slot_and_never_a_negative_one(run):
    run_dir, database = run
    registry = _registry(database, capacity=1)
    registry.acquire('agent-a')
    con = sqlite3.connect(database)
    con.execute("INSERT INTO ops_agent_slots VALUES ('agent-z', 'running', 1, NULL, NULL, 0, 0, 0, NULL, ?, ?)", (STAMP, STAMP))
    con.commit()
    con.close()
    slots = agent_map.view(run_dir, NOW)['slots']
    assert slots['capacity'] == 1 and slots['used'] == 2 and slots['free'] == 0


def test_the_heartbeat_of_each_instance_is_read_from_its_lease(run):
    run_dir, database = run
    registry = _registry(database)
    registry.acquire('agent-live', lease_id='lease-live')
    registry.acquire('agent-gone', lease_id='lease-gone')
    registry.acquire('agent-lost', lease_id='lease-lost')
    registry.acquire('agent-bare')
    _lease(database, 'lease-live', NOW - 10, NOW + 100)
    _lease(database, 'lease-gone', NOW - 500, NOW - 1, state='expired')
    beats = {row['agent_id']: row['heartbeat'] for row in agent_map.view(run_dir, NOW)['instances']}
    assert beats['agent-live']['state'] == 'MEASURED' and beats['agent-live']['age_s'] == 10
    assert beats['agent-live']['stale'] is False and beats['agent-live']['heartbeat_at'].endswith('Z')
    assert beats['agent-gone']['state'] == 'MEASURED' and beats['agent-gone']['age_s'] == 500 and beats['agent-gone']['stale'] is True
    assert beats['agent-lost']['state'] == 'UNVERIFIED' and beats['agent-lost']['age_s'] is None
    assert 'lease-lost' in beats['agent-lost']['reason']
    assert beats['agent-bare'] == {'state': 'UNVERIFIED', 'heartbeat_at': None, 'age_s': None, 'stale': None, 'reason': 'agente sem lease_id'}


def test_a_lease_with_a_heartbeat_in_the_future_is_not_a_measurement(run):
    run_dir, database = run
    _registry(database).acquire('agent-a', lease_id='lease-a')
    _lease(database, 'lease-a', NOW + 500, NOW + 900)
    beat = agent_map.view(run_dir, NOW)['instances'][0]['heartbeat']
    assert beat['state'] == 'UNVERIFIED' and beat['age_s'] is None and beat['reason'] == 'heartbeat_at no futuro do relógio'


def test_more_than_fifty_agents_list_fifty_and_count_all(run):
    run_dir, database = run
    registry = _registry(database, capacity=200)
    for index in range(60):
        registry.acquire('agent-%02d' % index)
    out = agent_map.view(run_dir, NOW)
    assert len(out['instances']) == agent_map.MAX_INSTANCES == 50
    assert out['instances_total'] == 60 and out['counts']['pending'] == 60
    assert out['instances'][0]['agent_id'] == 'agent-00' and out['instances'][-1]['agent_id'] == 'agent-49'
    assert out['slots']['used'] == 60 and out['slots']['free'] == 140


def test_reading_never_creates_or_changes_a_file_of_the_store(run):
    run_dir, database = run
    registry = _registry(database)
    registry.acquire('agent-a', lease_id='lease-a')
    _lease(database, 'lease-a', NOW - 1, NOW + 50)
    folder = database.parent
    before = ({name: (folder / name).read_bytes() for name in os.listdir(folder)}, sorted(os.listdir(folder)))
    for _ in range(3):
        assert agent_map.view(run_dir, NOW)['state'] == 'MEASURED'
    after = ({name: (folder / name).read_bytes() for name in os.listdir(folder)}, sorted(os.listdir(folder)))
    assert after == before
