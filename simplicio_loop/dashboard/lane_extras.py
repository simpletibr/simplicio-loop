'''Per-run extras for the Simplicio Live dashboard: last measured command, declared tasks, model per lane, heartbeat.

A pure reader over the run directory and its events. Every figure is what the run recorded; a figure with no record
is absent (None or an empty list), never invented. The heartbeat stays UNVERIFIED until a lease heartbeat producer
exists.
'''
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from simplicio_loop.dashboard import budget
from simplicio_loop.dashboard.runs import redact_text

SCHEMA = 'simplicio.dashboard-extras/v1'
EVENT_SCHEMA = 'simplicio.dashboard-event/v1'
MAX_ITEMS = 50
COMMAND_MAX = 300
TITLE_MAX = 160
COMMAND_KINDS = frozenset({'test_result', 'lint_result'})
HEARTBEAT = {'state': 'UNVERIFIED', 'reason': 'no lease heartbeat producer'}


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


def extras(run_dir: str | Path, events: Iterable[Any]) -> dict[str, Any]:
    '''The run's extras: last measured command, declared tasks, model per lane and the heartbeat state.

    Only dashboard events are read, in ascending seq order, so the latest record wins.
    '''
    ordered = sorted((e for e in events if isinstance(e, dict) and e.get('schema') == EVENT_SCHEMA), key=_seq)
    return {'schema': SCHEMA, 'last_command': _last_command(ordered), 'tasks': _tasks(run_dir),
            'models': _models(ordered), 'heartbeat': dict(HEARTBEAT)}
