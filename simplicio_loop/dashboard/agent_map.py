'''Measured agent map of a run for the Simplicio Live dashboard (issue #1550): the agent instances, the slots in use, the lease
each instance holds and the heartbeat of that lease.

Source: the Mapper OperationsStore the run uses. ``ops_agent_slots`` and ``operations_meta`` hold the instances and the slot
capacity, ``ops_leases`` the heartbeat. The store is opened read-only through the lane_extras reader and never created or
written. A store that is missing, locked or unreadable, a store with no agent and a lease with no recorded heartbeat stay
UNVERIFIED with the reason, and no count is invented.
'''
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from simplicio_loop.dashboard import lane_extras

MAX_INSTANCES = 50
STATUSES = ('pending', 'running', 'completed', 'shutdown', 'reclaimable')
ACTIVE = ('pending', 'running')
NO_STORE = 'store de operações não localizado para o run'
NO_AGENTS = 'nenhum agente registrado no store de operações'
NO_CAPACITY = 'capacidade de slots não registrada'
AGENTS_SQL = 'SELECT agent_id, status, attempt, worktree, lease_id FROM ops_agent_slots ORDER BY agent_id'
CAPACITY_SQL = "SELECT value FROM operations_meta WHERE key = 'agent_slot_capacity'"


def _slots(capacity: int | None, used: int, reason: str | None) -> dict[str, Any]:
    if capacity is None:
        return {'state': 'UNVERIFIED', 'capacity': None, 'used': None, 'free': None, 'reason': reason or NO_CAPACITY}
    return {'state': 'MEASURED', 'capacity': capacity, 'used': used, 'free': max(0, capacity - used), 'reason': None}


def _unverified(reason: str) -> dict[str, Any]:
    return {'state': 'UNVERIFIED', 'reason': reason, 'slots': _slots(None, 0, reason), 'counts': {}, 'instances': [],
            'instances_total': 0}


def _capacity(store: Any) -> tuple[int | None, str | None]:
    rows, why = store.read(CAPACITY_SQL)
    if rows is None:
        return None, why
    try:
        value = int(rows[0][0]) if rows else 0
    except (TypeError, ValueError):
        value = 0
    return (value, None) if value > 0 else (None, NO_CAPACITY)


def _heartbeat(store: Any, lease_id: str | None, now: float) -> dict[str, Any]:
    row: dict[str, Any] = {'state': 'UNVERIFIED', 'heartbeat_at': None, 'age_s': None, 'stale': None, 'reason': None}
    if not lease_id:
        row['reason'] = 'agente sem lease_id'
        return row
    view, why = store.view(lease_id, now)
    if view is None:
        row['reason'] = why
        return row
    if view['age_s'] < 0:
        row['reason'] = 'heartbeat_at no futuro do relógio'
        return row
    row.update(state='MEASURED', heartbeat_at=view['heartbeat_at'], age_s=view['age_s'], stale=view['state'] != 'live')
    return row


def view(run_dir: str | Path, now: float | None = None) -> dict[str, Any]:
    '''The run's agent map: ``slots`` (capacity, used, free), ``counts`` by status, and up to MAX_INSTANCES ``instances`` in
    agent_id order, each with its lease and the ``heartbeat`` of that lease. ``now`` (epoch seconds, default the wall clock)
    is the clock the heartbeat age is measured against.'''
    current = time.time() if now is None else float(now)
    database = lane_extras._store_file(run_dir)
    if database is None:
        return _unverified(NO_STORE)
    store = lane_extras._Store(database)
    try:
        agents, why = store.read(AGENTS_SQL)
        if agents is None:
            return _unverified(why or NO_STORE)
        if not agents:
            return _unverified(NO_AGENTS)
        counts = {status: 0 for status in STATUSES}
        for _, status, *_ in agents:
            if status in counts:
                counts[status] += 1
        capacity, capacity_why = _capacity(store)
        instances = [{'agent_id': agent_id, 'status': status, 'attempt': attempt, 'worktree': worktree, 'lease_id': lease_id,
                      'heartbeat': _heartbeat(store, lease_id, current)}
                     for agent_id, status, attempt, worktree, lease_id in agents[:MAX_INSTANCES]]
        return {'state': 'MEASURED', 'reason': None, 'slots': _slots(capacity, sum(counts[s] for s in ACTIVE), capacity_why),
                'counts': counts, 'instances': instances, 'instances_total': len(agents)}
    finally:
        store.close()
