'''Run budget reading for the Simplicio Live dashboard (issue #1404).

The declared limits come from the run's ``task-contract.json`` (sum over tasks of ``routing.budget``). Usage comes from
the ``token_usage`` and ``cost_sample`` events and from the event clock. The projection extrapolates usage by phase
progress, so it is an estimate and always carries ``proof_kind: estimado``. A figure with no declared limit, no
measured usage or no progress to extrapolate from is UNVERIFIED, never a pass.
'''
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from simplicio_loop.progress import PHASES

KEYS = ('tokens', 'usd', 'seconds')
SCHEMA = 'simplicio.dashboard-event/v1'
MAX_CONTRACT_BYTES = 1_000_000


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return value


def declared(run_dir: str | Path) -> dict[str, float | int | None]:
    '''Declared limits summed over the tasks; None for a dimension no task declares.'''
    totals: dict[str, float | int | None] = {key: None for key in KEYS}
    path = Path(run_dir) / 'task-contract.json'
    try:
        if path.stat().st_size > MAX_CONTRACT_BYTES:
            return totals
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return totals
    tasks = data.get('tasks') if isinstance(data, dict) else None
    for task in tasks if isinstance(tasks, list) else []:
        routing = task.get('routing') if isinstance(task, dict) else None
        limits = routing.get('budget') if isinstance(routing, dict) else None
        if not isinstance(limits, dict):
            continue
        for key in KEYS:
            value = _number(limits.get(key))
            if value is not None:
                totals[key] = (totals[key] or 0) + value
    return totals


def _bump(group: dict[str, int], key: Any, amount: int) -> None:
    if isinstance(key, str) and key:
        group[key] = group.get(key, 0) + amount


def usage(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    '''Tokens and USD summed from the producer events, grouped by phase, lane and model.'''
    tokens = 0
    usd = 0.0
    samples = 0
    cost_seen = False
    by_phase: dict[str, int] = {}
    by_lane: dict[str, int] = {}
    by_model: dict[str, int] = {}
    for event in events:
        if not isinstance(event, dict) or event.get('schema') != SCHEMA:
            continue
        payload = event.get('payload') if isinstance(event.get('payload'), dict) else {}
        if event.get('kind') == 'token_usage':
            parts = [_number(payload.get('input_tokens')), _number(payload.get('output_tokens'))]
            amount = int(sum(part for part in parts if part is not None))
            if amount <= 0:
                continue
            tokens += amount
            samples += 1
            _bump(by_phase, event.get('phase'), amount)
            _bump(by_lane, payload.get('lane'), amount)
            _bump(by_model, payload.get('model'), amount)
        elif event.get('kind') == 'cost_sample':
            value = _number(payload.get('usd'))
            if value is not None:
                usd += value
                cost_seen = True
    return {'tokens': tokens if samples else None, 'usd': usd if cost_seen else None, 'samples': samples,
            'by_phase': by_phase, 'by_lane': by_lane, 'by_model': by_model}


def _fraction(phase: str | None) -> float:
    if phase not in PHASES:
        return 0.0
    return PHASES.index(phase) / (len(PHASES) - 1)


def project(limit: float | int | None, used: float | int | None, phase: str | None) -> dict[str, Any]:
    '''One dimension: the limit, the measured use and the use extrapolated to the end of the run.'''
    row: dict[str, Any] = {'limit': limit, 'used': used, 'projected': None, 'state': 'UNVERIFIED',
                           'proof_kind': 'estimado', 'reason': None}
    if limit is None:
        row['reason'] = 'nenhum limite declarado no contrato da tarefa'
    elif used is None:
        row['reason'] = 'uso não medido: nenhum produtor de token_usage escreve eventos'
    elif used > limit:
        row['state'] = 'EXCEEDED'
    else:
        fraction = _fraction(phase)
        if fraction <= 0:
            row['reason'] = 'sem progresso de fase para projetar'
        else:
            projected = round(used / fraction, 4)
            row['projected'] = projected
            row['state'] = 'PROJECTED_OVER' if projected > limit else 'OK'
    return row


def _parse(ts: Any) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        parsed = datetime.fromisoformat(ts[:-1] + '+00:00' if ts.endswith('Z') else ts)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def elapsed_s(events: list[dict[str, Any]]) -> float | None:
    '''Seconds between the first and the last event timestamp; None when fewer than two are readable.'''
    stamps = [stamp for stamp in (_parse(e.get('ts')) for e in events if isinstance(e, dict)) if stamp]
    if len(stamps) < 2:
        return None
    return (max(stamps) - min(stamps)).total_seconds()


def current_phase(events: Iterable[dict[str, Any]]) -> str | None:
    phase = None
    for event in events:
        if isinstance(event, dict) and event.get('kind') == 'phase_entered' and isinstance(event.get('phase'), str):
            phase = event['phase']
    return phase


def report(run_dir: str | Path, events: list[dict[str, Any]]) -> dict[str, Any]:
    '''The budget panel payload for one run: limits, usage and one projection per dimension.'''
    limits = declared(run_dir)
    used = usage(events)
    phase = current_phase(events)
    measured = {'tokens': used['tokens'], 'usd': used['usd'], 'seconds': elapsed_s(events)}
    return {'phase': phase, 'limits': limits, 'usage': used,
            'rows': {key: project(limits[key], measured[key], phase) for key in KEYS}}
