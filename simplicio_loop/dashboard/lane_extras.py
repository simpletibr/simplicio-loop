'''Per-run extras for the Simplicio Live dashboard: last measured command, declared tasks, model per lane, heartbeat.

A pure reader over the run directory and its events. Every figure is what the run recorded; a figure with no record
is absent (None or an empty list), never invented. The heartbeat of each lane comes from the backlog lease that
scripts/task_backlog.py writes, read through the coordination reader; a lane whose lease cannot be found stays
UNVERIFIED with the reason.
'''
from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from simplicio_loop.dashboard import budget, coordination
from simplicio_loop.dashboard.runs import redact_text

SCHEMA = 'simplicio.dashboard-extras/v1'
EVENT_SCHEMA = 'simplicio.dashboard-event/v1'
MAX_ITEMS = 50
COMMAND_MAX = 300
TITLE_MAX = 160
COMMAND_KINDS = frozenset({'test_result', 'lint_result'})
BACKLOG_PARTS = ('orchestrator', 'backlog', 'backlog.jsonl')
LEASE_ID_KEYS = ('lease_id', 'attempt_id', 'fencing_token', 'fence')
NO_LANE_REASON = 'nenhuma lane com lease_id registrado'


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


def _lane_claims(ordered: list[dict[str, Any]]) -> dict[str, str]:
    '''Lease id of the latest worker_claimed of each lane ('' when it carried none), lane by event or by its task.'''
    task_lane = {task: lane for e in ordered if (task := _text(e.get('task_id'))) and (lane := _text(e.get('lane')))}
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


def _lane_row(lane: str, lease_id: str, leases: list[dict[str, Any]], failure: str | None, now: float) -> dict[str, Any]:
    row: dict[str, Any] = {'lane': lane, 'lease_id': lease_id or None, 'state': 'UNVERIFIED', 'heartbeat_at': None,
                           'age_s': None, 'stale': None, 'reason': None}
    if not lease_id:
        row['reason'] = 'lane sem lease_id registrado'
        return row
    lease = next((raw for raw in leases if lease_id in {raw.get(key) for key in LEASE_ID_KEYS}), None)
    view = coordination._lease_view(lease, now) if lease else None
    if failure or view is None:
        row['reason'] = failure or f'lease {lease_id} não está no backlog'
    elif view['age_s'] is None:
        row['reason'] = 'lease sem heartbeat_at medido'
    else:
        row.update(state='MEASURED', heartbeat_at=view['heartbeat_at'], age_s=max(0, view['age_s']),
                   stale=view['state'] != 'live')
    return row


def _row_text(row: dict[str, Any]) -> str:
    if row['state'] != 'MEASURED':
        return f"{row['lane']}: {row['reason']}"
    return f"{row['lane']}: batimento há {row['age_s']} s" + (' (obsoleto)' if row['stale'] else '')


def _heartbeat(claims: dict[str, str], run_dir: str | Path, backlog_path: str | Path | None, now: float) -> dict[str, Any]:
    '''Heartbeat of every claimed lane lease; PASS when at least one is measured, else UNVERIFIED with the reasons.'''
    if not claims:
        return {'state': 'UNVERIFIED', 'reason': NO_LANE_REASON, 'lanes': []}
    leases, failure = _leases(_backlog_file(run_dir, backlog_path))
    rows = [_lane_row(lane, claims[lane], leases, failure, now) for lane in sorted(claims)][:MAX_ITEMS]
    measured = any(row['state'] == 'MEASURED' for row in rows)
    return {'state': 'PASS' if measured else 'UNVERIFIED', 'reason': '; '.join(_row_text(row) for row in rows),
            'lanes': rows}


def extras(run_dir: str | Path, events: Iterable[Any], backlog_path: str | Path | None = None,
           now: float | None = None) -> dict[str, Any]:
    '''The run's extras: last measured command, declared tasks, model per lane and the heartbeat of each lane lease.

    Only dashboard events are read, in ascending seq order, so the latest record wins. ``now`` (epoch seconds, default
    the wall clock) is the clock the heartbeat age is measured against; ``backlog_path`` overrides the backlog file.
    '''
    ordered = sorted((e for e in events if isinstance(e, dict) and e.get('schema') == EVENT_SCHEMA), key=_seq)
    current = time.time() if now is None else float(now)
    return {'schema': SCHEMA, 'last_command': _last_command(ordered), 'tasks': _tasks(run_dir),
            'models': _models(ordered),
            'heartbeat': _heartbeat(_lane_claims(ordered), run_dir, backlog_path, current)}
