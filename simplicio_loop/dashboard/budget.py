'''Run budget reading for the Simplicio Live dashboard (issue #1404).

The declared limits come from the run's ``task-contract.json`` (sum over tasks of ``routing.budget``). Usage comes from
the ``token_usage`` and ``cost_sample`` events and from the event clock. The projection extrapolates usage by phase
progress, so it is an estimate and always carries ``proof_kind: estimado``. A figure with no declared limit, no
measured usage or no progress to extrapolate from is UNVERIFIED, never a pass.
'''
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from simplicio_loop.progress import PHASES

KEYS = ('tokens', 'usd', 'seconds')
SCHEMA = 'simplicio.dashboard-event/v1'
MAX_CONTRACT_BYTES = 1_000_000


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)) or value < 0:
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


def price_for(models: dict[str, Any], model: str) -> dict[str, Any] | None:
    '''The longest table key that prefixes the model id, so a dated id takes its family's price.

    Same rule as priceFor in static/live/economy.js; the two must agree (tests/test_dashboard_economy_pricing_contract_unit.py).
    '''
    best = None
    for key in models:
        if model.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    return models[best] if best is not None else None


def cost_estimate(events: Iterable[dict[str, Any]], prices: dict[str, Any] | None) -> dict[str, Any]:
    '''USD for the run: measured input/output tokens per model times the price table. Always an estimate.

    UNVERIFIED (with the reason) when no tokens were measured, the table is missing, or a model has no price.
    '''
    row: dict[str, Any] = {'usd': None, 'state': 'UNVERIFIED', 'proof_kind': 'estimado', 'reason': None,
                           'as_of': None, 'source_url': None, 'by_model': {}}
    per_model: dict[str, list[float]] = {}
    for event in events:
        if not isinstance(event, dict) or event.get('schema') != SCHEMA or event.get('kind') != 'token_usage':
            continue
        payload = event.get('payload') if isinstance(event.get('payload'), dict) else {}
        tokens_in, tokens_out = _number(payload.get('input_tokens')), _number(payload.get('output_tokens'))
        if not (tokens_in or 0) + (tokens_out or 0):
            continue
        model = payload.get('model') if isinstance(payload.get('model'), str) and payload.get('model') else ''
        totals = per_model.setdefault(model, [0, 0])
        totals[0] += tokens_in or 0
        totals[1] += tokens_out or 0
    table = prices.get('models') if isinstance(prices, dict) and isinstance(prices.get('models'), dict) else None
    if isinstance(prices, dict):
        row['as_of'], row['source_url'] = prices.get('as_of'), prices.get('source_url')
    if not per_model:
        row['reason'] = 'tokens não medidos: nenhum token_usage com contagem registrada pelo run'
        return row
    if table is None:
        row['reason'] = 'tabela de preços indisponível'
        return row
    total = 0.0
    for model, (tokens_in, tokens_out) in sorted(per_model.items()):
        price = price_for(table, model)
        in_rate = _number(price.get('input_per_mtok')) if isinstance(price, dict) else None
        out_rate = _number(price.get('output_per_mtok')) if isinstance(price, dict) else None
        if in_rate is None or out_rate is None:
            row['reason'] = 'sem preço na tabela para o modelo %r' % (model or 'desconhecido')
            row['usd'] = None
            row['by_model'] = {}
            return row
        usd = (tokens_in * in_rate + tokens_out * out_rate) / 1_000_000
        row['by_model'][model] = round(usd, 6)
        total += usd
    row['usd'] = round(total, 6)
    row['state'] = 'ESTIMADO'
    return row


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


def report(run_dir: str | Path, events: list[dict[str, Any]], prices: dict[str, Any] | None = None) -> dict[str, Any]:
    '''The budget panel payload for one run: limits, usage and one projection per dimension.'''
    limits = declared(run_dir)
    used = usage(events)
    phase = current_phase(events)
    measured = {'tokens': used['tokens'], 'usd': used['usd'], 'seconds': elapsed_s(events)}
    return {'phase': phase, 'limits': limits, 'usage': used, 'cost': cost_estimate(events, prices),
            'rows': {key: project(limits[key], measured[key], phase) for key in KEYS}}


COMPARE_FIELDS = ('duration_s', 'tokens', 'cost_usd', 'iterations')
COMPARE_WINDOW = 10


def compare(current: dict[str, Any], previous: list[dict[str, Any]]) -> dict[str, Any]:
    '''This run against the average of the last ten finished runs (history records, newest first).

    The current run and runs still running are skipped. A value no run measured is UNVERIFIED, never zero.
    '''
    window = [r for r in previous if r.get('run_id') != current.get('run_id') and r.get('verdict') != 'RUNNING'][:COMPARE_WINDOW]
    fields: dict[str, Any] = {}
    for key in COMPARE_FIELDS:
        values = [v for v in (_number(r.get(key)) for r in window) if v is not None]
        now = _number(current.get(key))
        row: dict[str, Any] = {'current': now, 'average': None, 'samples': len(values), 'delta_pct': None, 'state': 'UNVERIFIED'}
        if values and now is not None:
            average = sum(values) / len(values)
            row['average'] = average
            row['state'] = 'ESTIMADO'
            if average > 0:
                row['delta_pct'] = round((now - average) / average * 100, 1)
        fields[key] = row
    return {'runs': len(window), 'fields': fields}
