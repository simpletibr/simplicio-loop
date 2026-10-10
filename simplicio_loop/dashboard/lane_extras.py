'''Per-run extras for the Simplicio Live dashboard: last measured command, command running now, declared tasks, model per lane, heartbeat.

A pure reader over the run directory and its events. Every figure is what the run recorded; a figure with no record
is absent (None or an empty list), never invented. The heartbeat of each lane is matched on the lane's lease_id only
(from its worker_claimed event; a lease_id held by two backlog items is ambiguous, so UNVERIFIED). The runner's lease_id
is a Mapper OperationsStore id, so it is read from the ``ops_leases`` table of the run's store
(``<repo>/.simplicio-loop/data/operations.sqlite``, or $SIMPLICIO_MAPPER_OPERATIONS_DB as the runner resolves it),
opened read-only with stdlib sqlite3 and never created or written. A backlog lease that carries the same lease_id is read
through the coordination reader first. A lane whose lease cannot be found, or whose store is missing, locked or corrupt,
stays UNVERIFIED with the reason.

The watcher renews the lease of the issue it works on while turbo runs and writes each renewal as a ``lease_heartbeat`` event
of the run (``lease_key`` = ``repo#number``, ``status`` ``renewed`` or ``lost``, ``ttl_s``). The latest beat of each key is one more
row of the heartbeat: its age is the ``ts`` of the event against the clock passed in, and it is stale once older than its
own ``ttl_s``, or at any age when the lease was lost. A beat with no readable ``ts`` or ``ttl_s`` is UNVERIFIED with the reason.

The command running now is the latest ``command_started`` of a lane (paired by ``command_id``) that has no ``command_finished`` and
is not older than the last ``run_finished``; its age is the ``ts`` of the start against the clock passed in. A start with no finish
after ``STUCK_AFTER_S`` is flagged with its age, never hidden or presumed dead; a start with no readable ``ts`` is UNVERIFIED.
'''
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from simplicio_loop.dashboard import budget, coordination
from simplicio_loop.dashboard.runs import redact_command, redact_text

SCHEMA = 'simplicio.dashboard-extras/v1'
EVENT_SCHEMA = 'simplicio.dashboard-event/v1'
MAX_ITEMS = 50
COMMAND_MAX = 300
RUNNING_MAX = 200
STUCK_AFTER_S = 600
NO_COMMAND_REASON = 'nenhum command_started no run'
IDLE_REASON = 'nenhum comando em execução segundo os eventos'
TITLE_MAX = 160
COMMAND_KINDS = frozenset({'test_result', 'lint_result'})
BACKLOG_PARTS = ('orchestrator', 'backlog', 'backlog.jsonl')
NO_LANE_REASON = 'nenhuma lane com lease_id registrado'
BEAT_KIND = 'lease_heartbeat'
STORE_ENV = 'SIMPLICIO_MAPPER_OPERATIONS_DB'
STORE_PARTS = ('data', 'operations.sqlite')
STORE_TIMEOUT_S = 0.25


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _seq(event: dict[str, Any]) -> int:
    seq = event.get('seq')
    return seq if isinstance(seq, int) and not isinstance(seq, bool) else -1


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    return event['payload'] if isinstance(event.get('payload'), dict) else {}


def _last_command(ordered: list[dict[str, Any]]) -> dict[str, Any] | None:
    found = None
    for event in ordered:
        command = _text(_payload(event).get('command'))
        if event.get('kind') in COMMAND_KINDS and command:
            found = {'command': redact_text(command)[:COMMAND_MAX], 'kind': event['kind'],
                     'at': str(event.get('ts') or '')}
    return found


def _tasks(run_dir: str | Path) -> list[dict[str, str]]:
    path = Path(run_dir) / 'task-contract.json'
    try:
        if path.stat().st_size > budget.MAX_CONTRACT_BYTES:
            return []
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    raw = data.get('tasks') if isinstance(data, dict) else None
    tasks: list[dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        task_id = _text(item.get('id')) or _text(item.get('task_id'))
        title = _text(item.get('title')) or _text(item.get('name'))
        if task_id and title:
            tasks.append({'task_id': task_id, 'title': redact_text(title)[:TITLE_MAX]})
    return tasks[:MAX_ITEMS]


def _models(ordered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for event in ordered:
        lane = _text(event.get('lane'))
        model = _text(_payload(event).get('model'))
        if event.get('kind') != 'token_usage' or not (lane and model):
            continue
        row = rows.setdefault(lane, {'lane': lane, 'model': model, 'input_tokens': 0, 'output_tokens': 0})
        row['model'] = model
        row['input_tokens'] += _count(_payload(event).get('input_tokens'))
        row['output_tokens'] += _count(_payload(event).get('output_tokens'))
    return [rows[lane] for lane in sorted(rows)][:MAX_ITEMS]


def _task_lanes(ordered: list[dict[str, Any]]) -> dict[str, str]:
    '''The lane each task was last seen on: an event that names both.'''
    return {task: lane for e in ordered if (task := _text(e.get('task_id'))) and (lane := _text(e.get('lane')))}


def _lane_claims(ordered: list[dict[str, Any]]) -> dict[str, str]:
    '''Lease id of the latest worker_claimed of each lane ('' when it carried none), lane by event or by its task.'''
    task_lane = _task_lanes(ordered)
    claims: dict[str, str] = {}
    for event in ordered:
        lane = _text(event.get('lane')) or task_lane.get(_text(event.get('task_id')) or '')
        if event.get('kind') == 'worker_claimed' and lane:
            claims[lane] = _text(_payload(event).get('lease_id')) or ''
    return claims


def _backlog_file(run_dir: str | Path, backlog_path: str | Path | None) -> Path:
    '''The given backlog, else $SIMPLICIO_BACKLOG_FILE, else the orchestrator backlog of the run's .simplicio-loop.'''
    if backlog_path:
        return Path(backlog_path)
    override = os.environ.get('SIMPLICIO_BACKLOG_FILE')
    return Path(override) if override else Path(run_dir).parent.parent.joinpath(*BACKLOG_PARTS)


def _leases(backlog: Path) -> tuple[list[dict[str, Any]], str | None]:
    '''Every lease object of the backlog items, or the reason the backlog could not be read.'''
    try:
        _, items = coordination._read_backlog(backlog)
    except coordination._Unreadable as exc:
        return [], f'backlog não lido: {exc}'
    return [item['lease'] for item in items if isinstance(item.get('lease'), dict)], None


def _store_file(run_dir: str | Path) -> Path | None:
    '''The run's Mapper operations store as the runner resolves it: the env override, else the .simplicio-loop above the run.'''
    explicit = os.environ.get(STORE_ENV, '').strip()
    if explicit:
        return Path(explicit).expanduser().absolute()
    for parent in Path(run_dir).absolute().parents:
        if parent.name == '.simplicio-loop':
            return parent.joinpath(*STORE_PARTS)
    return None


SQLITE_HEAD = b'SQLite format 3\x00'
LEASE_SQL = ('SELECT l.state, l.heartbeat_at, l.expires_at, a.created_at, a.updated_at FROM ops_leases l '
             'LEFT JOIN ops_attempts a ON a.attempt_id = l.attempt_id WHERE l.lease_id = ?')


def _idle_wal(database: Path) -> bool:
    '''A WAL database with no -wal and no -shm: no connection holds it, so every commit is already in the main file.

    Opening such a file with mode=ro still makes SQLite create the empty -wal/-shm next to it, which would touch the
    store's files. immutable=1 avoids that and is only used here: it is NOT safe for a database a writer holds open,
    and those always have the sidecars.
    '''
    if any(Path(f'{database}{suffix}').exists() for suffix in ('-wal', '-shm')):
        return False
    try:
        with open(database, 'rb') as handle:
            head = handle.read(20)
    except OSError:
        return False
    return len(head) == 20 and head[:16] == SQLITE_HEAD and head[18] == 2 and head[19] == 2


class _Store:
    '''Read-only handle on the Mapper store for one request: one connection, and a failure is remembered for every lane,
    so a locked or corrupt store costs one timeout, not one per lane.'''

    def __init__(self, database: Path) -> None:
        self.database = database
        self._con: sqlite3.Connection | None = None
        self._down: str | None = None

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None

    def _connect(self) -> sqlite3.Connection:
        if self._con is None:
            uri = f'{self.database.absolute().as_uri()}?mode=ro' + ('&immutable=1' if _idle_wal(self.database) else '')
            self._con = sqlite3.connect(uri, uri=True, timeout=STORE_TIMEOUT_S)
        return self._con

    def view(self, lease_id: str, now: float) -> tuple[dict[str, Any] | None, str | None]:
        '''Heartbeat of ``lease_id`` in ops_leases (parameterised), or the reason it cannot be measured.'''
        if self._down:
            return None, self._down
        if not self.database.is_file():
            self._down = f'{self.database.name} ausente'
            return None, self._down
        try:
            row = self._connect().execute(LEASE_SQL, (lease_id,)).fetchone()
        except UnicodeError:
            return None, 'lease_id não é texto válido'
        except sqlite3.Error as exc:
            self._down = f'store não lido: {exc}'
            return None, self._down
        if row is None:
            return None, f'lease {lease_id} não está no store de operações'
        state, beat, expires, created, updated = row
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (beat, expires)):
            return None, 'lease do store sem heartbeat_at medido'
        live = state == 'active' and expires > now and now - beat <= (expires - beat) / 2
        # The claim writes heartbeat_at and the attempt's created_at/updated_at together; only .heartbeat() moves updated_at.
        beats = (updated != created) if state == 'active' and created is not None and updated is not None else None
        return {'heartbeat_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(beat)), 'age_s': int(now - beat),
                'state': 'live' if live else 'stale', 'beats': beats,
                'expired': state != 'active' or expires <= now}, None

    def read(self, sql: str, params: tuple = ()) -> tuple[list[tuple] | None, str | None]:
        '''Rows of one parameterised read-only query, or the reason the store cannot be read (remembered for the whole request).'''
        if self._down:
            return None, self._down
        if not self.database.is_file():
            self._down = f'{self.database.name} ausente'
            return None, self._down
        try:
            return self._connect().execute(sql, params).fetchall(), None
        except sqlite3.Error as exc:
            self._down = f'store não lido: {exc}'
            return None, self._down


def _lane_row(lane: str, lease_id: str, leases: list[dict[str, Any]], failure: str | None, now: float,
              store: _Store | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {'lane': lane, 'lease_id': lease_id or None, 'state': 'UNVERIFIED', 'heartbeat_at': None,
                           'age_s': None, 'stale': None, 'reason': None}
    if not lease_id:
        row['reason'] = 'lane sem lease_id registrado'
        return row
    found = [raw for raw in leases if raw.get('lease_id') == lease_id]
    if len(found) > 1:
        row['reason'] = f'lease {lease_id} aparece em mais de um item do backlog'
        return row
    if found:
        view = coordination._lease_view(found[0], now)
        reason = None if view else f'lease {lease_id} sem worker no backlog'
    else:
        view, reason = None, failure or f'lease {lease_id} não está no backlog'
        if store is not None:
            view, why = store.view(lease_id, now)
            reason = f'{reason}; {why}' if why else None
    if view is not None and view['age_s'] is None:
        reason = 'lease sem heartbeat_at medido'
    elif view is not None and view['age_s'] < 0:
        reason = 'heartbeat_at no futuro do relógio'
    if view is None or reason is not None:
        row['reason'] = reason
        return row
    beat = view.get('beats')
    # A lease nobody beats (the runner's claim is never heartbeated) is only stale once it has expired, not at half its ttl.
    stale = view['expired'] if beat is False else view['state'] != 'live'
    row.update(state='MEASURED', heartbeat_at=view['heartbeat_at'], age_s=view['age_s'], stale=stale)
    if beat is not None:   # only a Mapper store lease says whether anyone ever beat it
        row['beat'] = beat
    return row


def _beat_row(key: str, event: dict[str, Any], now: float) -> dict[str, Any]:
    '''The row of one lease key from its latest ``lease_heartbeat`` event.'''
    payload = _payload(event)
    status = payload.get('status')
    row: dict[str, Any] = {'lane': _text(event.get('lane')) or key, 'lease_id': key, 'state': 'UNVERIFIED', 'heartbeat_at': None,
                           'age_s': None, 'stale': None, 'reason': None, 'source': BEAT_KIND, 'status': status}
    at = budget._parse(event.get('ts'))
    ttl = payload.get('ttl_s')
    if at is None:
        row['reason'] = 'lease_heartbeat sem ts medido'
    elif now - at.timestamp() < 0:
        row['reason'] = 'lease_heartbeat no futuro do relógio'
    elif isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not 0 < ttl < math.inf:
        row['reason'] = 'lease_heartbeat sem ttl_s medido'
    else:
        age = int(now - at.timestamp())
        row.update(state='MEASURED', heartbeat_at=str(event['ts']), age_s=age, stale=status == 'lost' or age > ttl)
    return row


def _beat_rows(ordered: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
    '''One row per lease key: its latest ``lease_heartbeat`` (the list is in ascending seq, so the last one wins).'''
    latest = {key: event for event in ordered
              if event.get('kind') == BEAT_KIND and (key := _text(_payload(event).get('lease_key')))}
    return [_beat_row(key, latest[key], now) for key in sorted(latest)]


def _row_text(row: dict[str, Any]) -> str:
    if row['state'] != 'MEASURED':
        return f"{row['lane']}: {row['reason']}"
    if row.get('status') == 'lost':
        return f"{row['lane']}: lease perdido há {row['age_s']} s"
    if row.get('beat') is False:
        return f"{row['lane']}: sem batimento registrado desde o claim (claim há {row['age_s']} s)" + (
            ' (lease expirado)' if row['stale'] else '')
    return f"{row['lane']}: último batimento há {row['age_s']} s" + (' (obsoleto)' if row['stale'] else '')


def _claim_rows(claims: dict[str, str], run_dir: str | Path, backlog_path: str | Path | None, now: float) -> list[dict[str, Any]]:
    '''The row of every claimed lane lease, from the backlog or the Mapper store.'''
    if not claims:
        return []
    leases, failure = _leases(_backlog_file(run_dir, backlog_path))
    path = _store_file(run_dir)
    store = _Store(path) if path is not None else None
    try:
        return [_lane_row(lane, claims[lane], leases, failure, now, store) for lane in sorted(claims)]
    finally:
        if store is not None:
            store.close()


def _heartbeat(claims: dict[str, str], beats: list[dict[str, Any]], run_dir: str | Path, backlog_path: str | Path | None,
               now: float) -> dict[str, Any]:
    '''Heartbeat of every claimed lane lease and of every watcher lease beat; PASS when at least one is measured, else UNVERIFIED.'''
    rows = (_claim_rows(claims, run_dir, backlog_path, now) + beats)[:MAX_ITEMS]
    if not rows:
        return {'state': 'UNVERIFIED', 'reason': NO_LANE_REASON, 'lanes': []}
    measured = any(row['state'] == 'MEASURED' for row in rows)
    return {'state': 'PASS' if measured else 'UNVERIFIED', 'reason': '; '.join(_row_text(row) for row in rows),
            'lanes': rows}


def _running_row(event: dict[str, Any], lane: str | None, now: float) -> dict[str, Any]:
    payload = _payload(event)
    row: dict[str, Any] = {'lane': lane, 'task_id': _text(event.get('task_id')), 'command_id': payload['command_id'],
                           'command': redact_command(payload['command'])[:RUNNING_MAX], 'started_at': None, 'age_s': None,
                           'stuck': None, 'state': 'UNVERIFIED', 'reason': None}
    started = budget._parse(event.get('ts'))
    if started is None:
        row['reason'] = 'command_started sem ts medido'
    elif now - started.timestamp() < 0:
        row['reason'] = 'command_started no futuro do relógio'
    else:
        age = int(now - started.timestamp())
        row.update(state='MEASURED', started_at=str(event['ts']), age_s=age, stuck=age > STUCK_AFTER_S)
    return row


def _running_text(row: dict[str, Any]) -> str:
    name = row['lane'] or row['task_id'] or 'run'
    if row['state'] != 'MEASURED':
        return f"{name}: {row['reason']}"
    flag = f", sem fim registrado (limite {STUCK_AFTER_S} s)" if row['stuck'] else ''
    return f"{name}: em execução há {row['age_s']} s{flag}: {row['command']}"


def _running_command(ordered: list[dict[str, Any]], now: float) -> dict[str, Any]:
    '''The command each lane is running: its latest command_started with no command_finished of the same command_id.'''
    starts = [e for e in ordered if e.get('kind') == 'command_started'
              and _text(_payload(e).get('command_id')) and _text(_payload(e).get('command'))]
    if not starts:
        return {'state': 'UNVERIFIED', 'reason': NO_COMMAND_REASON, 'lanes': []}
    done = {cid for e in ordered if e.get('kind') == 'command_finished' and (cid := _text(_payload(e).get('command_id')))}
    ended = max((_seq(e) for e in ordered if e.get('kind') == 'run_finished'), default=-1)
    task_lane = _task_lanes(ordered)
    latest: dict[str, tuple[dict[str, Any], str | None]] = {}
    for event in starts:
        if _payload(event)['command_id'] in done or _seq(event) < ended:
            continue
        lane = _text(event.get('lane')) or task_lane.get(_text(event.get('task_id')) or '')
        latest[lane or _text(event.get('task_id')) or ''] = (event, lane)
    rows = [_running_row(event, lane, now) for _, (event, lane) in sorted(latest.items())][:MAX_ITEMS]
    if not rows:
        return {'state': 'PASS', 'reason': IDLE_REASON, 'lanes': []}
    return {'state': 'PASS' if any(row['state'] == 'MEASURED' for row in rows) else 'UNVERIFIED',
            'reason': '; '.join(_running_text(row) for row in rows), 'lanes': rows}


def extras(run_dir: str | Path, events: Iterable[Any], backlog_path: str | Path | None = None,
           now: float | None = None) -> dict[str, Any]:
    '''The run's extras: last measured command, the command running now, declared tasks, model per lane, the measured token series
    (the sparkline) and lane lease heartbeats.

    Only dashboard events are read, in ascending seq order, so the latest record wins. ``now`` (epoch seconds, default
    the wall clock) is the clock the heartbeat age is measured against; ``backlog_path`` overrides the backlog file.
    '''
    ordered = sorted((e for e in events if isinstance(e, dict) and e.get('schema') == EVENT_SCHEMA), key=_seq)
    current = time.time() if now is None else float(now)
    return {'schema': SCHEMA, 'last_command': _last_command(ordered), 'running_command': _running_command(ordered, current),
            'tasks': _tasks(run_dir), 'models': _models(ordered), 'tokens_series': budget.token_series(ordered),
            'heartbeat': _heartbeat(_lane_claims(ordered), _beat_rows(ordered, current), run_dir, backlog_path, current)}
